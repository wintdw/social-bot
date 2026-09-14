"""Config loading tests: defaults, deep merge, token resolution, validation."""

from __future__ import annotations

import pytest
import yaml

from social_bot.config import DEFAULTS, load_config, resolve_token, validate


def test_defaults_when_config_missing(tmp_path):
    cfg = load_config(tmp_path / "does-not-exist.yaml")
    assert cfg["destinations"]["facebook"]["api_version"] == "v26.0"
    assert cfg["destinations"]["facebook"]["base_url"] == "https://graph.facebook.com"
    assert cfg["destinations"]["linkedin"]["base_url"] == "https://api.linkedin.com"
    assert cfg["feed"]["limit"] == 10


def test_deep_merge_overrides_nested(tmp_path):
    conf = tmp_path / "config.yaml"
    conf.write_text(
        yaml.safe_dump(
            {"destinations": {"facebook": {"api_version": "v25.0"}}, "feed": {"limit": 3}}
        ),
        encoding="utf-8",
    )
    cfg = load_config(conf)
    assert cfg["destinations"]["facebook"]["api_version"] == "v25.0"
    # The sibling key survives the nested merge.
    assert (
        cfg["destinations"]["facebook"]["base_url"]
        == DEFAULTS["destinations"]["facebook"]["base_url"]
    )
    assert cfg["destinations"]["linkedin"]["base_url"]  # other block untouched
    assert cfg["feed"]["limit"] == 3
    assert cfg["feed"].get("fields") is None  # no phantom keys


def test_token_resolution_precedence(tmp_path, monkeypatch):
    cfg = load_config(tmp_path / "missing.yaml")  # defaults: no tokens
    monkeypatch.delenv("SOCIAL_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SOCIAL_BOT_FACEBOOK_TOKEN", raising=False)
    # explicit argument wins
    assert resolve_token("facebook", cfg, "flag-token") == "flag-token"
    # then the destination-specific environment variable
    monkeypatch.setenv("SOCIAL_BOT_FACEBOOK_TOKEN", "fb-env-token")
    assert resolve_token("facebook", cfg) == "fb-env-token"
    # then the global environment fallback
    monkeypatch.delenv("SOCIAL_BOT_FACEBOOK_TOKEN")
    monkeypatch.setenv("SOCIAL_BOT_TOKEN", "env-token")
    assert resolve_token("facebook", cfg) == "env-token"
    # then destinations.<name>.token
    monkeypatch.delenv("SOCIAL_BOT_TOKEN")
    cfg["destinations"]["facebook"]["token"] = "cfg-token"
    assert resolve_token("facebook", cfg) == "cfg-token"
    # empty when nothing is set
    cfg["destinations"]["facebook"]["token"] = ""
    assert resolve_token("facebook", cfg) == ""


def test_destination_tokens_are_independent(tmp_path, monkeypatch):
    cfg = load_config(tmp_path / "missing.yaml")
    monkeypatch.delenv("SOCIAL_BOT_TOKEN", raising=False)
    cfg["destinations"]["facebook"]["token"] = "fb-token"
    cfg["destinations"]["linkedin"]["token"] = "li-token"
    assert resolve_token("facebook", cfg) == "fb-token"
    assert resolve_token("linkedin", cfg) == "li-token"
    # A destination-specific env var overrides only its own destination.
    monkeypatch.setenv("SOCIAL_BOT_LINKEDIN_TOKEN", "li-env")
    assert resolve_token("facebook", cfg) == "fb-token"
    assert resolve_token("linkedin", cfg) == "li-env"


def test_credentials_file_supplies_token(tmp_path):
    conf = tmp_path / "config.yaml"
    conf.write_text(
        yaml.safe_dump({"destinations": {"facebook": {"account_id": "1"}}}),
        encoding="utf-8",
    )
    (tmp_path / "credentials.yaml").write_text(
        yaml.safe_dump({"destinations": {"facebook": {"token": "cred-token"}}}),
        encoding="utf-8",
    )
    cfg = load_config(conf)
    assert cfg["destinations"]["facebook"]["token"] == "cred-token"
    assert cfg["destinations"]["facebook"]["account_id"] == "1"  # config applies


def test_credentials_file_overrides_config_token(tmp_path):
    conf = tmp_path / "config.yaml"
    conf.write_text(
        yaml.safe_dump({"destinations": {"facebook": {"token": "cfg-token"}}}),
        encoding="utf-8",
    )
    (tmp_path / "credentials.yaml").write_text(
        yaml.safe_dump({"destinations": {"facebook": {"token": "cred-token"}}}),
        encoding="utf-8",
    )
    assert load_config(conf)["destinations"]["facebook"]["token"] == "cred-token"


def test_missing_credentials_file_keeps_default(tmp_path):
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg["destinations"]["facebook"]["token"] == ""


def test_env_beats_credentials_file(tmp_path, monkeypatch):
    (tmp_path / "credentials.yaml").write_text(
        yaml.safe_dump({"destinations": {"facebook": {"token": "cred-token"}}}),
        encoding="utf-8",
    )
    cfg = load_config(tmp_path / "config.yaml")
    monkeypatch.setenv("SOCIAL_BOT_TOKEN", "env-token")
    assert resolve_token("facebook", cfg) == "env-token"


def test_validate_accepts_defaults():
    validate({**DEFAULTS})  # should not raise


def test_validate_accepts_a_configured_post_schedule():
    cfg = {
        **DEFAULTS,
        "publish": {
            **DEFAULTS["publish"],
            "post_at": ["09:00", "20:30", "19:30-21:00"],
            "post_per_slot": 2,
            "interval_days": 2,
        },
    }
    validate(cfg)  # should not raise


