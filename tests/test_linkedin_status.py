"""linkin-bot gateway status (fetch stubbed — no network)."""

from __future__ import annotations

import io
import json
import urllib.error

from tests.test_dashboard_html import GENERATED, REFRESH, SCAN, STATS

from social_bot.dashboard_html import render_status_html
from social_bot.destinations import linkedin_status
from social_bot.destinations.linkedin import status as li_status


def _cfg(**kw):
    block = {"base_url": "http://localhost:8082", "timeout_seconds": 5.0}
    block.update(kw)
    return {"destinations": {"linkedin": block}}


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *args, **kwargs):
        return self._body


PAYLOAD = {
    "status": "ok",
    "kill_switch": False,
    "oauth": {"connected": True, "summary": "oauth token: expires in 59 days"},
    "caps": {
        "connect": {"sent_today": 0, "day_remaining": 30, "week_remaining": 20},
        "follow": {"sent_today": 0, "day_remaining": 10, "week_remaining": 50},
    },
    "schedule": {"connect": ["09:30"]},
    "next_run": {"connect": "2026-10-14 09:30"},
}


class TestFetch:
    def test_ok(self, monkeypatch):
        monkeypatch.setattr(
            li_status.urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(PAYLOAD)
        )
        view = linkedin_status(_cfg())
        assert view["ok"] is True
        assert view["connected"] is True
        assert view["oauth_summary"].startswith("oauth token")
        assert [c["kind"] for c in view["caps"]] == ["connect", "follow"]
        assert view["next_run"] == {"connect": "2026-10-14 09:30"}

    def test_gateway_down_is_a_view_not_an_error(self, monkeypatch):
        def boom(req, timeout=None):
            raise urllib.error.URLError("refused")

        monkeypatch.setattr(li_status.urllib.request, "urlopen", boom)
        view = linkedin_status(_cfg())
        assert view["ok"] is False
        assert "refused" in view["error"]

    def test_http_error_carries_the_status(self, monkeypatch):
        def gone(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 502, "bad", {}, io.BytesIO(b"down"))

        monkeypatch.setattr(li_status.urllib.request, "urlopen", gone)
        view = linkedin_status(_cfg())
        assert view["ok"] is False
        assert "502" in view["error"]

    def test_unconfigured(self):
        view = linkedin_status(_cfg(base_url=""))
        assert view["configured"] is False
        assert view["ok"] is False


class TestSummarize:
    def test_tolerates_an_empty_payload(self):
        out = li_status.summarize({})
        assert out["connected"] is None
        assert out["caps"] == []
        assert out["schedule"] == {}

    def test_status_url(self):
        assert li_status.status_url(_cfg()) == "http://localhost:8082/status"


class TestSection:
    def _out(self, linkedin):
        return render_status_html(
            STATS, refresh=REFRESH, scan=SCAN, linkedin=linkedin, generated_at=GENERATED
        )

    def test_ok_panel(self, monkeypatch):
        monkeypatch.setattr(
            li_status.urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(PAYLOAD)
        )
        out = self._out(linkedin_status(_cfg()))
        assert "LinkedIn" in out
        assert "oauth token" in out
        assert "09:30" in out and "2026-10-14 09:30" in out
        assert "badge-valid" in out

    def test_zero_counts_render_as_zero(self, monkeypatch):
        monkeypatch.setattr(
            li_status.urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(PAYLOAD)
        )
        out = self._out(linkedin_status(_cfg()))
        assert "<td>0</td>" in out

    def test_error_panel(self):
        out = self._out(
            {
                "configured": True,
                "ok": False,
                "base_url": "http://localhost:8082",
                "checked_at": "x",
                "error": "<boom>",
            }
        )
        assert "LinkedIn" in out
        assert "<boom>" not in out and "&lt;boom&gt;" in out

    def test_none_renders_no_panel(self):
        out = render_status_html(STATS, refresh=REFRESH, scan=SCAN, generated_at=GENERATED)
        assert '<span class="label">LinkedIn</span>' not in out
