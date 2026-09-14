"""FastAPI operator UI, JSON API, and in-process schedulers.

`serve` is a long-lived process with one operator UI: the dashboard at `/`
(controls + feed + counts), the review queue at `/review` (fed by the content
pipeline), the publish log at `/publish`, and a status page at `/status`. It runs
three container-local schedules — a feed refresh (`--refresh-at`), a source scan
(`--scan-at`), and timed posting (`--publish-at`, from `publish.post_at`).
Scanning only *queues* drafts, and the poster only posts drafts a human has
already approved on `/review/{id}` — it never approves or rewrites anything.
fastapi is an optional [server] extra, imported defensively so this module still
loads without it.

The scheduling/time helpers are pure (injectable `now`) so they are testable
without fastapi installed.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import os
import pathlib
import random
import sys
import traceback
import urllib.parse
from collections import Counter

from . import draft_pipeline as pipeline
from .config import load_config
from .dashboard_html import render_dashboard_html, render_publish_html, render_status_html
from .destinations import DestinationError, default_reader
from .destinations.facebook import (
    JSON_NAME,
    feed_cache_dir,
    load_cached_items,
    refresh_feed,
    render_feed_section,
)
from .draft_html import render_draft_html, render_drafts_html, render_message_html

# Optional [server] extra. Importing web.py without fastapi must still work
# (the pure helpers below are used by tests), so the names resolve to None and
# create_app() reports the missing extra. Request is needed at module scope so
# FastAPI can resolve the route handlers' string annotations.
try:  # pragma: no cover - exercised with/without the extra
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
except ImportError:  # pragma: no cover
    FastAPI = Request = None
    HTMLResponse = JSONResponse = RedirectResponse = None

DEFAULT_REFRESH_TIMES = ["07:00", "19:00"]
DEFAULT_SCAN_TIMES = ["06:00"]

# Paging defaults. The review list pages in the UI; the JSON API is bounded too,
# so a caller (the rewriter agent) can't pull an unbounded queue in one request.
REVIEW_PER_PAGE = 20
REVIEW_MAX_PER_PAGE = 200
API_DEFAULT_LIMIT = 100
API_MAX_LIMIT = 500

# How long shutdown waits for an in-flight publish to finish before cancelling
# the background loops. Keep below uvicorn's --timeout-graceful-shutdown.
DRAIN_TIMEOUT_SECONDS = 30.0

# The loops /ready treats as the heartbeat of the service. The token/page loops
# are one-shot startup lookups and are deliberately excluded — a finished task
# there is normal, not a dead scheduler.
SCHEDULER_LOOPS = ("refresh", "scan")


class _Draining(Exception):
    """The app is shutting down and is not accepting new publish work."""


def _parse_hhmm(text: str) -> tuple[int, int]:
    """Parse "HH:MM" into (hour, minute); raise ValueError on anything else."""
    hh, _, mm = str(text).partition(":")
    if not (hh.isdigit() and mm.isdigit()):
        raise ValueError(f"invalid time {text!r}: expected HH:MM")
    hour, minute = int(hh), int(mm)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid time {text!r}: expected HH:MM")
    return hour, minute


def _slot_window(slot: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """(start, end) clock pairs for a "HH:MM-HH:MM" window, or None if fixed."""
    text = str(slot)
    if "-" not in text:
        return None
    start, _, end = text.partition("-")
    return _parse_hhmm(start), _parse_hhmm(end)


def _slot_time(slot: str, day: dt.date) -> dt.datetime:
    """The instant ``slot`` fires on ``day``.

    A fixed "HH:MM" is that time. A "HH:MM-HH:MM" window picks a random minute
    inside it, seeded by the day and the slot text so the choice is stable
    across restarts — the scheduler's "this slot already ran" guard relies on
    recomputing the same instant.
    """
    window = _slot_window(slot)
    if window is None:
        hour, minute = _parse_hhmm(slot)
    else:
        (start_h, start_m), (end_h, end_m) = window
        hour, minute = divmod(
            random.Random(f"{day.isoformat()}|{slot}").randrange(
                start_h * 60 + start_m, end_h * 60 + end_m
            ),
            60,
        )
    return dt.datetime.combine(day, dt.time(hour, minute))


def _occurrence(slot: str, now: dt.datetime) -> dt.datetime:
    return _slot_time(slot, now.date())


def _next_occurrence(hhmm: str, now: dt.datetime) -> dt.datetime:
    occurrence = _occurrence(hhmm, now)
    if occurrence <= now:
        occurrence = _slot_time(hhmm, now.date() + dt.timedelta(days=1))
    return occurrence


def seconds_until(hhmm: str, now: dt.datetime | None = None) -> float:
    now = now or dt.datetime.now()
    return (_next_occurrence(hhmm, now) - now).total_seconds()


def seconds_until_any(times: list[str], now: dt.datetime | None = None) -> float:
    now = now or dt.datetime.now()
    return min(seconds_until(t, now) for t in times)


def next_run_at(times: list[str], now: dt.datetime | None = None) -> dt.datetime:
    now = now or dt.datetime.now()
    return min(_next_occurrence(t, now) for t in times)


def next_post_at(
    times: list[str],
    *,
    interval_remaining: int = 0,
    now: dt.datetime | None = None,
) -> dt.datetime | None:
    """The first slot that can actually post, honoring ``publish.interval_days``.

    The scheduler wakes at every slot, but the interval gate makes it skip the
    ones before the gap has elapsed — so the next *wake* is often not the next
    *post*. ``interval_remaining`` days out is the first day the gate lifts, and
    that day's earliest slot is the one that sends. None when there is no
    schedule.
    """
    if not times:
        return None
    now = now or dt.datetime.now()
    if interval_remaining <= 0:
        return next_run_at(times, now)
    day = now.date() + dt.timedelta(days=int(interval_remaining))
    return min(_slot_time(slot, day) for slot in times)


def current_slot(times: list[str], now: dt.datetime | None = None) -> str | None:
    """The most recent scheduled occurrence at/before now, as 'YYYY-MM-DD HH:MM'."""
    now = now or dt.datetime.now()
    latest: dt.datetime | None = None
    for hhmm in times:
        occurrence = _slot_time(hhmm, now.date())
        if occurrence > now:
            occurrence = _slot_time(hhmm, now.date() - dt.timedelta(days=1))
        if latest is None or occurrence > latest:
            latest = occurrence
    return latest.strftime("%Y-%m-%d %H:%M") if latest else None


def _iso(value: dt.datetime | None) -> str | None:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else None


def _clamp(value, lo: int, hi: int, default: int) -> int:
    """Coerce a query-string value into [lo, hi], falling back to `default`."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, number))


