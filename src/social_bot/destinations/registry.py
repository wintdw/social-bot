"""The destination registry — the one seam the platform-agnostic core touches.

Adding a platform means adding a package under ``destinations/`` and registering
its publisher/reader class here; nothing in the pipeline, CLI, or UI changes.
"""

from __future__ import annotations

from .base import (
    AccountReader,
    Publisher,
    PublisherError,
)
from .facebook import FacebookPublisher, FacebookReader
from .linkedin import LinkedInPublisher

PUBLISHERS: dict[str, type[Publisher]] = {
    cls.name: cls for cls in (FacebookPublisher, LinkedInPublisher)
}
READERS: dict[str, type[AccountReader]] = {cls.name: cls for cls in (FacebookReader,)}


def names() -> list[str]:
    """Every known destination name (registry order, facebook first)."""
    return list(PUBLISHERS)


def label_for(name: str) -> str:
    """The human-facing label for a destination name (falls back to the name)."""
    cls = PUBLISHERS.get(name)
    return (cls.label or name) if cls else name


def labels_for(names: list[str]) -> list[str]:
    """Labels for several destination names, in order."""
    return [label_for(name) for name in names]


def enabled_names(cfg: dict) -> list[str]:
    """Destinations a new draft is routed to (`publish.destinations`)."""
    return list(cfg.get("publish", {}).get("destinations", []) or [])


def video_names() -> list[str]:
    """Destinations that can publish a video post (Reel or feed video), registry order.

    A video draft may only target one of these; the core refuses the rest
    instead of silently dropping the clip.
    """
    return [name for name, cls in PUBLISHERS.items() if cls.supports_video]


def publisher_for(name: str, cfg: dict, token: str | None = None) -> Publisher:
    cls = PUBLISHERS.get(name)
    if cls is None:
        raise PublisherError(f"unknown destination {name!r}")
    return cls(cfg, token)


def reader_for(name: str, cfg: dict, token: str | None = None) -> AccountReader | None:
    """The account reader for a destination, or None if it has none."""
    cls = READERS.get(name)
    return cls(cfg, token) if cls else None


def default_reader(cfg: dict, token: str | None = None) -> AccountReader | None:
    """The reader for the first enabled destination that has one, else None."""
    for name in enabled_names(cfg):
        reader = reader_for(name, cfg, token)
        if reader is not None:
            return reader
    return None


def first_reader(cfg: dict, token: str | None = None) -> AccountReader | None:
    """The first registered reader, ignoring publish routing.

    `whoami`/`feed`/`refresh` are account utilities, not routing decisions:
    they work even when no feed-capable destination is enabled for new drafts.
    """
    for cls in READERS.values():
        return cls(cfg, token)
    return None


def direct_publisher(cfg: dict, token: str | None = None) -> Publisher | None:
    """The first publisher that can post raw content (the CLI `post` utility).

    Registry order wins (facebook first). Like `first_reader`, this is a
    platform utility, not the draft routing in `publish.destinations`.
    """
    for cls in PUBLISHERS.values():
        if cls.supports_direct:
            return cls(cfg, token)
    return None


def describe_all(cfg: dict) -> list[dict]:
    """Per-destination status for the operator UI: name, label, routed, configured."""
    enabled = set(enabled_names(cfg))
    state: list[dict] = []
    for name, cls in PUBLISHERS.items():
        publisher = cls(cfg)
        state.append(
            {
                "name": name,
                "label": publisher.label or name,
                "enabled": name in enabled,
                "configured": publisher.configured(),
            }
        )
    return state


def validate_destinations(cfg: dict) -> None:
    """Validate every configured destination block; raise ValueError if unusable.

    The per-destination schema lives with the destination (``validate_config``),
    so this only enforces the shape and the known names.
    """
    blocks = cfg.get("destinations", {})
    if not isinstance(blocks, dict):
        raise ValueError("config: destinations must be a mapping")
    for name, block in blocks.items():
        cls = PUBLISHERS.get(name)
        if cls is None:
            raise ValueError(f"config: unknown destination {name!r}")
        if not isinstance(block, dict):
            raise ValueError(f"config: destinations.{name} must be a mapping")
        cls.validate_config(block)


def linkedin_status(cfg: dict, timeout: float | None = None) -> dict:
    """The linkin-bot gateway status for the operator UI (never raises).

    The one seam for the LinkedIn side-channel: the core calls this, never the
    ``linkedin`` package directly, so no platform import leaks outside
    ``destinations/``. Unconfigured or unreachable gateway is an ``ok: False``
    view, never an exception.

    ``timeout`` overrides ``destinations.linkedin.timeout_seconds``. The
    health/metrics paths pass a short one: those are scraped often, so they must
    never wait the full post timeout for a hung gateway.
    """
    from .linkedin.status import get_status

    return get_status(cfg, timeout=timeout)
