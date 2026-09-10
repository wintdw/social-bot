"""Feed cache writer (stubbed API — no network)."""

from __future__ import annotations

import json

import pytest

from social_bot import refresh as refresh_mod
from social_bot.config import ROOT

RAW = [{"id": "123_1", "message": "hi", "status_type": "mobile_status_update"}]


class FakeApi:
    def __init__(self, items):
        self.items = items
        self.calls = None

    def page_feed(self, page_id, limit):
        self.calls = (page_id, limit)
        return self.items


def _cfg(tmp_path):
    return {
        "graph": {
            "base_url": "https://graph.facebook.com",
            "api_version": "v26.0",
            "timeout_seconds": 30.0,
            "page_id": "123",
            "token": "",
        },
        "feed": {"limit": 5, "dir": str(tmp_path / "feed")},
    }


def test_writes_cache(tmp_path, monkeypatch):
    fake = FakeApi(RAW)
    monkeypatch.setattr(refresh_mod, "api_from_config", lambda cfg: fake)

    result = refresh_mod.refresh_feed(_cfg(tmp_path))

    assert result["count"] == 1
    html_file = tmp_path / "feed" / "latest.html"
    json_file = tmp_path / "feed" / "latest.json"
    assert html_file.exists() and json_file.exists()
    assert json.loads(json_file.read_text(encoding="utf-8"))[0]["id"] == "123_1"
    assert "hi" in html_file.read_text(encoding="utf-8")
    assert fake.calls == ("123", 5)


def test_load_cached_items_none_when_absent(tmp_path):
    assert refresh_mod.load_cached_items(_cfg(tmp_path)) is None


def test_load_cached_items_parses_cache(tmp_path):
    feed_dir = tmp_path / "feed"
    feed_dir.mkdir()
    (feed_dir / "latest.json").write_text(json.dumps(RAW), encoding="utf-8")
    items = refresh_mod.load_cached_items(_cfg(tmp_path))
    assert items is not None
    assert items[0].message == "hi"


def test_missing_page_id_raises(tmp_path):
    cfg = _cfg(tmp_path)
    cfg["graph"]["page_id"] = ""
    with pytest.raises(ValueError):
        refresh_mod.refresh_feed(cfg)


def test_cache_dir_relative_resolves_to_root():
    assert refresh_mod.feed_cache_dir({"feed": {"dir": "data/feed"}}) == ROOT / "data" / "feed"


def test_cache_dir_absolute_is_kept(tmp_path):
    assert refresh_mod.feed_cache_dir({"feed": {"dir": str(tmp_path)}}) == tmp_path


def test_cache_dir_default():
    assert refresh_mod.feed_cache_dir({}) == ROOT / "data" / "feed"
