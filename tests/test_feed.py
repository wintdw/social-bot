"""Feed parsing + rendering tests (pure logic, no network)."""

from __future__ import annotations

import datetime as dt

from social_bot.feed import format_feed_md, parse_fb_datetime, parse_feed_response

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
        {
            "id": "123_2",
            "created_time": "2026-09-07T22:00:00Z",
            "story": "Example Page shared a link.",
            "status_type": "shared_story",
            "permalink_url": "https://www.facebook.com/123/posts/2",
        },
        {"id": "123_3", "status_type": "added_photos"},  # media post, no text/timestamp
    ]
}


class TestParseFbDatetime:
    def test_offset_without_colon(self):
        parsed = parse_fb_datetime("2026-09-08T07:12:34+0000")
        assert parsed is not None
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == dt.timedelta(0)

    def test_zulu_suffix(self):
        parsed = parse_fb_datetime("2026-09-07T22:00:00Z")
        assert parsed is not None and parsed.hour == 22

    def test_none_and_garbage(self):
        assert parse_fb_datetime(None) is None
        assert parse_fb_datetime("") is None
        assert parse_fb_datetime("not-a-date") is None


class TestParseFeedResponse:
    def test_maps_fields(self):
        items = parse_feed_response(SAMPLE)
        assert len(items) == 3
        first = items[0]
        assert first.id == "123_1"
        assert first.from_name == "Example Page"
        assert first.message == "Hello page fans!"
        assert first.created is not None
        assert first.status_type == "mobile_status_update"

    def test_story_fallback_text(self):
        items = parse_feed_response(SAMPLE)
        assert items[1].text == "Example Page shared a link."
        assert items[1].from_name == ""  # no `from` -> empty, not crash

    def test_media_post_without_text(self):
        items = parse_feed_response(SAMPLE)
        assert items[2].text == "" and items[2].created is None

    def test_empty_feed(self):
        assert parse_feed_response({"data": []}) == []
        assert parse_feed_response({}) == []


class TestFormatFeedMd:
    def test_renders_posts(self):
        out = format_feed_md(parse_feed_response(SAMPLE))
        assert "Hello page fans!" in out
        assert "Example Page shared a link." in out
        assert "https://www.facebook.com/123/posts/1" in out
        assert "(no text — added_photos post)" in out
        assert out.index("Hello page fans!") < out.index("Example Page shared a link.")

    def test_empty_feed_message(self):
        assert "No posts" in format_feed_md([])
