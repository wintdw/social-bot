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

    def to_dict(self) -> dict[str, Any]:
        return {
            "destination": self.destination,
            "post_id": self.post_id,
            "permalink": self.permalink,
            "private": self.private,
        }


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


class AccountReader(_Destination, ABC):
    """Reads an account's own feed and identity for the operator UI."""

    @abstractmethod
    def account(self) -> dict:
        """Account identity as ``{"id": ..., "name": ...}``."""

    @abstractmethod
    def fetch_feed(self, limit: int) -> list:
        """The account's own recent feed items, newest first."""

    def token_status(self) -> dict:
        """Introspect the account token for the dashboard's Token panel."""
        raise DestinationError(f"{self.name}: token status is not supported")