# The scheduler's last-run state lives in memory, but the process is restarted
# on every deploy — so it is also mirrored to a small JSON file next to the
# other state dirs. Without this the dashboard shows "not run yet" after any
# restart, even though refresh/scan have clearly been running.
STATE_NAME = "state.json"


def _state_path(cfg: dict) -> pathlib.Path:
    """Where the restart-durable scheduler state lives (sibling of review/)."""
    return pipeline.review_dir(cfg).parent / STATE_NAME


def _parse_iso(text) -> dt.datetime | None:
    """Parse a stored ISO-8601 timestamp, or None when absent/invalid."""
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(str(text))
    except ValueError:
        return None


def runtime_state_snapshot(state: dict) -> dict:
    """The restart-durable slice of the scheduler state (pure).

    The last-run outcome plus the posting pause is kept: a job in flight when
    the process dies is not "running" anymore, so `busy` is deliberately left
    out, but a pause must outlive the process.
    """
    return {
        "refresh": {
            "last_started": _iso(state.get("last_started")),
            "last_finished": _iso(state.get("last_finished")),
            "ok": state.get("last_ok"),
            "error": state.get("last_error"),
            "slot": state.get("last_slot"),
        },
        "scan": {
            "last_started": _iso(state.get("scan_started")),
            "last_finished": _iso(state.get("scan_finished")),
            "ok": state.get("scan_ok"),
            "error": state.get("scan_error"),
            "slot": state.get("scan_slot"),
            "added": state.get("last_added"),
        },
        # The pause survives a restart: a deploy must not silently resume a
        # posting hold an operator set on purpose.
        "post": {"paused": bool(state.get("post_paused"))},
    }


def apply_runtime_state(state: dict, data: dict) -> None:
    """Restore a snapshot from runtime_state_snapshot into live state (pure)."""
    if not isinstance(data, dict):
        return
    refresh = data.get("refresh") or {}
    state["last_started"] = _parse_iso(refresh.get("last_started"))
    state["last_finished"] = _parse_iso(refresh.get("last_finished"))
    state["last_ok"] = refresh.get("ok")
    state["last_error"] = refresh.get("error")
    state["last_slot"] = refresh.get("slot")
    scan = data.get("scan") or {}
    state["scan_started"] = _parse_iso(scan.get("last_started"))
    state["scan_finished"] = _parse_iso(scan.get("last_finished"))
    state["scan_ok"] = scan.get("ok")
    state["scan_error"] = scan.get("error")
    state["scan_slot"] = scan.get("slot")
    state["last_added"] = scan.get("added")
    post = data.get("post") or {}
    state["post_paused"] = bool(post.get("paused"))


