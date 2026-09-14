"""Serve scheduling helpers (pure logic — no fastapi/uvicorn needed)."""

from __future__ import annotations

import datetime as dt

import pytest

from social_bot.web import (
    _parse_hhmm,
    _slot_time,
    _slot_window,
    _writable_dir,
    apply_runtime_state,
    current_slot,
    image_jobs_view,
    infer_last_runs,
    live_view,
    next_post_at,
    next_run_at,
    readiness_view,
    runtime_state_snapshot,
    seconds_until,
    seconds_until_any,
)


class TestParseHhmm:
    def test_valid(self):
        assert _parse_hhmm("07:00") == (7, 0)
        assert _parse_hhmm("23:59") == (23, 59)

    @pytest.mark.parametrize("bad", ["7", "0700", "24:00", "12:60", "aa:bb", "", "-1:00"])
    def test_invalid(self, bad):
        with pytest.raises(ValueError):
            _parse_hhmm(bad)


class TestSlotWindows:
    """A 'HH:MM-HH:MM' slot fires at a stable random time inside the window."""

    DAY = dt.date(2026, 9, 10)

    def test_slot_window_detects_ranges(self):
        assert _slot_window("07:00") is None
        assert _slot_window("19:30-21:00") == ((19, 30), (21, 0))

    def test_fixed_time_unchanged(self):
        assert _slot_time("07:00", self.DAY) == dt.datetime(2026, 9, 10, 7, 0)

    def test_window_time_is_inside_and_on_the_day(self):
        moment = _slot_time("19:30-21:00", self.DAY)
        assert moment.date() == self.DAY
        assert dt.datetime(2026, 9, 10, 19, 30) <= moment < dt.datetime(2026, 9, 10, 21, 0)

    def test_window_time_is_stable_for_the_day(self):
        assert _slot_time("19:30-21:00", self.DAY) == _slot_time("19:30-21:00", self.DAY)

    def test_seconds_until_window_lands_in_the_window(self):
        now = dt.datetime(2026, 9, 10, 12, 0)
        target = now + dt.timedelta(seconds=seconds_until("19:30-21:00", now))
        assert dt.datetime(2026, 9, 10, 19, 30) <= target < dt.datetime(2026, 9, 10, 21, 0)

    def test_current_slot_uses_today_once_past_the_window(self):
        slot = current_slot(["19:30-21:00"], dt.datetime(2026, 9, 10, 23, 0))
        assert slot is not None and slot.startswith("2026-09-10 ")
        assert "2026-09-10 19:30" <= slot < "2026-09-10 21:00"

    def test_current_slot_uses_yesterday_before_the_window(self):
        slot = current_slot(["19:30-21:00"], dt.datetime(2026, 9, 10, 12, 0))
        assert slot is not None and slot.startswith("2026-09-09 ")


class TestSecondsUntil:
    def test_later_today(self):
        now = dt.datetime(2026, 9, 10, 6, 0)
        assert seconds_until("07:00", now) == 3600

    def test_already_passed_rolls_to_tomorrow(self):
        now = dt.datetime(2026, 9, 10, 8, 0)
        assert seconds_until("07:00", now) == 23 * 3600

    def test_exactly_at_time_rolls_forward(self):
        now = dt.datetime(2026, 9, 10, 7, 0)
        assert seconds_until("07:00", now) == 24 * 3600

    def test_any_picks_nearest(self):
        now = dt.datetime(2026, 9, 10, 6, 0)
        assert seconds_until_any(["07:00", "19:00"], now) == 3600
        assert seconds_until_any(["19:00", "07:00"], now) == 3600


class TestNextRunAt:
    def test_next_today(self):
        now = dt.datetime(2026, 9, 10, 18, 0)
        assert next_run_at(["07:00", "19:00"], now) == dt.datetime(2026, 9, 10, 19, 0)

    def test_rolls_to_tomorrow(self):
        now = dt.datetime(2026, 9, 10, 20, 0)
        assert next_run_at(["07:00", "19:00"], now) == dt.datetime(2026, 9, 11, 7, 0)


class TestNextPostAt:
    """The slot that can actually send — the interval gate skips earlier wakes."""

    NOW = dt.datetime(2026, 9, 12, 15, 57)

    def test_no_schedule_is_none(self):
        assert next_post_at([], interval_remaining=2, now=self.NOW) is None

    def test_without_a_hold_it_is_the_next_wake(self):
        assert next_post_at(["09:00", "20:00"], now=self.NOW) == dt.datetime(2026, 9, 12, 20, 0)

    def test_hold_lands_on_the_day_the_gate_lifts(self):
        assert next_post_at(
            ["09:00", "20:00"], interval_remaining=1, now=self.NOW
        ) == dt.datetime(2026, 9, 13, 9, 0)

    def test_hold_picks_the_earliest_of_several_slots(self):
        assert next_post_at(
            ["20:00", "09:00"], interval_remaining=2, now=self.NOW
        ) == dt.datetime(2026, 9, 14, 9, 0)

    def test_hold_with_a_window_lands_inside_the_window(self):
        moment = next_post_at(["19:30-21:00"], interval_remaining=1, now=self.NOW)
        assert moment.date() == dt.date(2026, 9, 13)
        assert dt.datetime(2026, 9, 13, 19, 30) <= moment < dt.datetime(2026, 9, 13, 21, 0)


