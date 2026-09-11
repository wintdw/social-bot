"""Config loading tests: defaults, deep merge, token resolution, validation."""

from __future__ import annotations

import pytest
import yaml

from social_bot.config import DEFAULTS, load_config, resolve_token, validate


def test_defaults_when_config_missing(tmp_path):
    cfg = load_config(tmp_path / "does-not-exist.yaml")
    assert cfg["graph"]["api_version"] == "v26.0"
    assert cfg["graph"]["base_url"] == "https://graph.facebook.com"
    assert cfg["feed"]["limit"] == 10


def test_deep_merge_overrides_nested(tmp_path):
    conf = tmp_path / "config.yaml"
    conf.write_text(
        yaml.safe_dump({"graph": {"api_version": "v25.0"}, "feed": {"limit": 3}}),
        encoding="utf-8",
    )
    cfg = load_config(conf)
    assert cfg["graph"]["api_version"] == "v25.0"
    assert cfg["graph"]["base_url"] == DEFAULTS["graph"]["base_url"]  # untouched
    assert cfg["feed"]["limit"] == 3
    assert cfg["feed"].get("fields") is None  # no phantom keys


def test_token_resolution_precedence(tmp_path, monkeypatch):
    cfg = load_config(tmp_path / "missing.yaml")  # defaults: graph.token == ""
    monkeypatch.delenv("SOCIAL_BOT_TOKEN", raising=False)
    # explicit argument wins
    assert resolve_token("flag-token", cfg) == "flag-token"
    # then the environment
    monkeypatch.setenv("SOCIAL_BOT_TOKEN", "env-token")
    assert resolve_token(None, cfg) == "env-token"
    # then config.graph.token
    monkeypatch.delenv("SOCIAL_BOT_TOKEN")
    cfg["graph"]["token"] = "cfg-token"
    assert resolve_token(None, cfg) == "cfg-token"
    # empty when nothing is set
    cfg["graph"]["token"] = ""
    assert resolve_token(None, cfg) == ""


def test_credentials_file_supplies_token(tmp_path):
    conf = tmp_path / "config.yaml"
    conf.write_text(yaml.safe_dump({"graph": {"page_id": "1"}}), encoding="utf-8")
    (tmp_path / "credentials.yaml").write_text(
        yaml.safe_dump({"graph": {"token": "cred-token"}}), encoding="utf-8"
    )
    cfg = load_config(conf)
    assert cfg["graph"]["token"] == "cred-token"
    assert cfg["graph"]["page_id"] == "1"  # config.yaml still applies


def test_credentials_file_overrides_config_token(tmp_path):
    conf = tmp_path / "config.yaml"
    conf.write_text(yaml.safe_dump({"graph": {"token": "cfg-token"}}), encoding="utf-8")
    (tmp_path / "credentials.yaml").write_text(
        yaml.safe_dump({"graph": {"token": "cred-token"}}), encoding="utf-8"
    )
    assert load_config(conf)["graph"]["token"] == "cred-token"


def test_missing_credentials_file_keeps_default(tmp_path):
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg["graph"]["token"] == ""


def test_env_beats_credentials_file(tmp_path, monkeypatch):
    (tmp_path / "credentials.yaml").write_text(
        yaml.safe_dump({"graph": {"token": "cred-token"}}), encoding="utf-8"
    )
    cfg = load_config(tmp_path / "config.yaml")
    monkeypatch.setenv("SOCIAL_BOT_TOKEN", "env-token")
    assert resolve_token(None, cfg) == "env-token"


def test_validate_accepts_defaults():
    validate({**DEFAULTS})  # should not raise


@pytest.mark.parametrize(
    "cfg",
    [
        {**DEFAULTS, "graph": {**DEFAULTS["graph"], "api_version": "26.0"}},
        {**DEFAULTS, "graph": {**DEFAULTS["graph"], "base_url": "http://graph.facebook.com"}},
        {**DEFAULTS, "graph": {**DEFAULTS["graph"], "timeout_seconds": -1}},
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
    assert cfg["blog"]["scan_at"] == ["06:00"]
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
        {"publish": {"destinations": []}},
        {"publish": {"destinations": ["mastodon"]}},
        {"publish": {"max_per_day": 0}},
        {"blog": {"scan_at": ["nope"]}},
        {"blog": {"scan_at": []}},
        {"blog": {"timeout_seconds": 0}},
        {"blog": {"max_scan": 0}},
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
        "no-destinations",
        "unknown-destination",
        "zero-cap",
        "bad-scan-at",
        "empty-scan-at",
        "bad-blog-timeout",
        "zero-max-scan",
        "unknown-image-provider",
        "zero-image-timeout",
        "zero-image-width",
        "http-image-base-url",
    ],
)
def test_validate_rejects_bad_pipeline_config(override):
    with pytest.raises(ValueError):
        validate({**DEFAULTS, **override})
