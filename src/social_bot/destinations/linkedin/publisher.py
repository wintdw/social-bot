"""LinkedIn destination — publishes through linkin-bot's ``POST /post`` gateway.

linkin-bot (a separate sibling service) owns the LinkedIn session (browser
cookies) and is the only thing that talks to LinkedIn. This adapter therefore
holds no token and knows nothing about login: it makes one HTTP call to
linkin-bot, which posts as the connected member. Point ``destinations.linkedin.base_url`` at that
gateway (internal network — linkin-bot is not exposed publicly), e.g.
``http://host.docker.internal:8082``.

A draft with an image uploads the bytes here (``media.load`` — the same store the
Facebook publisher uses) and hands them to the gateway as base64; the gateway
runs LinkedIn's image register-then-PUT flow and attaches the result as media, so
this adapter still holds no token and speaks no LinkedIn API.

A draft with a source URL sends it as the post's **first comment** (the gateway's
``comment`` field, typed into the new post right after it goes out, as the same
Page) — the caption's CTA points at the link ("đọc bài gốc ở comment"), and the
feed deprioritizes a post carrying an outbound link. Same reason the Facebook
publisher comments the link (see ``facebook/publisher.py``).
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request

from ... import media
from ...drafts import Draft
from ..base import Publisher, PublisherError, PublishResult

VISIBILITIES = ("PUBLIC", "CONNECTIONS")


class LinkedInPublisher(Publisher):
    name = "linkedin"
    label = "LinkedIn"
    # LinkedIn has no "unpublished post" equivalent, so private mode is a no-op.
    supports_private = False
    # An image draft sends its bytes to the gateway, which attaches them as media.
    supports_images = True

    @classmethod
    def validate_config(cls, dst: dict) -> None:
        base_url = str(dst.get("base_url", ""))
        if not (base_url.startswith("http://") or base_url.startswith("https://")):
            raise ValueError("config: destinations.linkedin.base_url must be an http(s) URL")
        if float(dst.get("timeout_seconds", 30)) <= 0:
            raise ValueError("config: destinations.linkedin.timeout_seconds must be positive")
        if str(dst.get("visibility", "PUBLIC")).upper() not in VISIBILITIES:
            raise ValueError(
                "config: destinations.linkedin.visibility must be PUBLIC or CONNECTIONS"
            )

    def base_url(self) -> str:
        return str(self.config().get("base_url") or "").rstrip("/")

    def visibility(self) -> str:
        return str(self.config().get("visibility") or "PUBLIC").upper()

    def timeout(self) -> float:
        return float(self.config().get("timeout_seconds", 30))

    def configured(self) -> bool:
        """Configured when pointed at a gateway URL — no token needed here."""
        return bool(self.base_url())

    def describe(self, draft: Draft) -> str:
        return f"POST {self.base_url()}/post"

    def publish(self, draft: Draft) -> PublishResult:
        text = draft.post_text
        if not text.strip() and not draft.image:
            raise PublisherError("linkedin: draft has no caption or image to post")
        payload: dict[str, str] = {"text": text, "visibility": self.visibility()}
        if draft.url:
            # The source link rides as the new post's **first comment**: the
            # gateway types it into the post right after publishing, as the same
            # Page. Keeping it out of the caption is deliberate — the caption's
            # CTA says the link is in the comment, and a post carrying an outbound
            # link is deprioritized by the feed (the reason Facebook comments the
            # link too). A comment that fails does not fail the post: the gateway
            # returns ok with commented=false, so the draft is still recorded sent.
            payload["comment"] = draft.url
        if draft.image:
            # Upload the bytes; the gateway attaches them as the post's media. A
            # local image is read from disk, a remote source cover downloaded here.
            try:
                data, _filename, content_type = media.load(self.cfg, draft.image)
            except media.MediaError as exc:
                raise PublisherError(f"linkedin: {exc}") from None
            payload["image_base64"] = base64.b64encode(data).decode("ascii")
            payload["image_content_type"] = content_type
        request = urllib.request.Request(
            f"{self.base_url()}/post",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout()) as response:
                body = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise PublisherError(f"linkedin: gateway returned HTTP {exc.code}: {detail}") from None
        except TimeoutError:
            # The gateway may have posted before the read timed out; the draft is
            # not marked posted, so check LinkedIn before retrying.
            raise PublisherError(
                f"linkedin: gateway did not respond within {self.timeout()}s; the post may "
                "still have gone out, so check LinkedIn before retrying"
            ) from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise PublisherError(f"linkedin: cannot reach the gateway: {exc}") from None
        if not body.get("ok"):
            raise PublisherError(f"linkedin: gateway rejected the post: {body.get('error')}")
        return PublishResult(
            destination=self.name,
            post_id=str(body.get("post_urn") or ""),
            permalink=str(body.get("permalink") or ""),
            private=False,
        )
