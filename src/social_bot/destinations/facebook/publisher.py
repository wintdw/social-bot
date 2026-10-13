"""Facebook Page publisher.

Facebook reuses the Graph client in ``api.py``; this module is the *publishing*
seam that turns an approved draft into a real post. A draft with an image is a
photo post, and the image is **uploaded** (see ``media``) rather than handed to
Graph as a URL to fetch — the generator no longer serves its URLs anonymously,
so a URL post 401s from Facebook's side.
"""

from __future__ import annotations

import time

from ... import media
from ...drafts import Draft
from ..base import Publisher, PublisherError, PublishResult
from .api import ApiError, api_from_config

# Seconds to wait before commenting on a freshly created post. Facebook's
# Graph API can have a brief propagation delay before the post is available
# for commenting.
COMMENT_DELAY_SECONDS = 3


class FacebookPublisher(Publisher):
    name = "facebook"
    label = "Facebook"

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
        endpoint = f"POST /{page_id}/photos" if draft.image else f"POST /{page_id}/feed"
        return f"{endpoint} (unpublished)" if self.private() else endpoint

    def publish(self, draft: Draft) -> PublishResult:
        page_id = self.page_id()
        caption = draft.post_text
        private = self.private()
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

        # Post the link as the first comment to avoid Facebook's algorithm
        # deprioritizing posts with external URLs in the caption. Wait a few
        # seconds first — the post may not be immediately available for
        # commenting due to Graph API propagation delay.
        if draft.url and post_id and "_" in post_id:
            time.sleep(COMMENT_DELAY_SECONDS)
            try:
                self.api.add_comment(post_id, draft.url)
            except ApiError:
                pass  # Comment failure shouldn't fail the publish

        return PublishResult(
            destination=self.name,
            post_id=post_id,
            permalink=permalink,
            private=private,
        )
