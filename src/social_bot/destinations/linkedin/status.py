"""LinkedIn gateway status — read linkin-bot's ``GET /status`` for the UI.

linkin-bot (a sibling service) owns the LinkedIn session (browser cookies) and
the posting schedules; this app only posts through its ``POST /post`` gateway.
Its ``GET /status`` is the operator's view into that side: session
connectivity, daily/weekly caps, schedules, and recent flow runs. This module
fetches and summarizes it so ``/status`` (and ``/api/status``) can display it.

Network stays in ``fetch_payload``; ``summarize`` is pure (no network, no
config) so it is testable without the gateway. ``get_status`` never raises —
a down gateway is an ``ok: False`` view, never a broken ``/status`` page.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.request

from ..base import DestinationError

STATUS_PATH = "/status"
DEFAULT_TIMEOUT = 10.0


class LinkedInStatusError(DestinationError):
    """The linkin-bot gateway status could not be read."""


def status_url(cfg: dict) -> str:
    """The gateway's ``/status`` URL from ``destinations.linkedin.base_url``."""
    base = str(cfg.get("destinations", {}).get("linkedin", {}).get("base_url") or "")
    return base.rstrip("/") + STATUS_PATH


def is_configured(cfg: dict) -> bool:
    """True when a gateway URL is set — no token needed on this side."""
    return bool(str(cfg.get("destinations", {}).get("linkedin", {}).get("base_url") or "").strip())


def _timeout(cfg: dict) -> float:
    try:
        timeout = float(
            cfg.get("destinations", {}).get("linkedin", {}).get("timeout_seconds", DEFAULT_TIMEOUT)
        )
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    return timeout if timeout > 0 else DEFAULT_TIMEOUT


def fetch_payload(cfg: dict, timeout: float | None = None) -> dict:
    """GET the gateway's ``/status`` and return the decoded JSON object.

    Raises ``LinkedInStatusError`` on anything unexpected (no URL configured,
    unreachable gateway, non-JSON body) — ``get_status`` turns that into a view.
    """
    url = status_url(cfg)
    if not url.startswith(("http://", "https://")):
        raise LinkedInStatusError("linkedin: destinations.linkedin.base_url is not set")
    wait = DEFAULT_TIMEOUT if timeout is None else timeout
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=wait) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise LinkedInStatusError(f"linkedin: gateway returned HTTP {exc.code}: {detail}") from None
    except (urllib.error.URLError, ValueError, OSError) as exc:
        raise LinkedInStatusError(f"linkedin: cannot reach the gateway: {exc}") from None
    if not isinstance(body, dict):
        raise LinkedInStatusError("linkedin: gateway returned a non-object status")
    return body


def summarize(payload: dict) -> dict:
    """Reduce a raw ``/status`` payload to what the operator UI shows (pure).

    Tolerant by design: linkin-bot owns this schema and may add keys, so every
    lookup has a default and an unexpected shape yields ``None``/``""`` rather
    than a ``KeyError``.

    Connectivity comes from the ``session`` object (linkin-bot logs in with
    browser cookies, not OAuth): ``present`` plus ``has_li_at`` (the auth
    cookie). An old gateway may still send ``oauth`` instead — that is kept as
    a fallback so either shape renders.
    """
    payload = payload if isinstance(payload, dict) else {}
    oauth = payload.get("oauth") if isinstance(payload.get("oauth"), dict) else {}
    session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
    posts = payload.get("posts") if isinstance(payload.get("posts"), dict) else {}
    caps = payload.get("caps") if isinstance(payload.get("caps"), dict) else {}
    schedule = payload.get("schedule") if isinstance(payload.get("schedule"), dict) else {}
    next_run = payload.get("next_run") if isinstance(payload.get("next_run"), dict) else {}

    cap_rows: list[dict] = []
    for kind, cap in caps.items():
        if not isinstance(cap, dict):
            continue
        cap_rows.append(
            {
                "kind": str(kind),
                "sent_today": cap.get("sent_today"),
                "day_remaining": cap.get("day_remaining"),
                "week_remaining": cap.get("week_remaining"),
                "remaining": cap.get("remaining"),
            }
        )
    cap_rows.sort(key=lambda row: row["kind"])

    def _str_list(value) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value]
        return [str(value)] if value else []

    if session:
        present = session.get("present")
        has_li_at = session.get("has_li_at")
        if present is False or has_li_at is False:
            connected: bool | None = False
        elif present is True:
            connected = True
        elif isinstance(oauth.get("connected"), bool):
            connected = oauth.get("connected")
        else:
            connected = None
        session_summary = str(session.get("summary") or "")
        if not session_summary and isinstance(present, bool):
            session_summary = (
                "session: present" if present else "session: missing — re-login linkin-bot"
            )
        check = session.get("last_check") if isinstance(session.get("last_check"), dict) else {}
        check_ok = check.get("ok")
        state = "ok" if check_ok is True else ("failed" if check_ok is False else "")
        detail = str(check.get("detail") or "")
        at = str(check.get("at") or "")
        joined = ", ".join(part for part in (detail, at) if part)
        session_check = f"{state} ({joined})" if state and joined else (state or joined)
    else:
        connected = oauth.get("connected") if isinstance(oauth.get("connected"), bool) else None
        session_summary = ""
        session_check = ""

    return {
        "status": str(payload.get("status") or ""),
        "connected": connected,
        # Legacy key from the OAuth-shaped payload; new gateways send
        # ``session`` instead, surfaced as ``session_summary`` below.
        "oauth_summary": str(oauth.get("summary") or ""),
        "session_summary": session_summary,
        "session_check": session_check,
        "page_url": str(posts.get("page_url") or ""),
        "kill_switch": bool(payload.get("kill_switch", False)),
        "caps": cap_rows,
        "schedule": {str(k): _str_list(v) for k, v in schedule.items()},
        "next_run": {str(k): str(v) for k, v in next_run.items() if v},
    }


def get_status(cfg: dict, timeout: float | None = None) -> dict:
    """The LinkedIn panel view for ``/status`` — never raises (pure shape).

    ``ok: True`` carries the summary; ``ok: False`` carries ``error``. ``web.py``
    calls this off the event loop and hands the result to
    ``dashboard_html.render_status_html(linkedin=...)``.
    """
    checked_at = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    base_url = str(cfg.get("destinations", {}).get("linkedin", {}).get("base_url") or "")
    if not is_configured(cfg):
        return {
            "configured": False,
            "ok": False,
            "base_url": base_url,
            "checked_at": checked_at,
            "error": "not configured — set destinations.linkedin.base_url",
        }
    try:
        payload = fetch_payload(cfg, timeout=_timeout(cfg) if timeout is None else timeout)
    except LinkedInStatusError as exc:
        return {
            "configured": True,
            "ok": False,
            "base_url": base_url,
            "checked_at": checked_at,
            "error": str(exc),
        }
    return {
        "configured": True,
        "ok": True,
        "base_url": base_url,
        "checked_at": checked_at,
        "error": "",
        **summarize(payload),
    }
