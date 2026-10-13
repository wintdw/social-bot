"""The destination registry and contracts (no network)."""

from __future__ import annotations

import copy

import pytest

from social_bot.config import DEFAULTS
from social_bot.destinations import (
    PUBLISHERS,
    READERS,
    default_reader,
    enabled_names,
    label_for,
    labels_for,
    names,
    reader_for,
    validate_destinations,
)
from social_bot.destinations.base import PublishResult
from social_bot.destinations.linkedin import LinkedInPublisher


def _cfg():
    return copy.deepcopy(DEFAULTS)


def test_names_labels_and_registry():
    assert names() == ["facebook", "linkedin"]
    assert set(PUBLISHERS) == {"facebook", "linkedin"}
    assert label_for("facebook") == "Facebook"
    assert label_for("linkedin") == "LinkedIn"
    assert label_for("mastodon") == "mastodon"  # unknown falls back to the name
    assert labels_for(["facebook", "linkedin"]) == ["Facebook", "LinkedIn"]


def test_enabled_names_follows_publish_routing():
    cfg = _cfg()
    assert enabled_names(cfg) == ["facebook", "linkedin"]
    cfg["publish"]["destinations"] = ["facebook"]
    assert enabled_names(cfg) == ["facebook"]


def test_only_facebook_has_a_reader():
    cfg = _cfg()
    assert set(READERS) == {"facebook"}
    assert reader_for("facebook", cfg).label == "Facebook"
    assert reader_for("linkedin", cfg) is None
    assert reader_for("mastodon", cfg) is None


def test_default_reader_is_first_enabled_with_a_reader():
    cfg = _cfg()
    assert default_reader(cfg).name == "facebook"
    cfg["publish"]["destinations"] = ["linkedin"]
    assert default_reader(cfg) is None


def test_validate_destinations_rejects_unknown_and_bad_blocks():
    cfg = _cfg()
    cfg["destinations"]["mastodon"] = {}
    with pytest.raises(ValueError):
        validate_destinations(cfg)

    cfg = _cfg()
    cfg["destinations"]["facebook"]["base_url"] = "http://x"
    with pytest.raises(ValueError):
        validate_destinations(cfg)


def test_validate_destinations_accepts_defaults():
    validate_destinations(_cfg())


def test_publish_result_to_dict():
    result = PublishResult("facebook", post_id="1_2", permalink="u", private=True)
    assert result.to_dict() == {
        "destination": "facebook",
        "post_id": "1_2",
        "permalink": "u",
        "private": True,
    }


def test_linkedin_validate_config_checks_gateway_url_and_visibility():
    with pytest.raises(ValueError):
        LinkedInPublisher.validate_config({"base_url": "api.linkedin.com"})
    with pytest.raises(ValueError):
        LinkedInPublisher.validate_config({"base_url": "http://x", "visibility": "FRIENDS"})
    with pytest.raises(ValueError):
        LinkedInPublisher.validate_config({"base_url": "http://x", "timeout_seconds": 0})
    LinkedInPublisher.validate_config(
        {"base_url": "http://host.docker.internal:8082", "visibility": "CONNECTIONS"}
    )
