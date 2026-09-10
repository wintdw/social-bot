"""Destination publishers (Facebook Page now; LinkedIn stubbed).

A publisher turns an approved draft into a real post. Facebook reuses the
existing Graph client; LinkedIn is wired as an adapter so enabling it later
needs no changes in the pipeline — but it is not implemented yet (company-page
posting needs LinkedIn Community Management API approval).
"""

from __future__ import annotations

from .api import ApiError, api_from_config
from .drafts import Draft


class PublisherError(Exception):
    """A destination could not accept the post."""


class FacebookPublisher:
    name = "facebook"

    def __init__(self, cfg: dict, token: str | None = None) -> None:
        self.cfg = cfg
        self.token = token
        self._api = None

    @property
    def api(self):
        if self._api is None:
            self._api = api_from_config(self.cfg, self.token)
        return self._api

    def page_id(self) -> str:
        page_id = str(self.cfg.get("graph", {}).get("page_id") or "").strip()
        if not page_id:
            raise ValueError("no page id: set graph.page_id in config.yaml")
        return page_id

    def private(self) -> bool:
        """True when publish.private is on: post unpublished (admins only)."""
        return bool(self.cfg.get("publish", {}).get("private", False))

    def describe(self, draft: Draft) -> str:
        """The endpoint a real send would hit (dry-run text)."""
        page_id = self.page_id()
        endpoint = f"POST /{page_id}/photos" if draft.image else f"POST /{page_id}/feed"
        return f"{endpoint} (unpublished)" if self.private() else endpoint

    def publish(self, draft: Draft) -> dict:
        page_id = self.page_id()
        caption = draft.post_text
        private = self.private()
        if draft.image:
            resp = self.api.create_photo_post(
                page_id, caption, draft.image, published=not private
            )
        else:
            resp = self.api.create_post(
                page_id, caption, draft.url or None, published=not private
            )
        post_id = str(resp.get("post_id") or resp.get("id") or "")
        permalink = f"https://www.facebook.com/{post_id}" if "_" in post_id else ""
        return {
            "destination": self.name,
            "post_id": post_id,
            "permalink": permalink,
            "private": private,
        }


class LinkedInPublisher:
    name = "linkedin"

    def __init__(self, cfg: dict, token: str | None = None) -> None:
        self.cfg = cfg
        self.token = token

    def describe(self, draft: Draft) -> str:
        return "POST https://api.linkedin.com/rest/posts"

    def publish(self, draft: Draft) -> dict:
        raise PublisherError(
            "LinkedIn publishing is not enabled yet — provide an access token with "
            "w_member_social / w_organization_social and implement the adapter"
        )


PUBLISHERS = {
    FacebookPublisher.name: FacebookPublisher,
    LinkedInPublisher.name: LinkedInPublisher,
}


def publisher_for(name: str, cfg: dict, token: str | None = None):
    cls = PUBLISHERS.get(name)
    if cls is None:
        raise PublisherError(f"unknown destination {name!r}")
    return cls(cfg, token)


__all__ = [
    "ApiError",
    "PublisherError",
    "FacebookPublisher",
    "LinkedInPublisher",
    "PUBLISHERS",
    "publisher_for",
]
