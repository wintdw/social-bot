"""Destination contracts: the seam every platform plugs into.

A *destination* is a platform the factory publishes to (``facebook``,
``linkedin``, ...). Two capabilities are modelled separately:

* ``Publisher``     — turn an approved draft into a real post.
* ``AccountReader`` — read the account's own feed / identity / token status for
                      the operator UI. Facebook implements it; LinkedIn does not.

Platform code lives in a sibling package per destination (``facebook/``,
``linkedin/``); the platform-agnostic core only ever imports ``registry.py``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a runtime import cycle
    from ..drafts import Draft


class DestinationError(Exception):
    """A destination could not accept the post."""


class PublisherError(DestinationError):
    """Kept as a named alias of DestinationError for existing callers/tests."""


@dataclass
class PublishResult:
    """What a publisher returns after a real send."""

    destination: str
    post_id: str = ""
    permalink: str = ""
    private: bool = False
    # The first-comment outcome, for a destination that posts the source link as
    # the new post's first comment. ``None`` = no comment was involved (no source
    # URL, or a platform that comments inside the API call). A failed comment never
    # fails the send: the post is out, so it is reported here instead.
    commented: bool | None = None
    comment_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = {
            "destination": self.destination,
            "post_id": self.post_id,
            "permalink": self.permalink,
            "private": self.private,
        }
        if self.commented is not None:
            data["commented"] = self.commented
            if self.comment_error:
                data["comment_error"] = self.comment_error
        return data


class _Destination:
    """Shared config/token plumbing for publishers and readers."""

    name: ClassVar[str] = ""
    label: ClassVar[str] = ""

    def __init__(self, cfg: dict, token: str | None = None) -> None:
        self.cfg = cfg
        self.token = token

    def config(self) -> dict:
        """This destination's own block from ``config["destinations"][name]``."""
        return dict(self.cfg.get("destinations", {}).get(self.name, {}))

    def token_value(self) -> str:
        """The resolved token (explicit > per-destination env > global env > config)."""
        from ..config import resolve_token

        return resolve_token(self.name, self.cfg, self.token)

    def configured(self) -> bool:
        """True when the destination has the credentials it needs to send."""
        return bool(self.token_value())


class Publisher(_Destination, ABC):
    """Turns an approved draft into a post on one platform."""

    # A destination may not support every post feature; the core checks these.
    supports_images: ClassVar[bool] = True
    supports_private: ClassVar[bool] = True
    # Video is opt-in per destination: a platform must say it can take one
    # before the core will route a video draft there.
    supports_video: ClassVar[bool] = False
    # Direct posting is the CLI `post` utility (raw status/link/photo), not the
    # draft pipeline. A platform that can do it sets this and implements the
    # two methods below.
    supports_direct: ClassVar[bool] = False

    @classmethod
    def validate_config(cls, dst: dict) -> None:
        """Validate this destination's config block; raise ValueError if unusable.

        Platform-owned: each destination knows its own required keys.
        """

    @abstractmethod
    def describe(self, draft: Draft) -> str:
        """The endpoint a real send would hit (dry-run text)."""

    @abstractmethod
    def publish(self, draft: Draft) -> PublishResult:
        """Send the draft; return where it landed."""

    def describe_direct(
        self,
        caption: str,
        *,
        link: str = "",
        photo: str = "",
        published: bool = True,
        account_id: str = "",
    ) -> dict:
        """Endpoint and form fields for the CLI `post` dry run.

        Only a destination with ``supports_direct`` implements this; the core
        never assumes a platform's post shape.
        """
        raise DestinationError(f"{self.name}: direct posting is not supported")

    def direct_post(
        self,
        caption: str,
        *,
        link: str = "",
        photo: str = "",
        published: bool = True,
        account_id: str = "",
    ) -> dict:
        """Post raw content outside the draft pipeline (the CLI `post` utility)."""
        raise DestinationError(f"{self.name}: direct posting is not supported")


class AccountReader(_Destination, ABC):
    """Reads an account's own feed and identity for the operator UI."""

    @abstractmethod
    def account(self) -> dict:
        """Account identity as ``{"id": ..., "name": ...}``."""

    @abstractmethod
    def fetch_feed(self, limit: int, account_id: str = "") -> list:
        """The account's own recent feed items, newest first.

        ``account_id`` overrides the configured one (`--page-id` on the CLI);
        empty means "the configured account".
        """

    def token_status(self) -> dict:
        """Introspect the account token for the dashboard's Token panel."""
        raise DestinationError(f"{self.name}: token status is not supported")

    # -- optional capabilities -------------------------------------------
    # Only a feed-capable platform implements these. The core calls them
    # through this contract, so it never imports a destination package.

    def identity(self) -> dict:
        """The token owner (`whoami`)."""
        raise DestinationError(f"{self.name}: token identity is not supported")

    def accounts(self) -> list[dict]:
        """Accounts/pages this credential can manage (`whoami`)."""
        raise DestinationError(f"{self.name}: account listing is not supported")

    def feed_markdown(self, limit: int, account_id: str = "") -> str:
        """The account feed rendered as markdown (`feed` CLI)."""
        raise DestinationError(f"{self.name}: feed rendering is not supported")

    def refresh(self) -> dict:
        """Fetch the account feed and write the cached copy."""
        raise DestinationError(f"{self.name}: feed caching is not supported")

    def cached_feed(self) -> list | None:
        """The cached feed items, or None when nothing is cached."""
        raise DestinationError(f"{self.name}: feed caching is not supported")

    def feed_section(self, items: list) -> str:
        """The feed items rendered as an HTML fragment for the dashboard."""
        raise DestinationError(f"{self.name}: feed rendering is not supported")
