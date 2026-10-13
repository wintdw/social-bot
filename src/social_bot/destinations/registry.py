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


def publisher_for(name: str, cfg: dict, token: str | None = None) -> Publisher:
    cls = PUBLISHERS.get(name)
    if cls is None:
        raise PublisherError(f"unknown destination {name!r}")
    return cls(cfg, token)


def reader_for(name: str, cfg: dict, token: str | None = None) -> AccountReader | None:
    """The account reader for a destination, or None if it has none."""
    cls = READERS.get(name)
    return cls(cfg, token) if cls else None


def default_reader(cfg: dict) -> AccountReader | None:
    """The reader for the first enabled destination that has one, else None."""
    for name in enabled_names(cfg):
        reader = reader_for(name, cfg)
        if reader is not None:
            return reader
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


def linkedin_status(cfg: dict) -> dict:
    """The linkin-bot gateway status for the operator UI (never raises).

    The one seam for the LinkedIn side-channel: the core calls this, never the
    ``linkedin`` package directly, so no platform import leaks outside
    ``destinations/``. Unconfigured or unreachable gateway is an ``ok: False``
    view, never an exception.
    """
    from .linkedin.status import get_status

    return get_status(cfg)