def _read_state_file(path: pathlib.Path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state_file(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _mtime(path: pathlib.Path) -> dt.datetime | None:
    """A file's modification time as a naive local datetime, or None."""
    try:
        return dt.datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def infer_last_runs(cfg: dict) -> dict:
    """Last-run times from the artifacts a refresh/scan writes (pure).

    A fallback for a first boot against an existing data dir: the feed cache's
    mtime is when refresh last succeeded and seen.json is rewritten at the end
    of every scan, so the dashboard reports real last runs even before this
    process has performed any.
    """
    return {
        "refresh": _mtime(feed_cache_dir(cfg) / JSON_NAME),
        "scan": _mtime(pipeline.seen_path(cfg)),
    }


def live_view() -> dict:
    """Liveness payload: the process is up and serving. Pure."""
    return {"status": "alive"}


def readiness_view(checks: dict[str, bool]) -> tuple[dict, int]:
    """Turn a name->ok map into (payload, HTTP status). Pure.

    Ready means every check passed (200); any failure is 503 so a load balancer
    stops routing to this instance while it drains or is unhealthy.
    """
    failed = [name for name, ok in checks.items() if not ok]
    payload = {
        "status": "ready" if not failed else "not ready",
        "checks": checks,
        "failed": failed,
    }
    return payload, (200 if not failed else 503)


def _writable_dir(path) -> bool:
    """True when the nearest existing ancestor of `path` is writable.

    The state dirs may not exist yet on a first boot, so walk up to the first
    path that does and test that — this is a read-only probe (no mkdir).
    """
    candidate = pathlib.Path(path)
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return os.access(candidate, os.W_OK)


def image_jobs_view(enabled: bool, images: dict) -> dict:
    """Serialize the background image-job state for /api/status (pure).

    ``images`` maps draft id -> {status, error?, started_at?, finished_at?} as
    maintained by the running app. Pure so it is testable without fastapi.
    """
    jobs = [
        {
            "draft_id": draft_id,
            "status": info.get("status"),
            "error": info.get("error", ""),
            "started_at": _iso(info.get("started_at")),
            "finished_at": _iso(info.get("finished_at")),
        }
        for draft_id, info in images.items()
    ]
    return {
        "enabled": enabled,
        "running": sum(1 for job in jobs if job["status"] == "running"),
        "failed": sum(1 for job in jobs if job["status"] == "error"),
        "jobs": jobs,
    }


def create_app(
    config_path=None,
    refresh_at: list[str] | None = None,
    boot_refresh: bool = False,
    scan_at: list[str] | None = None,
    boot_scan: bool = False,
    post_at: list[str] | None = None,
):
    """Build the FastAPI app: cached feed at `/`, draft review UI, schedulers."""
    if FastAPI is None:
        raise RuntimeError(
            "serve needs the [server] extra: pip install 'social-bot[server]'"
        )

    cfg = load_config(config_path)
    times = list(refresh_at or DEFAULT_REFRESH_TIMES)
    scan_times = list(scan_at or cfg.get("blog", {}).get("scan_at") or DEFAULT_SCAN_TIMES)
    # An explicit [] disables timed posting, so only fall back to config when the
    # caller passed None (the CLI cannot pass an empty list).
    if post_at is None:
        post_times = list(cfg.get("publish", {}).get("post_at") or [])
    else:
        post_times = list(post_at)
    private = bool(cfg.get("publish", {}).get("private", False))
    image_enabled = bool(pipeline.image_gen_config(cfg).get("enabled"))
    # The account reader for the enabled destinations (facebook today). None when
    # no enabled destination can read a feed, so the feed panels and the
    # page/token loops stay off rather than failing.
    reader = default_reader(cfg)

    state: dict = {
        "busy": False,
        "lock": asyncio.Lock(),
        "last_started": None,
        "last_finished": None,
        "last_ok": None,
        "last_error": None,
        "last_slot": None,
        "scan_busy": False,
        "scan_lock": asyncio.Lock(),
        "scan_started": None,
        "scan_finished": None,
        "scan_ok": None,
        "scan_error": None,
        "scan_slot": None,
        "last_added": None,
        # Timed posting: the scheduler only posts human-approved drafts.
        "post_busy": False,
        "post_lock": asyncio.Lock(),
        "post_started": None,
        "post_finished": None,
        "post_ok": None,
        "post_error": None,
        "post_slot": None,
        "last_posted": None,
        # Timed posting can be paused at runtime (and the pause persisted to
        # state.json) so the poster skips its slots without touching the
        # schedule. Manual posting is a human action and is not affected.
        "post_paused": False,
        "page_name": None,
        "token_status": None,
        "token_error": None,
        "token_checked": None,
        "token_busy": False,
        "image_lock": asyncio.Lock(),
        # Lifecycle: shutdown sets `shutting_down`, pauses new publish work, and
        # waits on `drain` (cleared while a publish is in flight, set when none).
        "shutting_down": False,
        "inflight_publishes": 0,
        "drain": asyncio.Event(),
        # The scheduler tasks (by name) and every fire-and-forget task, so
        # shutdown can cancel/await them and /ready can spot a dead loop.
        "loops": {},
        "bg_tasks": set(),
        # Per-draft status of the background image job, so an operator can tell
        # "running", "failed" and "done" apart — the draft's own `image` field
        # only ever shows the end state (present or not).
        "images": {},
    }
    state["drain"].set()  # nothing in flight yet

    # Restore the last-run state so a restart doesn't reset the dashboard to
    # "not run yet". With no saved state (first boot after an upgrade) fall back
    # to the mtimes of the feed cache / seen ledger, which record real runs.
    state_path = _state_path(cfg)
    saved = _read_state_file(state_path)
    if saved:
        apply_runtime_state(state, saved)
    else:
        inferred = infer_last_runs(cfg)
        if inferred["refresh"]:
            state["last_finished"] = inferred["refresh"]
            state["last_ok"] = True
        if inferred["scan"]:
            state["scan_finished"] = inferred["scan"]
            state["scan_ok"] = True

    def _persist_state() -> None:
        try:
            _write_state_file(state_path, runtime_state_snapshot(state))
        except OSError as exc:  # never let bookkeeping kill the app
            print(f"[web] cannot persist scheduler state: {exc}", file=sys.stderr, flush=True)

    def _lookup_page_name() -> str:
        if reader is None:
            return ""
        info = reader.account()
        return str(info.get("name") or "").strip()

    async def _page_job() -> None:
        """Resolve the account's display name for the dashboard (best-effort)."""
        if reader is None:
            return
        try:
            name = await asyncio.to_thread(_lookup_page_name)
        except Exception as exc:  # a name lookup must never kill the app
            print(f"[web] page name lookup failed: {exc}", file=sys.stderr, flush=True)
            return
        if name:
            state["page_name"] = name
            print(f"[web] page: {name}", flush=True)

    async def _page_loop() -> None:
        await asyncio.sleep(1)  # let the server bind
        await _page_job()

    def _image_note(draft_id: str, status: str, error: str = "") -> None:
        """Record the latest image-job outcome for one draft (bounded)."""
        info = state["images"].get(draft_id) or {"draft_id": draft_id}
        info["status"] = status
        if error:
            info["error"] = error
        else:
            info.pop("error", None)
        now = dt.datetime.now()
        if status == "running":
            info["started_at"] = now
        else:
            info["finished_at"] = now
        state["images"][draft_id] = info
        while len(state["images"]) > 50:  # keep the map bounded
            state["images"].pop(next(iter(state["images"])))

    async def _token_job(reason: str) -> None:
        """Check the token's validity/expiry so /status can display it."""
        if reader is None or state["token_busy"]:
            return
        state["token_busy"] = True
        try:
            status = await asyncio.to_thread(reader.token_status)
        except Exception as exc:  # a token check must never kill the app
            status = {"valid": None, "error": str(exc)}
        finally:
            state["token_checked"] = dt.datetime.now()
            state["token_busy"] = False
        state["token_status"] = status
        state["token_error"] = status.get("error")
        print(f"[web] token checked (reason={reason}, valid={status.get('valid')})", flush=True)

    async def _token_loop() -> None:
        await asyncio.sleep(1)  # let the server bind
        await _token_job("startup")

    async def _refresh_job(reason: str) -> None:
        if reader is None:
            return  # no feed-capable destination is enabled
        async with state["lock"]:
            if state["busy"]:
                return
            state["busy"] = True
            state["last_started"] = dt.datetime.now()
            print(f"[web] refresh starting (reason={reason})", flush=True)
            try:
                result = await asyncio.to_thread(refresh_feed, cfg)
                state["last_ok"] = True
                state["last_error"] = None
                print(
                    f"[web] refresh finished (reason={reason}, posts={result['count']})",
                    flush=True,
                )
            except Exception as exc:  # a failed refresh must never kill the app
                state["last_ok"] = False
                state["last_error"] = str(exc)
                print(f"[web] refresh failed (reason={reason}): {exc}", file=sys.stderr, flush=True)
                traceback.print_exc()
            finally:
                state["last_finished"] = dt.datetime.now()
                state["busy"] = False
        _persist_state()
        # A refresh needs a working token — refresh the token readout with it.
        await _token_job(f"after refresh ({reason})")
        if not state["page_name"]:
            await _page_job()

    async def _scheduler_loop() -> None:
        await asyncio.sleep(1)  # let the server bind
        print(
            f"[web] scheduler up: refresh at {', '.join(times)} container-local "
            f"(next: {next_run_at(times):%Y-%m-%d %H:%M})",
            flush=True,
        )
        if boot_refresh:
            await _refresh_job("startup")
            state["last_slot"] = current_slot(times)
        while True:
            await asyncio.sleep(seconds_until_any(times))
            slot = current_slot(times)
            if slot is None or state["last_slot"] == slot:
                continue  # this slot already ran (startup or manual)
            state["last_slot"] = slot
            await _refresh_job(f"scheduled {slot}")

    async def _scan_job(reason: str) -> None:
        """Scan source feeds into drafts. Never posts — publishing is human-gated."""
        async with state["scan_lock"]:
            if state["scan_busy"]:
                return
            state["scan_busy"] = True
            state["scan_started"] = dt.datetime.now()
            print(f"[web] scan starting (reason={reason})", flush=True)
            try:
                result = await asyncio.to_thread(pipeline.scan_sources, cfg)
                state["scan_ok"] = True
                state["scan_error"] = None
                state["last_added"] = result["added"]
                print(
                    f"[web] scan finished (reason={reason}, added={result['added']})",
                    flush=True,
                )
                for err in result.get("errors", []):
                    print(
                        f"[web] scan source error: {err['source']}: {err['error']}",
                        file=sys.stderr,
                        flush=True,
                    )
                if result.get("skipped_old"):
                    print(
                        f"[web] scan skipped {result['skipped_old']} item(s) older "
                        f"than blog.max_age_days",
                        flush=True,
                    )
            except Exception as exc:  # a failed scan must never kill the app
                state["scan_ok"] = False
                state["scan_error"] = str(exc)
                print(f"[web] scan failed (reason={reason}): {exc}", file=sys.stderr, flush=True)
                traceback.print_exc()
            finally:
                state["scan_finished"] = dt.datetime.now()
                state["scan_busy"] = False
        _persist_state()

    async def _scanner_loop() -> None:
        await asyncio.sleep(1)  # let the server bind
        print(
            f"[web] scanner up: scan at {', '.join(scan_times)} container-local "
            f"(next: {next_run_at(scan_times):%Y-%m-%d %H:%M})",
            flush=True,
        )
        if boot_scan:
            await _scan_job("startup")
            state["scan_slot"] = current_slot(scan_times)
        while True:
            await asyncio.sleep(seconds_until_any(scan_times))
            slot = current_slot(scan_times)
            if slot is None or state["scan_slot"] == slot:
                continue
            state["scan_slot"] = slot
            await _scan_job(f"scheduled {slot}")

    async def _post_job(reason: str) -> None:
        """Post a slot's worth of human-approved drafts. Never approves."""
        posted = 0
        async with state["post_lock"]:
            if state["post_busy"]:
                return
            state["post_busy"] = True
            state["post_started"] = dt.datetime.now()
            print(f"[web] posting starting (reason={reason})", flush=True)
            try:
                result = await _run_publish(pipeline.publish_scheduled, cfg)
                state["post_ok"] = True
                state["post_error"] = None
                posted = len(result["posted"])
                state["last_posted"] = posted
                print(
                    f"[web] posting finished (reason={reason}, posted={posted})",
                    flush=True,
                )
                for skip in result.get("skipped", []):
                    print(
                        f"[web] posting skipped {skip['id']}: {skip['reason']}",
                        flush=True,
                    )
                for err in result.get("errors", []):
                    print(
                        f"[web] posting error {err['id']}: {err['error']}",
                        file=sys.stderr,
                        flush=True,
                    )
            except Exception as exc:  # a failed post run must never kill the app
                state["post_ok"] = False
                state["post_error"] = str(exc)
                print(f"[web] posting failed (reason={reason}): {exc}", file=sys.stderr, flush=True)
                traceback.print_exc()
            finally:
                state["post_finished"] = dt.datetime.now()
                state["post_busy"] = False
        # A post lands in the feed, so refresh the cache right away instead of
        # waiting for the next --refresh-at slot: the dashboard shows it now.
        if posted and not state["shutting_down"]:
            await _refresh_job(f"after posting ({reason})")

    async def _posting_loop() -> None:
        await asyncio.sleep(1)  # let the server bind
        print(
            f"[web] poster up: post at {', '.join(post_times)} container-local "
            f"(next: {next_run_at(post_times):%Y-%m-%d %H:%M})",
            flush=True,
        )
        while True:
            await asyncio.sleep(seconds_until_any(post_times))
            slot = current_slot(post_times)
            if slot is None or state["post_slot"] == slot:
                continue  # this slot already ran (manual or a restart)
            state["post_slot"] = slot
            if state["post_paused"]:
                # Paused: consume the slot anyway, so resuming posts from the
                # next slot rather than firing a backlog of missed ones.
                print(f"[web] posting paused — skipping slot {slot}", flush=True)
                continue
            await _post_job(f"scheduled {slot}")

    async def _image_job(draft_id: str) -> None:
        """Generate the image for one just-rewritten draft (best-effort).

        Every post is a photo post, so serve fills the image right after a
        rewrite lands rather than waiting for a manual `blog image`. Serialized
        by ``image_lock`` because generation loads and rewrites the whole queue.
        A provider failure is logged and recorded on the draft's image status
        (``/api/status``) — it never fails the rewrite that triggered it.
        """
        async with state["image_lock"]:
            _image_note(draft_id, "running")
            try:
                result = await asyncio.to_thread(
                    pipeline.generate_missing_image, cfg, draft_id
                )
            except Exception as exc:  # a failed image must never kill the app
                _image_note(draft_id, "error", str(exc))
                print(f"[web] image failed ({draft_id}): {exc}", file=sys.stderr, flush=True)
                return
        if result is None:
            # image_gen is off, or the draft vanished while we waited.
            _image_note(draft_id, "skipped")
            return
        errors = result.get("errors", [])
        if result.get("generated"):
            _image_note(draft_id, "ok")
            print(f"[web] image generated for {draft_id}", flush=True)
        elif errors:
            detail = str(errors[0].get("error", ""))
            _image_note(draft_id, "error", detail)
            print(f"[web] image error ({draft_id}): {detail}", file=sys.stderr, flush=True)
        else:
            # Already had an image: a re-submitted rewrite must not regenerate.
            _image_note(draft_id, "unchanged")

    def _spawn(coro) -> asyncio.Task:
        """Run a fire-and-forget coroutine, tracked so shutdown can await it."""
        task = asyncio.create_task(coro)
        state["bg_tasks"].add(task)
        task.add_done_callback(state["bg_tasks"].discard)
        return task

    async def _run_publish(fn, *args, **kwargs):
        """Run a publish off the event loop, tracked so shutdown can drain it.

        Refused outright while shutting down, so no new post is started mid-drain;
        the caller turns `_Draining` into a 503.
        """
        if state["shutting_down"]:
            raise _Draining()
        state["inflight_publishes"] += 1
        state["drain"].clear()
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        finally:
            state["inflight_publishes"] -= 1
            if state["inflight_publishes"] == 0:
                state["drain"].set()

    def _set_post_paused(paused: bool) -> None:
        """Pause/resume the timed poster, persisted so a restart keeps the hold.

        Only the *scheduled* poster is affected: an explicit human send
        ("Post approved now", a draft's Post now, `blog publish`) still goes
        out, because the pause exists to stop unattended posting.
        """
        state["post_paused"] = paused
        _persist_state()
        print(f"[web] posting {'paused' if paused else 'resumed'}", flush=True)

    def _schedule_image(draft_id: str) -> None:
        """Queue a background image generation for a just-rewritten draft."""
        if state["shutting_down"]:
            return
        if not pipeline.image_gen_config(cfg).get("enabled"):
            return
        _spawn(_image_job(draft_id))

    def _state_writable() -> bool:
        """True when the review and publish state dirs are writable."""
        return all(
            _writable_dir(path)
            for path in (
                pipeline.review_dir(cfg),
                pipeline.published_path(cfg).parent,
            )
        )

    @contextlib.asynccontextmanager
    async def _lifespan(app):
        state["loops"] = {
            "refresh": asyncio.create_task(_scheduler_loop()),
            "scan": asyncio.create_task(_scanner_loop()),
        }
        if reader is not None:
            # Facebook-only lookups (page name, token status); skipped when no
            # enabled destination can read a feed.
            state["loops"]["token"] = asyncio.create_task(_token_loop())
            state["loops"]["page"] = asyncio.create_task(_page_loop())
        if post_times:
            state["loops"]["posting"] = asyncio.create_task(_posting_loop())
        try:
            yield
        finally:
            # Drain in-flight publishes before tearing the loops down: mark
            # not-ready, let a running post finish (bounded), then cancel.
            state["shutting_down"] = True
            inflight = state["inflight_publishes"]
            if inflight:
                print(
                    f"[web] shutdown: draining {inflight} in-flight publish(es)",
                    flush=True,
                )
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        state["drain"].wait(), timeout=DRAIN_TIMEOUT_SECONDS
                    )
            tasks = [*state["loops"].values(), *state["bg_tasks"]]
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    app = FastAPI(docs_url=None, redoc_url=None, lifespan=_lifespan)

    def _refresh_runtime() -> dict:
        return {
            "busy": state["busy"],
            "ok": state["last_ok"],
            "error": state["last_error"],
            "last_finished": _iso(state["last_finished"]),
            "schedule": times,
            "next": next_run_at(times).strftime("%Y-%m-%d %H:%M"),
        }

    def _scan_runtime() -> dict:
        return {
            "busy": state["scan_busy"],
            "ok": state["scan_ok"],
            "error": state["scan_error"],
            "last_added": state["last_added"],
            "last_finished": _iso(state["scan_finished"]),
            "schedule": scan_times,
            "next": next_run_at(scan_times).strftime("%Y-%m-%d %H:%M"),
        }

    def _token_runtime() -> dict:
        status = dict(state["token_status"] or {})
        if state["token_error"]:
            status["error"] = state["token_error"]
        status["checked_at"] = _iso(state["token_checked"])
        status["busy"] = state["token_busy"]
        return status

    def _post_runtime() -> dict:
        # `next` is the next scheduler wake; `next_post` is the slot that can
        # actually send (the interval gate may skip several wakes first).
        next_post = next_post_at(
            post_times, interval_remaining=pipeline.interval_remaining(cfg)
        )
        return {
            "busy": state["post_busy"],
            "ok": state["post_ok"],
            "error": state["post_error"],
            "last_posted": state["last_posted"],
            "last_finished": _iso(state["post_finished"]),
            "schedule": post_times,
            "paused": state["post_paused"],
            "next": next_run_at(post_times).strftime("%Y-%m-%d %H:%M") if post_times else "",
            "next_post": next_post.strftime("%Y-%m-%d %H:%M") if next_post else "",
        }

    def _next_post_label() -> str:
        """When the next post actually goes out, or '' when posting is disabled."""
        return str(_post_runtime().get("next_post") or "")

    def _image_runtime() -> dict:
        """Background image jobs, newest last — how /api/status reports them."""
        return image_jobs_view(image_enabled, state["images"])

    def _page(markup: str, status_code: int = 200) -> HTMLResponse:
        return HTMLResponse(
            markup, status_code=status_code, headers={"Cache-Control": "no-cache"}
        )

    def _dashboard_redirect(message: str) -> RedirectResponse:
        return RedirectResponse(
            f"/?message={urllib.parse.quote(message)}", status_code=303
        )

    @app.get("/", response_class=HTMLResponse)
    async def index(message: str = ""):
        """The operator dashboard: refresh/scan controls, counts, and feed."""
        stats = await asyncio.to_thread(pipeline.status, cfg)
        feed_section = ""
        feed_label = ""
        feed_count = 0
        if reader is not None:
            items = await asyncio.to_thread(load_cached_items, cfg)
            feed_label = f"{reader.label} feed"
            if items:
                feed_section = render_feed_section(items)
                feed_count = len(items)
        return _page(
            render_dashboard_html(
                feed_section=feed_section,
                feed_label=feed_label,
                feed_count=feed_count,
                account_label=state["page_name"] or feed_label,
                stats=stats,
                refresh=_refresh_runtime(),
                scan=_scan_runtime(),
                post=_post_runtime(),
                images=_image_runtime(),
                token=_token_runtime(),
                message=message,
                private=private,
            )
        )

    @app.get("/live")
    async def live():
        """Liveness: the process is up. Never touches state, so it can't flake."""
        return JSONResponse(live_view())

    @app.get("/ready")
    async def ready():
        """Readiness: can this instance serve? 503 while draining or unhealthy.

        Checks the schedulers are alive and the state dirs are writable — the two
        things that stop the pipeline working while the process still answers.
        """
        loops = state.get("loops") or {}
        schedulers = [loops.get(name) for name in SCHEDULER_LOOPS]
        checks = {
            "not_shutting_down": not state["shutting_down"],
            "schedulers_alive": all(
                task is not None and not task.done() for task in schedulers
            ),
            "state_writable": await asyncio.to_thread(_state_writable),
        }
        payload, status_code = readiness_view(checks)
        return JSONResponse(payload, status_code=status_code)

    @app.get("/health")
    async def health():
        open_drafts = await asyncio.to_thread(
            lambda: len(pipeline.list_drafts(cfg, pipeline.REVIEW_STATES))
        )
        return JSONResponse(
            {
                "status": "ok",
                "busy": state["busy"],
                "last_started": _iso(state["last_started"]),
                "last_finished": _iso(state["last_finished"]),
                "last_ok": state["last_ok"],
                "last_error": state["last_error"],
                "schedule": times,
                "next_refresh": next_run_at(times).strftime("%Y-%m-%d %H:%M"),
                "scan_busy": state["scan_busy"],
                "scan_ok": state["scan_ok"],
                "scan_error": state["scan_error"],
                "last_added": state["last_added"],
                "scan_schedule": scan_times,
                "next_scan": next_run_at(scan_times).strftime("%Y-%m-%d %H:%M"),
                "post_busy": state["post_busy"],
                "post_ok": state["post_ok"],
                "post_error": state["post_error"],
                "last_posted": state["last_posted"],
                "post_paused": state["post_paused"],
                "publish_schedule": post_times,
                "next_publish": next_run_at(post_times).strftime("%Y-%m-%d %H:%M") if post_times else "",
                "open_drafts": open_drafts,
                "shutting_down": state["shutting_down"],
                "inflight_publishes": state["inflight_publishes"],
            }
        )

    @app.get("/api/status")
    async def api_status():
        """A full pipeline snapshot: sources, drafts by state, posted, schedules."""
        stats = await asyncio.to_thread(pipeline.status, cfg)
        return JSONResponse(
            {
                "generated_at": dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                **stats,
                "scan": _scan_runtime(),
                "refresh": _refresh_runtime(),
                "post": _post_runtime(),
                "token": _token_runtime(),
                "images": _image_runtime(),
                "lifecycle": {
                    "shutting_down": state["shutting_down"],
                    "inflight_publishes": state["inflight_publishes"],
                },
            }
        )

    @app.post("/refresh")
    async def refresh_now():
        if state["shutting_down"]:
            return JSONResponse({"started": False, "reason": "shutting down"}, status_code=503)
        if state["busy"]:
            return JSONResponse(
                {"started": False, "reason": "refresh already running"}, status_code=409
            )
        state["last_slot"] = current_slot(times)
        _spawn(_refresh_job("manual"))
        return JSONResponse({"started": True})

    @app.post("/scan")
    async def scan_now(request: Request):
        """Trigger a source scan now. Never posts — it only queues drafts."""
        wants_html = "text/html" in request.headers.get("accept", "")
        if state["shutting_down"]:
            if wants_html:
                return RedirectResponse(
                    f"/review?message={urllib.parse.quote('Shutting down')}",
                    status_code=303,
                )
            return JSONResponse(
                {"started": False, "reason": "shutting down"}, status_code=503
            )
        if state["scan_busy"]:
            if wants_html:
                return RedirectResponse(
                    f"/review?message={urllib.parse.quote('Scan already running')}",
                    status_code=303,
                )
            return JSONResponse(
                {"started": False, "reason": "scan already running"}, status_code=409
            )
        state["scan_slot"] = current_slot(scan_times)
        _spawn(_scan_job("manual"))
        if wants_html:
            return RedirectResponse(
                f"/review?message={urllib.parse.quote('Scan started — refresh shortly')}",
                status_code=303,
            )
        return JSONResponse({"started": True})

    @app.post("/publish/run")
    async def publish_run(request: Request):
        """Post the approved queue now. Only human-approved drafts are posted."""
        wants_html = "text/html" in request.headers.get("accept", "")
        if state["shutting_down"]:
            if wants_html:
                return RedirectResponse(
                    f"/review?message={urllib.parse.quote('Shutting down')}",
                    status_code=303,
                )
            return JSONResponse(
                {"started": False, "reason": "shutting down"}, status_code=503
            )
        if state["post_busy"]:
            if wants_html:
                return RedirectResponse(
                    f"/review?message={urllib.parse.quote('Posting already running')}",
                    status_code=303,
                )
            return JSONResponse(
                {"started": False, "reason": "posting already running"}, status_code=409
            )
        state["post_slot"] = current_slot(post_times)
        _spawn(_post_job("manual"))
        if wants_html:
            return RedirectResponse(
                f"/review?message={urllib.parse.quote('Posting started — the approved queue drains shortly')}",
                status_code=303,
            )
        return JSONResponse({"started": True})

    @app.post("/publish/pause")
    async def publish_pause(request: Request):
        """Stop the poster firing at its slots until resumed (persisted).

        The schedule is untouched, and explicit sends still work — this only
        holds back the unattended poster.
        """
        wants_html = "text/html" in request.headers.get("accept", "")
        _set_post_paused(True)
        message = "Posting paused — the scheduler skips its slots until you resume. Post approved now still works."
        if wants_html:
            return _dashboard_redirect(message)
        return JSONResponse({"paused": True, "message": message})

    @app.post("/publish/resume")
    async def publish_resume(request: Request):
        """Resume the poster; the next scheduled slot posts again."""
        wants_html = "text/html" in request.headers.get("accept", "")
        _set_post_paused(False)
        message = "Posting resumed — the next scheduled slot posts again."
        if wants_html:
            return _dashboard_redirect(message)
        return JSONResponse({"paused": False, "message": message})

    # -- review queue (human-gated publishing) ---------------------------

    @app.get("/review", response_class=HTMLResponse)
    async def review_index(
        message: str = "",
        source: str = "",
        status: str = "",
        q: str = "",
        sort: str = "",
        page: int = 1,
        per_page: int = REVIEW_PER_PAGE,
    ):
        per_page = _clamp(per_page, 1, REVIEW_MAX_PER_PAGE, REVIEW_PER_PAGE)
        base = await asyncio.to_thread(pipeline.list_drafts, cfg, pipeline.REVIEW_STATES)
        drafts = pipeline.filter_drafts(base, source=source, state=status, q=q)
        drafts = pipeline.sort_drafts(drafts, sort)
        # Keep every option visible (so the active chip never disappears) but
        # count each row within the other row's selection and the active search,
        # so the numbers add up to what clicking each chip would actually show.
        names = sorted({d.source for d in base if d.source})
        states = [s for s in pipeline.REVIEW_STATES if any(d.state == s for d in base)]
        source_scope = pipeline.filter_drafts(base, state=status, q=q)
        state_scope = pipeline.filter_drafts(base, source=source, q=q)
        source_counts = Counter(d.source for d in source_scope if d.source)
        state_counts = Counter(d.state for d in state_scope)
        page_drafts, page_info = pipeline.paginate(drafts, page=page, per_page=per_page)
        return _page(
            render_drafts_html(
                page_drafts,
                message=message,
                private=private,
                total=len(base),
                matched=len(drafts),
                sources=[(name, source_counts.get(name, 0)) for name in names],
                statuses=[(state, state_counts.get(state, 0)) for state in states],
                selected_source=source,
                selected_status=status,
                source_total=len(source_scope),
                status_total=len(state_scope),
                page=page_info,
                scheduling=bool(post_times),
                q=q,
                sort=sort,
            )
        )

    @app.get("/review/{draft_id}", response_class=HTMLResponse)
    async def review_detail(draft_id: str, message: str = "", kind: str = "info"):
        def _load():
            draft = pipeline.get_draft(cfg, draft_id)
            if draft is None:
                return None, [], ""
            open_ids = [d.id for d in pipeline.list_drafts(cfg, pipeline.REVIEW_STATES)]
            return draft, open_ids, pipeline.dna_text(cfg)

        draft, open_ids, dna = await asyncio.to_thread(_load)
        if draft is None:
            return _page(render_message_html("Draft not found", f"No draft {draft_id!r}."), 404)
        next_id = None
        if len(open_ids) > 1 and draft_id in open_ids:
            next_id = open_ids[(open_ids.index(draft_id) + 1) % len(open_ids)]
        return _page(
            render_draft_html(
                draft,
                dna=dna,
                message=message,
                message_kind=kind,
                private=private,
                image_enabled=image_enabled and draft.state in pipeline.REVIEW_STATES,
                image_status=state["images"].get(draft_id),
                next_id=next_id,
                scheduling=bool(post_times),
                next_post=_next_post_label(),
                posting_paused=state["post_paused"],
            )
        )

    @app.post("/review/{draft_id}/publish")
    async def review_publish(draft_id: str, request: Request):
        form = await request.form()
        hashtags = form.get("hashtags")
        dry_run = str(form.get("dry_run", "")) in ("1", "true", "on", "yes")
        approve = str(form.get("approve", "")) in ("1", "true", "on", "yes")
        try:
            await asyncio.to_thread(
                pipeline.edit_draft,
                cfg,
                draft_id,
                caption=str(form.get("caption", "") or ""),
                hashtags=None if hashtags is None else str(hashtags),
                image_prompt=str(form.get("image_prompt", "") or ""),
            )
            if approve:
                # Approve & schedule: save the edits, then queue for the poster.
                await asyncio.to_thread(pipeline.approve_draft, cfg, draft_id)
                if state["post_paused"]:
                    text = (
                        "Approved — posting is paused, so it waits until you resume. "
                        "Post now sends it immediately."
                    )
                elif post_times:
                    text = (
                        f"Approved — posts at the next slot ({_next_post_label()}). "
                        "Post now sends it immediately."
                    )
                else:
                    text = "Approved — the queue is drained. Post now sends it immediately."
                return RedirectResponse(
                    f"/review/{urllib.parse.quote(draft_id)}"
                    f"?message={urllib.parse.quote(text)}&kind=success",
                    status_code=303,
                )
            result = await _run_publish(
                pipeline.publish_draft, cfg, draft_id, dry_run=dry_run
            )
        except _Draining:
            return _page(
                render_message_html(
                    "Shutting down", "The service is shutting down; try again shortly."
                ),
                503,
            )
        except ValueError as exc:
            return _page(render_message_html("Cannot publish", str(exc)), 400)
        except DestinationError as exc:
            return _page(render_message_html("Publish failed", str(exc)), 502)
        if dry_run:
            suffix = " unpublished" if private else ""
            text = (
                f"Dry run: would post{suffix} to "
                f"{[r['destination'] for r in result['results']]}."
            )
            kind = "info"
        elif result["private"]:
            ids = [r.get("permalink") or r.get("post_id") for r in result["results"]]
            text = (
                f"Posted privately (unpublished, admins only): {ids}. "
                "Draft kept in the review queue."
            )
            kind = "warning"
        else:
            parts = [
                f"{r.get('destination')}: {r.get('permalink') or r.get('post_id')}"
                for r in result["results"]
                if not r.get("skipped")
            ]
            text = "Posted " + "; ".join(parts) if parts else "Nothing to post."
            kind = "success"
        return RedirectResponse(
            f"/review/{urllib.parse.quote(draft_id)}?message={urllib.parse.quote(text)}"
            f"&kind={kind}",
            status_code=303,
        )

    @app.post("/review/{draft_id}/save")
    async def review_save(draft_id: str, request: Request):
        """Save the compose edits (caption, hashtags, image prompt). Never posts."""
        form = await request.form()
        hashtags = form.get("hashtags")
        try:
            await asyncio.to_thread(
                pipeline.edit_draft,
                cfg,
                draft_id,
                caption=str(form.get("caption", "") or ""),
                hashtags=None if hashtags is None else str(hashtags),
                image_prompt=str(form.get("image_prompt", "") or ""),
            )
        except ValueError as exc:
            return _page(render_message_html("Cannot save", str(exc)), 400)
        return RedirectResponse(
            f"/review/{urllib.parse.quote(draft_id)}"
            f"?message={urllib.parse.quote('Saved. Your edits are live.')}&kind=success",
            status_code=303,
        )

    @app.post("/review/{draft_id}/reject")
    async def review_reject(draft_id: str):
        try:
            await asyncio.to_thread(pipeline.reject_draft, cfg, draft_id)
        except ValueError as exc:
            return _page(render_message_html("Cannot reject", str(exc)), 400)
        return RedirectResponse("/review", status_code=303)

    @app.post("/review/{draft_id}/image")
    async def review_image(draft_id: str):
        """Generate a new AI image for one draft (never posts). Slow: blocks."""
        target = f"/review/{urllib.parse.quote(draft_id)}"
        try:
            result = await asyncio.to_thread(
                pipeline.generate_images, cfg, draft_ids=[draft_id], overwrite=True
            )
        except ValueError as exc:
            text, kind = str(exc), "error"
        else:
            if result["generated"]:
                text = f"Generated a new image ({result['generated']}/{result['candidates']})."
                kind = "success"
            elif result["errors"]:
                text, kind = result["errors"][0]["error"], "error"
            else:
                text, kind = "Nothing to regenerate for this draft.", "warning"
        return RedirectResponse(
            f"{target}?message={urllib.parse.quote(text)}&kind={kind}", status_code=303
        )

    # -- operator pages: publish log + status ----------------------------

    @app.get("/publish", response_class=HTMLResponse)
    async def publish_index():
        records = await asyncio.to_thread(pipeline.list_published, cfg)
        return _page(render_publish_html(records, private=private))

    @app.get("/status", response_class=HTMLResponse)
    async def status_page():
        stats = await asyncio.to_thread(pipeline.status, cfg)
        return _page(
            render_status_html(
                stats,
                refresh=_refresh_runtime(),
                scan=_scan_runtime(),
                post=_post_runtime(),
                token=_token_runtime(),
                images=_image_runtime(),
                private=private,
            )
        )

    # -- legacy paths (old bookmarks keep working) -----------------------

    @app.get("/drafts")
    async def drafts_redirect():
        return RedirectResponse("/review", status_code=307)

    @app.get("/drafts/{draft_id}")
    async def draft_redirect(draft_id: str):
        return RedirectResponse(f"/review/{urllib.parse.quote(draft_id)}", status_code=307)

    # -- JSON API for the rewriter agent (Command Code) ------------------

    @app.get("/api/drafts")
    async def api_drafts(limit: int = API_DEFAULT_LIMIT, offset: int = 0):
        """Open drafts + the DNA brief, for the rewriter. Paged via limit/offset.

        Newest first, bounded so a caller can't pull an unbounded queue in one
        request; ``total``/``has_more``/``next_offset`` let it page through.
        """
        limit = _clamp(limit, 1, API_MAX_LIMIT, API_DEFAULT_LIMIT)
        offset = max(0, offset)

        def _load():
            return pipeline.list_drafts(cfg, pipeline.OPEN_STATES), pipeline.dna_text(cfg)

        drafts, dna = await asyncio.to_thread(_load)
        total = len(drafts)
        window = drafts[offset : offset + limit]
        consumed = offset + len(window)
        return JSONResponse(
            {
                "dna": dna,
                "drafts": [d.to_dict() for d in window],
                "total": total,
                "offset": offset,
                "limit": limit,
                "returned": len(window),
                "has_more": consumed < total,
                "next_offset": consumed if consumed < total else None,
            }
        )

    @app.post("/api/drafts/{draft_id}/rewrite")
    async def api_rewrite(draft_id: str, request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
        try:
            draft = await asyncio.to_thread(pipeline.receive_rewrite, cfg, draft_id, body)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        # Every post is a photo post: fill the image in the background (only
        # when the draft has none) so the rewrite response stays fast.
        _schedule_image(draft_id)
        return JSONResponse({"draft": draft.to_dict()})

    @app.post("/api/drafts/{draft_id}/image")
    async def api_image(draft_id: str, overwrite: bool = False):
        """Generate an image for one draft, from its rewrite's image_prompt.

        Fill-only by default: a draft that already has an image (e.g. the source
        post's own cover) is left alone unless ``?overwrite=true`` is passed, so
        a rewriter batch can't clobber existing covers.
        """
        try:
            result = await asyncio.to_thread(
                pipeline.generate_images, cfg, draft_ids=[draft_id], overwrite=overwrite
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        draft = pipeline.get_draft(cfg, draft_id)
        return JSONResponse({**result, "draft": draft.to_dict() if draft else None})

    return app
