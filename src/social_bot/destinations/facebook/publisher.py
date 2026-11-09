"""Facebook Page publisher.

Facebook reuses the Graph client in ``api.py``; this module is the *publishing*
seam that turns an approved draft into a real post. A draft with an image is a
photo post, and the image is **uploaded** (see ``media``) rather than handed to
Graph as a URL to fetch — the generator no longer serves its URLs anonymously,
so a URL post 401s from Facebook's side.

A draft with a video publishes to one of two placements, chosen per post
(``Draft.video_mode``): a **Reel** through ``/{page}/video_reels`` (the Reels
tab) or an ordinary **video post** through ``/{page}/videos`` (the feed). They
reach different audiences, so the operator picks.
"""

from __future__ import annotations

import time

from ... import media
from ...drafts import VIDEO_POST, Draft
from ..base import Publisher, PublisherError, PublishResult
from .api import ApiError, api_from_config

# Seconds to wait before commenting on a freshly created post. Facebook's
# Graph API can have a brief propagation delay before the post is available
# for commenting.
COMMENT_DELAY_SECONDS = 3


class FacebookPublisher(Publisher):
    name = "facebook"
    label = "Facebook"
    # Video goes out as a page destination; the placement (feed video or Reel)
    # is per draft — see ``Draft.video_mode``.
    supports_video = True

    def __init__(self, cfg: dict, token: str | None = None) -> None:
        super().__init__(cfg, token)
        self._api = None

    @property
    def api(self):
        if self._api is None:
            self._api = api_from_config(self.cfg, self.token)
        return self._api

    @classmethod
    def validate_config(cls, dst: dict) -> None:
        if not str(dst.get("api_version", "")).startswith("v"):
            raise ValueError("config: destinations.facebook.api_version must look like 'v26.0'")
        if not str(dst.get("base_url", "")).startswith("https://"):
            raise ValueError("config: destinations.facebook.base_url must be an https URL")
        if float(dst.get("timeout_seconds", 30)) <= 0:
            raise ValueError("config: destinations.facebook.timeout_seconds must be positive")

    def page_id(self, *, required: bool = True) -> str:
        page_id = str(self.config().get("account_id") or "").strip()
        if required and not page_id:
            raise ValueError("no page id: set destinations.facebook.account_id in config.yaml")
        return page_id

    def configured(self) -> bool:
        return bool(self.token_value()) and bool(self.page_id(required=False))

    def private(self) -> bool:
        """True when publish.private is on: post unpublished (admins only)."""
        return bool(self.cfg.get("publish", {}).get("private", False))

    def describe(self, draft: Draft) -> str:
        """The endpoint a real send would hit (dry-run text)."""
        page_id = self.page_id()
        if draft.video:
            if draft.video_mode == VIDEO_POST:
                endpoint = f"POST /{page_id}/videos"
                return f"{endpoint} (unpublished)" if self.private() else endpoint
            return (
                f"POST /{page_id}/video_reels (draft)"
                if self.private()
                else (f"POST /{page_id}/video_reels")
            )
        endpoint = f"POST /{page_id}/photos" if draft.image else f"POST /{page_id}/feed"
        return f"{endpoint} (unpublished)" if self.private() else endpoint

    def publish(self, draft: Draft) -> PublishResult:
        page_id = self.page_id()
        caption = draft.post_text
        private = self.private()
        if draft.video:
            if draft.video_mode == VIDEO_POST:
                return self._publish_video_post(draft, page_id, caption, private)
            return self._publish_reel(draft, page_id, caption, private)
        if draft.image:
            # Upload the bytes; never let Graph fetch the image URL itself. A
            # local image is read from disk, a remote one (a source cover, or a
            # legacy generated URL) is downloaded here — with the generator's
            # key, which is the only reason its URLs still resolve at all.
            try:
                image, filename, content_type = media.load(self.cfg, draft.image)
            except media.MediaError as exc:
                raise PublisherError(f"facebook: {exc}") from None
            resp = self.api.create_photo_post(
                page_id,
                caption,
                image,
                filename=filename,
                content_type=content_type,
                published=not private,
            )
        else:
            resp = self.api.create_post(page_id, caption, draft.url or None, published=not private)
        post_id = str(resp.get("post_id") or resp.get("id") or "")
        permalink = f"https://www.facebook.com/{post_id}" if "_" in post_id else ""
        self._comment_source_link(draft, post_id)

        return PublishResult(
            destination=self.name,
            post_id=post_id,
            permalink=permalink,
            private=private,
        )

    def _video_bytes(self, draft: Draft) -> tuple[bytes, str]:
        """The attached clip's bytes and filename (a local file, never fetched)."""
        try:
            return media.load_video(self.cfg, draft.video)
        except media.MediaError as exc:
            raise PublisherError(f"facebook: {exc}") from None

    def _publish_video_post(
        self, draft: Draft, page_id: str, caption: str, private: bool
    ) -> PublishResult:
        """Upload the clip as an ordinary video post in the page feed.

        One multipart POST to ``/{page}/videos`` — not a Reel: a feed video
        keeps its own placement and audience. The response carries the video
        id; the feed story's post id is the composite ``<page>_<video>``.
        """
        data, filename = self._video_bytes(draft)
        try:
            resp = self.api.create_video_post(
                page_id,
                caption,
                data,
                filename=filename,
                content_type=media.video_media_type(filename),
                published=not private,
            )
        except ApiError as exc:
            raise PublisherError(f"facebook: video upload failed: {exc}") from None

        video_id = str(resp.get("id") or resp.get("video_id") or "")
        if not video_id:
            raise PublisherError("facebook: video upload returned no video id")
        post_id = f"{page_id}_{video_id}"
        permalink = f"https://www.facebook.com/{page_id}/videos/{video_id}/"
        # ``/videos`` returns a bare video id, so the composite post id is an
        # assumption; the video object itself accepts comments too, and a
        # failed comment never fails the post.
        if not private:
            self._comment_source_link(draft, post_id, retries=3, alt_ids=[video_id])
        return PublishResult(
            destination=self.name,
            post_id=post_id,
            permalink=permalink,
            private=private,
        )

    def _publish_reel(
        self, draft: Draft, page_id: str, caption: str, private: bool
    ) -> PublishResult:
        """Upload the clip and publish it as a Reel (or leave it a DRAFT).

        The three-step Reels flow: open a session, POST the bytes to
        ``rupload.facebook.com``, then finish. A Reel already appears in the
        page feed, so this is one post, not two.
        """
        data, _filename = self._video_bytes(draft)
        try:
            session = self.api.start_reel_upload(page_id)
            video_id = str(session.get("video_id") or "")
            if not video_id:
                raise PublisherError("facebook: reel upload session returned no video id")
            self.api.upload_reel(video_id, data, upload_url=str(session.get("upload_url") or ""))
            resp = self.api.finish_reel(
                page_id,
                video_id,
                description=caption,
                state="DRAFT" if private else "PUBLISHED",
            )
        except ApiError as exc:
            raise PublisherError(f"facebook: reel upload failed: {exc}") from None

        # The finish call returns the feed post id; the canonical form is
        # ``<page id>_<post id>``, which is what a comment targets.
        raw_post_id = str(resp.get("post_id") or "")
        if raw_post_id and "_" not in raw_post_id:
            post_id = f"{page_id}_{raw_post_id}"
        else:
            post_id = raw_post_id or video_id
        permalink = f"https://www.facebook.com/reel/{video_id}/"
        # A draft never becomes public, so a comment on it can never be seen;
        # the public send (if any) posts and comments then.
        if not private:
            self._comment_source_link(draft, post_id, retries=3)
        return PublishResult(
            destination=self.name,
            post_id=post_id,
            permalink=permalink,
            private=private,
        )

    def _comment_source_link(
        self,
        draft: Draft,
        post_id: str,
        *,
        retries: int = 1,
        alt_ids: list[str] | None = None,
    ) -> None:
        """Post the source URL as the new post's first comment.

        Keeps an outbound link out of the caption (the feed deprioritizes posts
        carrying one). Graph needs a moment before a fresh post accepts a
        comment, and a still-processing video can take longer, so a video send
        retries with a widening gap. ``alt_ids`` are tried in order when the
        composite post id is refused (a feed video also accepts a comment on
        the video object itself). A comment failure never fails the post.
        """
        if not (draft.url and post_id):
            return
        for target in [post_id, *(alt_ids or [])]:
            for attempt in range(max(1, retries)):
                time.sleep(COMMENT_DELAY_SECONDS * (attempt + 1))
                try:
                    self.api.add_comment(target, draft.url)
                    return
                except ApiError:
                    continue
