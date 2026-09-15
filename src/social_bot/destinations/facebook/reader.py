"""Facebook account reader: identity, feed fetch/cache, token status.

Fetches the Page's own feed through the Graph client and writes two files under
the configured `feed.dir`: `latest.json` (the raw Graph items) and `latest.html`
(the rendered dashboard page). Read-only — nothing is ever posted here.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from ...config import ROOT, load_config
from ..base import AccountReader
from .api import api_from_config, check_token
from .feed import FeedItem, parse_feed_response
from .feed_html import render_feed_html

JSON_NAME = "latest.json"
HTML_NAME = "latest.html"


def account_id(cfg: dict) -> str:
    """The facebook Page id from `destinations.facebook.account_id`."""
    raw = str(cfg.get("destinations", {}).get("facebook", {}).get("account_id") or "").strip()
    if not raw:
        raise ValueError(
            "no page id: set destinations.facebook.account_id in config.yaml, "
            "pass --page-id, or run `whoami` to list the pages the token can manage"
        )
    return raw


def feed_cache_dir(cfg: dict) -> pathlib.Path:
    """The cache directory from `feed.dir`, resolved against the project root."""
    raw = str(cfg.get("feed", {}).get("dir") or "data/feed")
    path = pathlib.Path(raw)
    return path if path.is_absolute() else ROOT / path


def load_cached_items(cfg: dict) -> list[FeedItem] | None:
    """Parsed feed items from the cache, or None if the feed isn't cached yet."""
    path = feed_cache_dir(cfg) / JSON_NAME
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return parse_feed_response({"data": data})


def refresh_feed(cfg: dict | None = None, config_path=None) -> dict:
    """Fetch the page feed and write latest.json + latest.html.

    Raises ValueError (bad config/page id) or ApiError (Graph/network failure);
    the caller decides how to report it.
    """
    cfg = cfg or load_config(config_path)
    page_id = account_id(cfg)

    api = api_from_config(cfg)
    raw_items = api.page_feed(page_id, int(cfg["feed"]["limit"]))

    out_dir = feed_cache_dir(cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_file = out_dir / JSON_NAME
    html_file = out_dir / HTML_NAME
    json_file.write_text(json.dumps(raw_items, indent=2, ensure_ascii=False), encoding="utf-8")
    html_file.write_text(
        render_feed_html(parse_feed_response({"data": raw_items}), page_id=page_id),
        encoding="utf-8",
    )
    return {"count": len(raw_items), "html_file": str(html_file), "json_file": str(json_file)}


class FacebookReader(AccountReader):
    """Reads the configured Page: its identity, its feed, and the token's status."""

    name = "facebook"
    label = "Facebook"

    @property
    def api(self):
        return api_from_config(self.cfg, self.token)

    def configured(self) -> bool:
        return bool(self.token_value()) and bool(str(self.config().get("account_id") or "").strip())

    def account(self) -> dict[str, Any]:
        return self.api.page_info(account_id(self.cfg))

    def fetch_feed(self, limit: int) -> list[dict]:
        return self.api.page_feed(account_id(self.cfg), limit)

    def token_status(self) -> dict:
        return check_token(self.cfg, self.token)
