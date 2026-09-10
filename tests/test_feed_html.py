"""Feed -> HTML rendering (pure logic)."""

from __future__ import annotations

import datetime as dt

from social_bot.feed import FeedItem, parse_feed_response
from social_bot.feed_html import render_feed_html, render_feed_section

GENERATED = dt.datetime(2026, 9, 10, 12, 0)

SAMPLE = {
    "data": [
        {
            "id": "123_1",
            "created_time": "2026-09-08T07:12:34+0000",
            "message": "Hello page fans!",
            "status_type": "mobile_status_update",
            "permalink_url": "https://www.facebook.com/123/posts/1",
            "from": {"name": "Example Page", "id": "123"},
        },
        {"id": "123_2", "status_type": "added_photos"},
    ]
}


class TestRenderFeedHtml:
    def test_renders_posts(self):
        out = render_feed_html(parse_feed_response(SAMPLE), page_id="123", generated_at=GENERATED)
        assert "Hello page fans!" in out
        assert "https://www.facebook.com/123/posts/1" in out
        assert "2 most recent post(s)" in out
        assert "(no text — added_photos post)" in out

    def test_document_shape(self):
        out = render_feed_html([], page_id="123", generated_at=GENERATED)
        assert out.lstrip().startswith("<!doctype html>")
        assert out.rstrip().endswith("</html>")

    def test_escapes_user_content(self):
        item = FeedItem(
            message="<script>alert(1)</script>",
            permalink_url="https://example.com/?a=1&b=2",
        )
        out = render_feed_html([item], generated_at=GENERATED)
        assert "<script>" not in out
        assert "&lt;script&gt;" in out
        assert "?a=1&amp;b=2" in out

    def test_empty_feed(self):
        out = render_feed_html([], page_id="123", generated_at=GENERATED)
        assert "No posts on the feed." in out

    def test_has_navigation(self):
        out = render_feed_html([], page_id="123", generated_at=GENERATED)
        assert 'href="/review"' in out and 'href="/status"' in out


class TestRenderFeedSection:
    def test_fragment_has_articles_but_no_document(self):
        out = render_feed_section(parse_feed_response(SAMPLE))
        assert "<article>" in out
        assert "Hello page fans!" in out
        assert "<!doctype html>" not in out

    def test_empty_fragment(self):
        assert "No posts on the feed." in render_feed_section([])