@pytest.mark.parametrize(
    "cfg",
    [
        {
            **DEFAULTS,
            "destinations": {
                **DEFAULTS["destinations"],
                "facebook": {**DEFAULTS["destinations"]["facebook"], "api_version": "26.0"},
            },
        },
        {
            **DEFAULTS,
            "destinations": {
                **DEFAULTS["destinations"],
                "facebook": {
                    **DEFAULTS["destinations"]["facebook"],
                    "base_url": "http://graph.facebook.com",
                },
            },
        },
        {
            **DEFAULTS,
            "destinations": {
                **DEFAULTS["destinations"],
                "facebook": {
                    **DEFAULTS["destinations"]["facebook"],
                    "timeout_seconds": -1,
                },
            },
        },
        {**DEFAULTS, "feed": {**DEFAULTS["feed"], "limit": 0}},
    ],
    ids=["bad-version", "http-base-url", "bad-timeout", "zero-limit"],
)
def test_validate_rejects_bad_config(cfg):
    with pytest.raises(ValueError):
        validate(cfg)


def test_defaults_include_pipeline_sections(tmp_path):
    cfg = load_config(tmp_path / "missing.yaml")
    assert cfg["sources"][0]["name"] == "atento-blog"
    assert cfg["sources"][0]["type"] == "index"
    assert cfg["publish"]["destinations"] == ["facebook"]
    assert cfg["publish"]["post_at"] == []  # timed posting is off by default
    assert cfg["publish"]["post_per_slot"] == 1
    assert cfg["publish"]["interval_days"] == 0  # no minimum gap by default
    assert cfg["blog"]["scan_at"] == ["06:00"]
    assert cfg["blog"]["max_age_days"] == 0  # no age window by default
    assert cfg["review"]["dir"] == "data/review"
    assert cfg["publish"]["log_name"] == "published.jsonl"


def test_image_gen_disabled_by_default(tmp_path):
    cfg = load_config(tmp_path / "missing.yaml")
    assert cfg["image_gen"]["enabled"] is False
    assert cfg["image_gen"]["overwrite"] is False
    assert cfg["image_gen"]["base_url"] == "https://gen.pollinations.ai/image"
    assert cfg["image_gen"]["model"] == "openai/gpt-image-1-mini"
    assert cfg["image_gen"]["width"] == 1080 and cfg["image_gen"]["height"] == 1350


def test_credentials_file_supplies_image_key(tmp_path):
    conf = tmp_path / "config.yaml"
    conf.write_text(yaml.safe_dump({"image_gen": {"enabled": True}}), encoding="utf-8")
    (tmp_path / "credentials.yaml").write_text(
        yaml.safe_dump({"image_gen": {"api_key": "sk_secret"}}), encoding="utf-8"
    )
    cfg = load_config(conf)
    assert cfg["image_gen"]["api_key"] == "sk_secret"
    assert cfg["image_gen"]["enabled"] is True


@pytest.mark.parametrize(
    "override",
    [
        {"sources": []},
        {"sources": [{"name": "x", "type": "sitemap", "url": "https://x"}]},
        {"sources": [{"name": "x", "type": "ftp", "url": "https://x", "path_prefix": "/b/"}]},
        {"sources": [{"name": "x", "type": "rss", "url": "http://x"}]},
        {"destinations": {**DEFAULTS["destinations"], "mastodon": {}}},
        {"publish": {"destinations": []}},
        {"publish": {"destinations": ["mastodon"]}},
        {"publish": {"destinations": ["facebook"], "post_at": ["nope"]}},
        {"publish": {"destinations": ["facebook"], "post_at": ["24:00"]}},
        {"publish": {"destinations": ["facebook"], "post_at": ["19:30-21:00-22:00"]}},
        {"publish": {"destinations": ["facebook"], "post_at": ["21:00-19:30"]}},
        {"publish": {"destinations": ["facebook"], "post_at": "09:00"}},
        {"publish": {"destinations": ["facebook"], "post_per_slot": 0}},
        {"publish": {"destinations": ["facebook"], "interval_days": -1}},
        {"blog": {"scan_at": ["nope"]}},
        {"blog": {"scan_at": []}},
        {"blog": {"timeout_seconds": 0}},
        {"blog": {"max_scan": 0}},
        {"blog": {**DEFAULTS["blog"], "max_age_days": -1}},
        {"image_gen": {"provider": "midjourney"}},
        {"image_gen": {"timeout_seconds": 0}},
        {"image_gen": {"width": 0}},
        {"image_gen": {"base_url": "http://gen.pollinations.ai/image"}},
    ],
    ids=[
        "empty-sources",
        "sitemap-needs-prefix",
        "bad-source-type",
        "http-source-url",
        "unknown-destination-block",
        "no-destinations",
        "unknown-destination",
        "bad-post-at",
        "out-of-range-post-at",
        "post-at-window-triple",
        "post-at-window-reversed",
        "post-at-not-a-list",
        "zero-post-per-slot",
        "negative-interval-days",
        "bad-scan-at",
        "empty-scan-at",
        "bad-blog-timeout",
        "zero-max-scan",
        "negative-max-age-days",
        "unknown-image-provider",
        "zero-image-timeout",
        "zero-image-width",
        "http-image-base-url",
    ],
)
def test_validate_rejects_bad_pipeline_config(override):
    with pytest.raises(ValueError):
        validate({**DEFAULTS, **override})
