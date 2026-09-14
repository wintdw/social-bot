"""Feed -> HTML rendering (pure logic)."""

from __future__ import annotations

import datetime as dt

from social_bot.destinations.facebook.feed import FeedItem, parse_feed_response
from social_bot.destinations.facebook.feed_html import (
    render_feed_html,
    render_feed_section,
)

GENERATED = dt.datetime(2026, 9, 10, 12, 0)

SAMPLE = {
    "data": [
        {
            "id": "123_1",
            "created_time": "2026-09-08T07:12:34+0000",
            "message": "Hello page fans!",
            "status_type": "mobile_status_update",
            "permalink_url": "https://www.facebook.com/123/posts/1",
            "full_picture": "https://scontent.example.com/hero.jpg",
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
        assert '<img src="https://scontent.example.com/hero.jpg"' in out

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

    def test_escapes_image_url(self):
        item = FeedItem(image='https://example.com/x.jpg"><script>alert(1)</script>')
        out = render_feed_section([item])
        assert "<script>" not in out
        assert 'src="https://example.com/x.jpg&quot;&gt;&lt;script&gt;' in out

    def test_empty_feed(self):
        out = render_feed_html([], page_id="123", generated_at=GENERATED)
        assert "No posts on the feed." in out

    def test_has_navigation(self):
        out = render_feed_html([], page_id="123", generated_at=GENERATED)
        assert 'href="/review"' in out and 'href="/status"' in out


class TestRenderFeedSection:
    def test_fragment_has_queue_rows_but_no_document(self):
        out = render_feed_section(parse_feed_response(SAMPLE))
        assert 'class="qrow"' in out
        assert 'class="qthumb"' in out
        assert "Hello page fans!" in out
        assert "<!doctype html>" not in out

    def test_post_without_image_gets_the_empty_placeholder(self):
        out = render_feed_section([FeedItem(message="text only")])
        assert 'class="qthumb empty"' in out
        assert "<img" not in out

    def test_post_with_a_masthead_titles_the_row_with_the_hook(self):
        out = render_feed_section([FeedItem(message="[Học cùng Atento]\n\nNội dung")])
        assert 'class="qtitle">Nội dung</span>' in out
        assert '<span class="pill">[Học cùng Atento]</span>' in out
        assert 'class="qpreview"' not in out

    def test_the_masthead_rides_along_in_the_meta_not_as_the_title(self):
        out = render_feed_section(
            [FeedItem(message="[Học cùng Atento]\n\nCâu hook\n\nPhần thân.")]
        )
        assert 'class="qtitle">Câu hook</span>' in out
        assert 'class="qpreview">Phần thân.</span>' in out
        assert '<span class="pill">[Học cùng Atento]</span>' in out

    def test_post_without_a_masthead_takes_its_first_line_as_the_title(self):
        out = render_feed_section([FeedItem(message="Câu hook\n\nPhần thân còn lại.")])
        assert 'class="qtitle">Câu hook</span>' in out
        assert 'class="qpreview">Phần thân còn lại.</span>' in out

    def test_a_single_line_post_still_gets_a_title_and_no_preview(self):
        out = render_feed_section([FeedItem(message="Chỉ một dòng")])
        assert 'class="qtitle">Chỉ một dòng</span>' in out
        assert 'class="qpreview"' not in out

    def test_photo_post_without_text_gets_a_neutral_title(self):
        out = render_feed_section([FeedItem(status_type="added_photos")])
        assert 'class="qtitle">(no text — added_photos post)</span>' in out
        assert 'class="qpreview"' not in out

    def test_a_long_first_line_is_truncated_for_the_title(self):
        out = render_feed_section([FeedItem(message="x" * 120)])
        assert "x" * 79 + "…" in out

    def test_post_with_a_permalink_is_a_row_link(self):
        out = render_feed_section([FeedItem(message="Hi", permalink_url="https://fb/1")])
        assert '<a class="qrow" href="https://fb/1">' in out
        assert 'class="qgo"' in out

    def test_post_without_a_permalink_is_not_a_link(self):
        out = render_feed_section([FeedItem(message="Hi")])
        assert '<div class="qrow">' in out
        assert "qgo" not in out

    def test_empty_fragment(self):
        assert "No posts on the feed." in render_feed_section([])
