"""Facebook destination: the Graph transport, the Page publisher, the reader.

Everything that talks to facebook.com / graph.facebook.com lives in this
package. The rest of the factory only reaches it through ``destinations``.
"""

from .api import (
    ApiError,
    GraphApi,
    api_from_config,
    check_token,
    token_status_from_debug,
)
from .feed import FeedItem, format_feed_md, parse_fb_datetime, parse_feed_response
from .feed_html import render_feed_html, render_feed_section
from .publisher import FacebookPublisher
from .reader import (
    HTML_NAME,
    JSON_NAME,
    FacebookReader,
    account_id,
    feed_cache_dir,
    load_cached_items,
    refresh_feed,
)

__all__ = [
    "ApiError",
    "GraphApi",
    "api_from_config",
    "check_token",
    "token_status_from_debug",
    "FeedItem",
    "format_feed_md",
    "parse_fb_datetime",
    "parse_feed_response",
    "render_feed_html",
    "render_feed_section",
    "FacebookPublisher",
    "FacebookReader",
    "HTML_NAME",
    "JSON_NAME",
    "account_id",
    "feed_cache_dir",
    "load_cached_items",
    "refresh_feed",
]
