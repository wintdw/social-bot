"""Destination adapters: one package per platform, one shared seam.

The platform-agnostic core (pipeline, CLI, web, UI) imports only from here:

* ``publisher_for`` / ``reader_for`` — resolve a platform adapter by name.
* ``names`` / ``enabled_names`` — the registry and the configured routing.
* ``Publisher`` / ``AccountReader`` / ``PublishResult`` — the contracts.
* ``DestinationError`` / ``PublisherError`` — the failure type to catch.
"""

from .base import (
    AccountReader,
    DestinationError,
    Publisher,
    PublisherError,
    PublishResult,
)
from .registry import (
    PUBLISHERS,
    READERS,
    default_reader,
    describe_all,
    enabled_names,
    label_for,
    labels_for,
    linkedin_status,
    names,
    publisher_for,
    reader_for,
    validate_destinations,
)

__all__ = [
    "AccountReader",
    "DestinationError",
    "PublishResult",
    "Publisher",
    "PublisherError",
    "PUBLISHERS",
    "READERS",
    "default_reader",
    "describe_all",
    "enabled_names",
    "label_for",
    "labels_for",
    "linkedin_status",
    "names",
    "publisher_for",
    "reader_for",
    "validate_destinations",
]
