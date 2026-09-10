"""Serve scheduling helpers (pure logic — no fastapi/uvicorn needed)."""

from __future__ import annotations

import datetime as dt

import pytest

from social_bot.web import (
    _parse_hhmm,
    current_slot,
    next_run_at,
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
