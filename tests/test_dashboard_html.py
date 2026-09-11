"""Operator UI pages: dashboard, published log, status (pure rendering)."""

from __future__ import annotations

import datetime as dt

from social_bot.dashboard_html import (
    render_dashboard_html,
    render_publish_html,
    render_status_html,
)
from social_bot.feed import FeedItem

GENERATED = dt.datetime(2026, 9, 10, 12, 0)

STATS = {
    "sources": [
        {"name": "atento-blog", "type": "index", "url": "https://atento.vn/blog", "lang": "vi"}
    ],
    "drafts": {"total": 8, "open": 8, "by_state": {"extracted": 0, "ai_draft": 8}},
    "seen": 8,
    "published": {"total": 2, "private": 1, "recent": []},
    "publish": {
        "enabled": True,
        "private": False,
        "destinations": ["facebook"],
        "max_per_day": 10,
        "dna_file_set": True,
    },
}

REFRESH = {
    "busy": False,
    "ok": True,
    "error": None,
    "last_finished": "2026-09-10 07:00:00",
    "schedule": ["07:00", "19:00"],
    "next": "2026-09-10 19:00",
}
SCAN = {
    "busy": False,
    "ok": None,
    "error": None,
    "last_added": None,
    "last_finished": None,
    "schedule": ["06:00"],
    "next": "2026-09-11 06:00",
}

RECORDS = [
    {
        "id": "a",
        "source": "atento-blog",
        "url": "https://atento.vn/blog/a",
        "destination": "facebook",
        "post_id": "1_2",
        "permalink": "https://www.facebook.com/1_2",
        "posted_at": "2026-09-09T10:00:00+00:00",
    },
    {
        "id": "b",
        "source": "atento-blog",
        "url": "",
        "destination": "facebook",
        "post_id": "122131563729359840",
        "permalink": "",
        "posted_at": "2026-09-10T09:07:15+00:00",
        "private": True,
    },
]


class TestDashboard:
    def test_has_navigation_to_every_page(self):
        out = render_dashboard_html(
            items=[], stats=STATS, refresh=REFRESH, scan=SCAN, generated_at=GENERATED
        )
        for href in ('href="/"', 'href="/review"', 'href="/publish"', 'href="/status"'):
            assert href in out

    def test_controls_post_to_refresh_and_scan(self):
        out = render_dashboard_html(
            items=[], stats=STATS, refresh=REFRESH, scan=SCAN, generated_at=GENERATED
        )
        assert 'action="/refresh"' in out and "Refresh feed" in out
        assert 'action="/scan"' in out and "Scan sources" in out

    def test_counts_and_schedule(self):
        out = render_dashboard_html(
            items=[], stats=STATS, refresh=REFRESH, scan=SCAN, generated_at=GENERATED
        )
        assert ">8<" in out  # open drafts
        assert "2026-09-10 19:00" in out  # next refresh
        assert "2026-09-11 06:00" in out  # next scan

    def test_renders_feed_items(self):
        items = [FeedItem(message="Hello fans", permalink_url="https://fb/1")]
        out = render_dashboard_html(
            items=items, stats=STATS, refresh=REFRESH, scan=SCAN, generated_at=GENERATED
        )
        assert "Hello fans" in out

    def test_no_cache_hint(self):
        out = render_dashboard_html(
            items=None, stats=STATS, refresh=REFRESH, scan=SCAN, generated_at=GENERATED
        )
        assert "No feed cached yet" in out

    def test_message_is_escaped(self):
        out = render_dashboard_html(
            items=[], stats=STATS, refresh=REFRESH, scan=SCAN,
            message="<b>Scan started</b>", generated_at=GENERATED,
        )
        assert "&lt;b&gt;Scan started&lt;/b&gt;" in out

    def test_private_mode_notice(self):
        out = render_dashboard_html(
            items=[], stats=STATS, refresh=REFRESH, scan=SCAN,
            private=True, generated_at=GENERATED,
        )
        assert "Private mode" in out


IMAGES = {
    "enabled": True,
    "running": 1,
    "failed": 1,
    "jobs": [
        {
            "draft_id": "post-one",
            "status": "running",
            "error": "",
            "started_at": "2026-09-11 08:00:00",
            "finished_at": None,
        },
        {
            "draft_id": "post-two",
            "status": "error",
            "error": "HTTP 520 <upstream>",
            "started_at": "2026-09-11 08:00:00",
            "finished_at": "2026-09-11 08:00:30",
        },
    ],
}


