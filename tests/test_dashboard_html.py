"""Operator UI pages: dashboard, published log, status (pure rendering)."""

from __future__ import annotations

import datetime as dt

from social_bot.dashboard_html import (
    render_dashboard_html,
    render_publish_html,
    render_status_html,
)
from social_bot.destinations.facebook.feed import FeedItem
from social_bot.destinations.facebook.feed_html import render_feed_section

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
        "destination_state": [
            {"name": "facebook", "label": "Facebook", "enabled": True, "configured": True},
            {"name": "linkedin", "label": "LinkedIn", "enabled": False, "configured": False},
        ],
        "post_at": ["09:00", "20:00"],
        "post_per_slot": 1,
        "interval_days": 2,
        "interval_remaining": 0,
        "approved": 2,
        "next_draft": {
            "id": "post-old",
            "title": "Oldest approved draft",
            "source": "atento-blog",
            "has_image": True,
        },
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
POST = {
    "busy": False,
    "ok": None,
    "error": None,
    "last_posted": None,
    "last_finished": None,
    "schedule": ["09:00", "20:00"],
    "next": "2026-09-11 09:00",
    "next_post": "2026-09-11 09:00",
}


def _dash(feed_items=None, *, account_label="Atento Education", **kw):
    """render_dashboard_html with a Facebook feed panel, as the app wires it."""
    section = ""
    count = 0
    if feed_items:
        section = render_feed_section(feed_items)
        count = len(feed_items)
    kw.setdefault("stats", STATS)
    kw.setdefault("refresh", REFRESH)
    kw.setdefault("scan", SCAN)
    kw.setdefault("generated_at", GENERATED)
    return render_dashboard_html(
        feed_section=section,
        feed_label="Facebook feed",
        feed_count=count,
        account_label=account_label,
        **kw,
    )


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
        out = _dash()
        for href in ('href="/"', 'href="/review"', 'href="/publish"', 'href="/status"'):
            assert href in out

    def test_controls_post_to_refresh_and_scan(self):
        out = _dash()
        assert 'action="/refresh"' in out and "Refresh feed" in out
        assert 'action="/scan"' in out and "Scan sources" in out

    def test_counts_and_schedule(self):
        out = _dash()
        assert ">8<" in out  # open drafts
        assert "2026-09-10 19:00" in out  # next refresh
        assert "2026-09-11 06:00" in out  # next scan

    def test_renders_feed_items(self):
        items = [FeedItem(message="Hello fans", permalink_url="https://fb/1")]
        out = _dash(feed_items=items)
        assert "Hello fans" in out
        assert "Facebook feed" in out

    def test_no_cache_hint(self):
        out = _dash()  # no feed items, but a reader is present
        assert "No feed cached yet" in out

    def test_no_reader_hides_the_feed_panel_and_control(self):
        out = render_dashboard_html(
            stats=STATS, refresh=REFRESH, scan=SCAN, generated_at=GENERATED
        )
        assert "No feed cached yet" not in out
        assert 'action="/refresh"' not in out
        assert "no destination configured" in out

    def test_message_is_escaped(self):
        out = _dash(message="<b>Scan started</b>")
        assert "&lt;b&gt;Scan started&lt;/b&gt;" in out

    def test_private_mode_notice(self):
        out = _dash(private=True)
        assert "Private mode" in out

    def test_shows_the_account_label(self):
        out = _dash(account_label="Atento Education")
        assert "Atento Education" in out


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
        out = _dash(images=IMAGES)
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
        assert "2 post(s)" in out
        assert out.index("2026-09-10T09:07:15") < out.index("2026-09-09T10:00:00")

    def test_links_permalink_without_a_visibility_column(self):
        out = render_publish_html(RECORDS, generated_at=GENERATED)
        assert "https://www.facebook.com/1_2" in out
        assert "Visibility" not in out
        assert '<div class="sub">2 post(s) · generated' in out

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
        assert "min interval" in out
        assert "2026-09-10 07:00:00" in out  # last refresh run

    def test_document_shape(self):
        out = render_status_html(STATS, refresh=REFRESH, scan=SCAN, generated_at=GENERATED)
        assert out.lstrip().startswith("<!doctype html>")
        assert out.rstrip().endswith("</html>")

    def test_token_not_checked_yet(self):
        out = render_status_html(STATS, refresh=REFRESH, scan=SCAN, generated_at=GENERATED)
        assert "Not checked yet." in out

    def test_lists_destinations(self):
        out = render_status_html(STATS, refresh=REFRESH, scan=SCAN, generated_at=GENERATED)
        assert "Destinations" in out
        assert "Facebook" in out and "LinkedIn" in out

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