class TestCurrentSlot:
    def test_most_recent_today(self):
        now = dt.datetime(2026, 9, 10, 12, 0)
        assert current_slot(["07:00", "19:00"], now) == "2026-09-10 07:00"

    def test_after_evening_run(self):
        now = dt.datetime(2026, 9, 10, 20, 0)
        assert current_slot(["07:00", "19:00"], now) == "2026-09-10 19:00"

    def test_before_first_uses_yesterday(self):
        now = dt.datetime(2026, 9, 10, 6, 0)
        assert current_slot(["07:00", "19:00"], now) == "2026-09-09 19:00"


class TestReadiness:
    def test_all_checks_pass(self):
        payload, status = readiness_view({"a": True, "b": True})
        assert status == 200
        assert payload["status"] == "ready"
        assert payload["failed"] == []

    def test_any_failure_is_503(self):
        payload, status = readiness_view({"a": True, "b": False})
        assert status == 503
        assert payload["status"] == "not ready"
        assert payload["failed"] == ["b"]

    def test_live_view_always_alive(self):
        assert live_view() == {"status": "alive"}


class TestWritableDir:
    def test_existing_dir(self, tmp_path):
        assert _writable_dir(tmp_path) is True

    def test_missing_dir_walks_up_to_writable_parent(self, tmp_path):
        assert _writable_dir(tmp_path / "nested" / "deep") is True


class TestRuntimeState:
    def test_round_trip(self):
        state = {
            "last_started": dt.datetime(2026, 9, 11, 7, 0, 5),
            "last_finished": dt.datetime(2026, 9, 11, 7, 0, 30),
            "last_ok": True,
            "last_error": None,
            "last_slot": "2026-09-11 07:00",
            "scan_started": None,
            "scan_finished": dt.datetime(2026, 9, 11, 6, 0, 12),
            "scan_ok": False,
            "scan_error": "boom",
            "scan_slot": "2026-09-11 06:00",
            "last_added": 3,
        }
        restored: dict = {}
        apply_runtime_state(restored, runtime_state_snapshot(state))
        assert restored["last_finished"] == dt.datetime(2026, 9, 11, 7, 0, 30)
        assert restored["last_ok"] is True
        assert restored["last_slot"] == "2026-09-11 07:00"
        assert restored["scan_finished"] == dt.datetime(2026, 9, 11, 6, 0, 12)
        assert restored["scan_ok"] is False
        assert restored["scan_error"] == "boom"
        assert restored["scan_started"] is None
        assert restored["last_added"] == 3

    def test_snapshot_of_fresh_state_is_all_none(self):
        snap = runtime_state_snapshot({})
        assert snap["refresh"]["last_finished"] is None
        assert snap["refresh"]["ok"] is None
        assert snap["scan"]["slot"] is None

    def test_posting_pause_round_trips(self):
        snap = runtime_state_snapshot({"post_paused": True})
        assert snap["post"]["paused"] is True
        restored: dict = {}
        apply_runtime_state(restored, snap)
        assert restored["post_paused"] is True

    def test_posting_pause_defaults_off(self):
        assert runtime_state_snapshot({})["post"]["paused"] is False
        restored = {"post_paused": True}
        apply_runtime_state(restored, {"refresh": {}, "scan": {}})
        assert restored["post_paused"] is False

    def test_bad_payload_is_ignored(self):
        state = {"last_ok": True}
        apply_runtime_state(state, "not a dict")
        assert state["last_ok"] is True


class TestInferLastRuns:
    @staticmethod
    def _cfg(root):
        return {
            "feed": {"dir": str(root / "feed")},
            "review": {"dir": str(root / "review"), "seen_name": "seen.json"},
        }

    def test_reads_artifact_mtimes(self, tmp_path):
        (tmp_path / "feed").mkdir()
        (tmp_path / "review").mkdir()
        (tmp_path / "feed" / "latest.json").write_text("[]", encoding="utf-8")
        (tmp_path / "review" / "seen.json").write_text("[]", encoding="utf-8")
        out = infer_last_runs(self._cfg(tmp_path))
        assert out["refresh"] is not None
        assert out["scan"] is not None

    def test_missing_artifacts_are_none(self, tmp_path):
        out = infer_last_runs(self._cfg(tmp_path))
        assert out["refresh"] is None
        assert out["scan"] is None


class TestImageJobsView:
    def test_empty(self):
        assert image_jobs_view(True, {}) == {
            "enabled": True,
            "running": 0,
            "failed": 0,
            "jobs": [],
        }

    def test_serializes_running_and_failed(self):
        started = dt.datetime(2026, 9, 11, 8, 0, 0)
        finished = dt.datetime(2026, 9, 11, 8, 0, 30)
        view = image_jobs_view(
            True,
            {
                "a": {"status": "running", "started_at": started},
                "b": {"status": "error", "error": "HTTP 520", "finished_at": finished},
            },
        )
        assert view["enabled"] is True
        assert view["running"] == 1
        assert view["failed"] == 1
        assert view["jobs"] == [
            {
                "draft_id": "a",
                "status": "running",
                "error": "",
                "started_at": "2026-09-11 08:00:00",
                "finished_at": None,
            },
            {
                "draft_id": "b",
                "status": "error",
                "error": "HTTP 520",
                "started_at": None,
                "finished_at": "2026-09-11 08:00:30",
            },
        ]

    def test_ok_and_unchanged_are_not_failures(self):
        view = image_jobs_view(
            True,
            {"a": {"status": "ok"}, "b": {"status": "unchanged"}, "c": {"status": "skipped"}},
        )
        assert view["running"] == 0
        assert view["failed"] == 0
        assert [job["status"] for job in view["jobs"]] == ["ok", "unchanged", "skipped"]