class TestImageSection:
    def test_dashboard_shows_image_jobs(self):
        out = render_dashboard_html(
            items=[], stats=STATS, refresh=REFRESH, scan=SCAN,
            images=IMAGES, generated_at=GENERATED,
        )
        assert "Image jobs" in out
        assert "post-two" in out
        assert "badge-failed" in out and "badge-running" in out

    def test_status_shows_image_jobs(self):
        out = render_status_html(
            STATS, refresh=REFRESH, scan=SCAN, images=IMAGES, generated_at=GENERATED
        )
        assert "2 job(s) · 1 running · 1 failed" in out
        assert "post-one" in out

    def test_newest_job_first(self):
        out = render_status_html(
            STATS, refresh=REFRESH, scan=SCAN, images=IMAGES, generated_at=GENERATED
        )
        assert out.index("post-two") < out.index("post-one")

    def test_error_text_is_escaped(self):
        out = render_status_html(
            STATS, refresh=REFRESH, scan=SCAN, images=IMAGES, generated_at=GENERATED
        )
        assert "<upstream>" not in out
        assert "&lt;upstream&gt;" in out

    def test_no_jobs_yet(self):
        out = render_status_html(
            STATS, refresh=REFRESH, scan=SCAN,
            images={"enabled": True, "running": 0, "failed": 0, "jobs": []},
            generated_at=GENERATED,
        )
        assert "No image jobs yet" in out

    def test_disabled(self):
        out = render_status_html(
            STATS, refresh=REFRESH, scan=SCAN,
            images={"enabled": False, "running": 0, "failed": 0, "jobs": []},
            generated_at=GENERATED,
        )
        assert "Disabled" in out

    def test_absent_images_renders_no_section(self):
        out = render_status_html(STATS, refresh=REFRESH, scan=SCAN, generated_at=GENERATED)
        assert "Image jobs" not in out



class TestPublish:
    def test_lists_records_newest_first(self):
        out = render_publish_html(RECORDS, generated_at=GENERATED)
        assert "2 post(s) · 1 public · 1 private" in out
        assert out.index("2026-09-10T09:07:15") < out.index("2026-09-09T10:00:00")

    def test_links_permalink_and_marks_visibility(self):
        out = render_publish_html(RECORDS, generated_at=GENERATED)
        assert "https://www.facebook.com/1_2" in out
        assert "public" in out and "private" in out

    def test_no_permalink_shows_no_post_id(self):
        # A private/unpublished send returns no post — don't render a bare id.
        out = render_publish_html(RECORDS, generated_at=GENERATED)
        assert "122131563729359840" not in out

    def test_empty(self):
        out = render_publish_html([], generated_at=GENERATED)
        assert "Nothing published yet." in out

    def test_escapes_source(self):
        out = render_publish_html(
            [{"source": "<script>alert(1)</script>", "posted_at": "x"}], generated_at=GENERATED
        )
        assert "<script>" not in out
        assert "&lt;script&gt;" in out


class TestStatus:
    def test_renders_snapshot(self):
        out = render_status_html(STATS, refresh=REFRESH, scan=SCAN, generated_at=GENERATED)
        assert "atento-blog" in out
        assert "ai_draft" in out
        assert "max per day" in out
        assert "2026-09-10 07:00:00" in out  # last refresh run

    def test_document_shape(self):
        out = render_status_html(STATS, refresh=REFRESH, scan=SCAN, generated_at=GENERATED)
        assert out.lstrip().startswith("<!doctype html>")
        assert out.rstrip().endswith("</html>")

    def test_token_not_checked_yet(self):
        out = render_status_html(STATS, refresh=REFRESH, scan=SCAN, generated_at=GENERATED)
        assert "Not checked yet." in out

    def test_token_valid_with_expiry(self):
        token = {
            "valid": True,
            "type": "PAGE",
            "expires_at": "2026-11-09T21:12:21+00:00",
            "never_expires": False,
            "expires_in_days": 59,
            "scopes": ["pages_read_engagement", "pages_manage_posts"],
            "checked_at": "2026-09-11 08:00:00",
        }
        out = render_status_html(
            STATS, refresh=REFRESH, scan=SCAN, token=token, generated_at=GENERATED
        )
        assert "badge-valid" in out
        assert "in 59 day" in out
        assert "2 granted" in out
        assert "2026-09-11 08:00:00" in out

    def test_token_never_expires(self):
        token = {"valid": True, "never_expires": True, "checked_at": "2026-09-11 08:00:00"}
        out = render_status_html(
            STATS, refresh=REFRESH, scan=SCAN, token=token, generated_at=GENERATED
        )
        assert "badge-valid" in out
        assert ">never<" in out

    def test_token_invalid_shows_error(self):
        token = {
            "valid": False,
            "error": "Session has expired",
            "checked_at": "2026-09-11 08:00:00",
        }
        out = render_status_html(
            STATS, refresh=REFRESH, scan=SCAN, token=token, generated_at=GENERATED
        )
        assert "badge-invalid" in out
        assert "Session has expired" in out

    def test_token_error_is_escaped(self):
        token = {"valid": False, "error": "<script>alert(1)</script>", "checked_at": "x"}
        out = render_status_html(
            STATS, refresh=REFRESH, scan=SCAN, token=token, generated_at=GENERATED
        )
        assert "<script>" not in out
        assert "&lt;script&gt;" in out
