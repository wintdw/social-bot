"""LinkedIn destination — a structured stub, not implemented yet.

Company-page posting needs LinkedIn's Community Management API approval; a
member token needs ``w_member_social``. When it is enabled, add an access token
and the author URN, then implement ``publish`` against ``POST /rest/posts``. No
core changes are required: the pipeline resolves publishers through the
registry, so the platform-specific logic stays in this module.
"""

from __future__ import annotations

from ...drafts import Draft
from ..base import Publisher, PublisherError, PublishResult


class LinkedInPublisher(Publisher):
    name = "linkedin"
    label = "LinkedIn"
    # LinkedIn has no "unpublished post" equivalent, so private mode is a no-op.
    supports_private = False

    @classmethod
    def validate_config(cls, dst: dict) -> None:
        if not str(dst.get("base_url", "")).startswith("https://"):
            raise ValueError("config: destinations.linkedin.base_url must be an https URL")
        urn = str(dst.get("author_urn") or "").strip()
        if urn and not urn.startswith("urn:li:"):
            raise ValueError(
                "config: destinations.linkedin.author_urn must look like 'urn:li:organization:<id>'"
            )

    def author_urn(self) -> str:
        return str(self.config().get("author_urn") or "").strip()

    def configured(self) -> bool:
        return bool(self.token_value()) and bool(self.author_urn())

    def describe(self, draft: Draft) -> str:
        base = str(self.config().get("base_url") or "https://api.linkedin.com").rstrip("/")
        return f"POST {base}/rest/posts"

    def publish(self, draft: Draft) -> PublishResult:
        raise PublisherError(
            "LinkedIn publishing is not enabled yet — provide an access token with "
            "w_member_social / w_organization_social and implement the adapter"
        )
