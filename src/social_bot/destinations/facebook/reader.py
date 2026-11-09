"""Facebook account reader: identity, feed fetch/cache, token status.

Fetches the Page's own feed through the Graph client and writes two files under
the configured `feed.dir`: `latest.json` (the raw Graph items) and `latest.html`
(the rendered dashboard page). Read-only — nothing is ever posted here.

The account utilities (`whoami`, `feed`, `refresh`) and the dashboard call these
through ``AccountReader``, so the core never imports this package.
"""

from __future__ import annotations

import json
from typing import Any

from ...config import FEED_HTML_NAME, FEED_JSON_NAME, feed_cache_dir, load_config
from ..base import AccountReader, DestinationError
from .api import ApiError, api_from_config, check_token
from .feed import FeedItem, format_feed_md, parse_feed_response
from .feed_html import render_feed_html, render_feed_section

# Kept as aliases: the names live in config so the web layer can find the cache
# without importing this package.
JSON_NAME = FEED_JSON_NAME
HTML_NAME = FEED_HTML_NAME


def account_id(cfg: dict) -> str:
    """The facebook Page id from `destinations.facebook.account_id`."""
    raw = str(cfg.get("destinations", {}).get("facebook", {}).get("account_id") or "").strip()
    if not raw:
        raise ValueError(
            "no page id: set destinations.facebook.account_id in config.yaml, "
            "pass --page-id, or run `whoami` to list the pages the token can manage"
        )
    return raw


def load_cached_items(cfg: dict) -> list[FeedItem] | None:
    """Parsed feed items from the cache, or None if the feed isn't cached yet."""
    path = feed_cache_dir(cfg) / FEED_JSON_NAME
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return parse_feed_response({"data": data})


def refresh_feed(cfg: dict | None = None, config_path=None, token: str | None = None) -> dict:
    """Fetch the page feed and write latest.json + latest.html.

    Raises ValueError (bad config/page id), ApiError (Graph/network failure), or
    OSError (cache write); the caller decides how to report it.
    """
    cfg = cfg or load_config(config_path)
    page_id = account_id(cfg)

    api = api_from_config(cfg, token)
    raw_items = api.page_feed(page_id, int(cfg["feed"]["limit"]))

    out_dir = feed_cache_dir(cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_file = out_dir / FEED_JSON_NAME
    html_file = out_dir / FEED_HTML_NAME
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
        try:
            return self.api.page_info(account_id(self.cfg))
        except ApiError as exc:
            raise DestinationError(f"facebook: {exc}") from None

    def identity(self) -> dict:
        try:
            return self.api.me()
        except ApiError as exc:
            raise DestinationError(f"facebook: {exc}") from None

    def accounts(self) -> list[dict]:
        try:
            return self.api.managed_pages()
        except ApiError as exc:
            raise DestinationError(f"facebook: {exc}") from None

    def _page(self, override: str = "") -> str:
        return str(override or account_id(self.cfg))

    def fetch_feed(self, limit: int, account_id: str = "") -> list[dict]:
        try:
            return self.api.page_feed(self._page(account_id), limit)
        except ApiError as exc:
            raise DestinationError(f"facebook: {exc}") from None

    def feed_markdown(self, limit: int, account_id: str = "") -> str:
        items = self.fetch_feed(limit, account_id)
        return format_feed_md(parse_feed_response({"data": items}))

    def refresh(self) -> dict:
        try:
            return refresh_feed(self.cfg, token=self.token)
        except ApiError as exc:
            raise DestinationError(f"facebook: {exc}") from None

    def cached_feed(self) -> list[FeedItem] | None:
        return load_cached_items(self.cfg)

    def feed_section(self, items: list[FeedItem]) -> str:
        return render_feed_section(items)

    def token_status(self) -> dict:
        return check_token(self.cfg, self.token)