class TestTimedPosting:
    def test_dashboard_shows_next_post_and_control(self):
        out = _dash(post=POST)
        assert "Next post" in out
        assert "2026-09-11 09:00" in out
        assert "Post schedule" in out
        assert 'action="/publish/run"' in out

    def test_dashboard_hides_posting_without_a_schedule(self):
        out = _dash()
        assert "Next post" not in out
        assert "Post schedule" not in out
        assert 'action="/publish/run"' not in out

    def test_status_shows_schedule_and_settings(self):
        out = render_status_html(
            STATS, refresh=REFRESH, scan=SCAN, post=POST, generated_at=GENERATED
        )
        assert "Post schedule" in out
        assert "post at" in out
        assert "09:00, 20:00" in out
        assert "min interval (days)" in out
        assert ">2<" in out

    def test_dashboard_next_post_card_names_the_draft(self):
        out = _dash(post=POST)
        assert "Next post" in out
        assert "Oldest approved draft (post-old)" in out

    def test_dashboard_posting_line_names_the_draft(self):
        out = _dash(post=POST)
        assert "next up Oldest approved draft (post-old)" in out

    def test_dashboard_says_when_nothing_is_approved(self):
        stats = {**STATS, "publish": {**STATS["publish"], "approved": 0, "next_draft": None}}
        out = _dash(stats=stats, post=POST)
        assert "nothing approved yet" in out

    def test_dashboard_shows_the_interval_hold(self):
        stats = {
            **STATS,
            "publish": {**STATS["publish"], "interval_remaining": 2},
        }
        out = _dash(stats=stats, post=POST)
        assert "in 2 day(s)" in out

    def test_dashboard_next_post_shows_the_interval_aware_time(self):
        # The scheduler wakes tomorrow, but the interval holds the post back:
        # the Next post row shows the slot that can send, not the next wake.
        stats = {**STATS, "publish": {**STATS["publish"], "interval_remaining": 1}}
        post = {**POST, "next": "2026-09-12 19:51", "next_post": "2026-09-13 20:14"}
        out = _dash(stats=stats, post=post)
        assert '<span class="sched-when">2026-09-13 20:14</span>' in out
        # the scheduler wake stays, but only on the Post schedule row
        assert '<span class="sched-when">next 2026-09-12 19:51</span>' in out

    def test_status_lists_the_next_draft_and_interval(self):
        out = render_status_html(
            STATS, refresh=REFRESH, scan=SCAN, post=POST, generated_at=GENERATED
        )
        assert "next up" in out
        assert "Oldest approved draft (post-old)" in out
        assert "interval remaining (days)" in out

    def test_posting_line_notes_the_interval_hold(self):
        stats = {
            **STATS,
            "publish": {**STATS["publish"], "interval_remaining": 2},
        }
        out = render_status_html(
            stats, refresh=REFRESH, scan=SCAN, post=POST, generated_at=GENERATED
        )
        assert "waits 2 day(s)" in out

    def test_next_draft_title_is_escaped(self):
        stats = {
            **STATS,
            "publish": {
                **STATS["publish"],
                "next_draft": {"id": "x", "title": "<script>alert(1)</script>"},
            },
        }
        out = _dash(stats=stats, post=POST)
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_status_hides_posting_without_a_schedule(self):
        out = render_status_html(STATS, refresh=REFRESH, scan=SCAN, generated_at=GENERATED)
        assert "Post schedule" not in out
        assert "post at" in out  # the setting row still renders, as "—"


class TestPostingPause:
    PAUSED = {**POST, "paused": True}

    def test_dashboard_offers_pause_when_running(self):
        out = _dash(post=POST)
        assert 'action="/publish/pause"' in out and "Pause posting" in out
        assert 'action="/publish/resume"' not in out

    def test_dashboard_offers_resume_when_paused(self):
        out = _dash(post=self.PAUSED)
        assert 'action="/publish/resume"' in out and "Resume posting" in out
        assert 'action="/publish/pause"' not in out

    def test_dashboard_reports_the_pause(self):
        out = _dash(post=self.PAUSED)
        assert '<span class="sched-when">paused</span>' in out
        assert "resume to schedule the next post" in out
        assert "posting paused" in out  # the Approved pipeline stage

    def test_status_reports_the_pause(self):
        out = render_status_html(
            STATS, refresh=REFRESH, scan=SCAN, post=self.PAUSED, generated_at=GENERATED
        )
        assert '<span class="sched-when">paused</span>' in out

    def test_no_pause_control_without_a_schedule(self):
        out = _dash()
        assert 'action="/publish/pause"' not in out
        assert 'action="/publish/resume"' not in out
