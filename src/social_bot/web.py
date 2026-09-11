"""FastAPI operator UI, JSON API, and in-process schedulers.

`serve` is a long-lived process with one operator UI: the dashboard at `/`
(controls + feed + counts), the review queue at `/review` (fed by the content
pipeline), the publish log at `/publish`, and a status page at `/status`. It runs
two container-local schedules — a feed refresh (`--refresh-at`) and a source scan
(`--scan-at`). Scanning only *queues* drafts; publishing happens solely when a
human submits the review page's approve action, never on a timer. fastapi is an
optional [server] extra, imported defensively so this module still loads without it.

The scheduling/time helpers are pure (injectable `now`) so they are testable
without fastapi installed.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import sys
import traceback
import urllib.parse
from collections import Counter

from . import draft_pipeline as pipeline
from .api import ApiError, check_token
from .config import load_config
from .dashboard_html import render_dashboard_html, render_publish_html, render_status_html
from .draft_html import render_draft_html, render_drafts_html, render_message_html
from .publishers import PublisherError
from .refresh import load_cached_items, refresh_feed

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


def _parse_hhmm(text: str) -> tuple[int, int]:
    """Parse "HH:MM" into (hour, minute); raise ValueError on anything else."""
    hh, _, mm = str(text).partition(":")
    if not (hh.isdigit() and mm.isdigit()):
        raise ValueError(f"invalid time {text!r}: expected HH:MM")
    hour, minute = int(hh), int(mm)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid time {text!r}: expected HH:MM")
    return hour, minute


def _occurrence(hhmm: str, now: dt.datetime) -> dt.datetime:
    hour, minute = _parse_hhmm(hhmm)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _next_occurrence(hhmm: str, now: dt.datetime) -> dt.datetime:
    occurrence = _occurrence(hhmm, now)
    if occurrence <= now:
        occurrence += dt.timedelta(days=1)
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


def current_slot(times: list[str], now: dt.datetime | None = None) -> str | None:
    """The most recent scheduled occurrence at/before now, as 'YYYY-MM-DD HH:MM'."""
    now = now or dt.datetime.now()
    latest: dt.datetime | None = None
    for hhmm in times:
        occurrence = _occurrence(hhmm, now)
        if occurrence > now:
            occurrence -= dt.timedelta(days=1)
        if latest is None or occurrence > latest:
            latest = occurrence
    return latest.strftime("%Y-%m-%d %H:%M") if latest else None


def _iso(value: dt.datetime | None) -> str | None:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else None


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
):
    """Build the FastAPI app: cached feed at `/`, draft review UI, schedulers."""
    if FastAPI is None:
        raise RuntimeError(
            "serve needs the [server] extra: pip install 'social-bot[server]'"
        )

    cfg = load_config(config_path)
    times = list(refresh_at or DEFAULT_REFRESH_TIMES)
    scan_times = list(scan_at or cfg.get("blog", {}).get("scan_at") or DEFAULT_SCAN_TIMES)
    private = bool(cfg.get("publish", {}).get("private", False))
    image_enabled = bool(pipeline.image_gen_config(cfg).get("enabled"))

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
        "token_status": None,
        "token_error": None,
        "token_checked": None,
        "token_busy": False,
        "image_lock": asyncio.Lock(),
        "image_tasks": set(),
        # Per-draft status of the background image job, so an operator can tell
        # "running", "failed" and "done" apart — the draft's own `image` field
        # only ever shows the end state (present or not).
        "images": {},
    }

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
        if state["token_busy"]:
            return
        state["token_busy"] = True
        try:
            status = await asyncio.to_thread(check_token, cfg)
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
        # A refresh needs a working token — refresh the token readout with it.
        await _token_job(f"after refresh ({reason})")

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
            except Exception as exc:  # a failed scan must never kill the app
                state["scan_ok"] = False
                state["scan_error"] = str(exc)
                print(f"[web] scan failed (reason={reason}): {exc}", file=sys.stderr, flush=True)
                traceback.print_exc()
            finally:
                state["scan_finished"] = dt.datetime.now()
                state["scan_busy"] = False

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

    def _schedule_image(draft_id: str) -> None:
        """Queue a background image generation for a just-rewritten draft."""
        if not pipeline.image_gen_config(cfg).get("enabled"):
            return
        task = asyncio.create_task(_image_job(draft_id))
        state["image_tasks"].add(task)
        task.add_done_callback(state["image_tasks"].discard)

    @contextlib.asynccontextmanager
    async def _lifespan(app):
        tasks = [
            asyncio.create_task(_scheduler_loop()),
            asyncio.create_task(_scanner_loop()),
            asyncio.create_task(_token_loop()),
        ]
        try:
            yield
        finally:
            for task in [*tasks, *state["image_tasks"]]:
                task.cancel()
            for task in [*tasks, *state["image_tasks"]]:
                with contextlib.suppress(asyncio.CancelledError):
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

    def _image_runtime() -> dict:
        """Background image jobs, newest last — how /api/status reports them."""
        return image_jobs_view(image_enabled, state["images"])

    def _page(markup: str, status_code: int = 200) -> HTMLResponse:
        return HTMLResponse(
            markup, status_code=status_code, headers={"Cache-Control": "no-cache"}
        )

    @app.get("/", response_class=HTMLResponse)
    async def index(message: str = ""):
        """The operator dashboard: refresh/scan controls, counts, and feed."""
        return _page(
            render_dashboard_html(
                items=load_cached_items(cfg),
                page_id=str(cfg["graph"].get("page_id") or ""),
                stats=pipeline.status(cfg),
                refresh=_refresh_runtime(),
                scan=_scan_runtime(),
                images=_image_runtime(),
                message=message,
                private=private,
            )
        )

    @app.get("/health")
    async def health():
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
                "open_drafts": len(pipeline.list_drafts(cfg, pipeline.OPEN_STATES)),
            }
        )

    @app.get("/api/status")
    async def api_status():
        """A full pipeline snapshot: sources, drafts by state, posted, schedules."""
        return JSONResponse(
            {
                "generated_at": dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                **pipeline.status(cfg),
                "scan": _scan_runtime(),
                "refresh": _refresh_runtime(),
                "token": _token_runtime(),
                "images": _image_runtime(),
            }
        )

    @app.post("/refresh")
    async def refresh_now():
        if state["busy"]:
            return JSONResponse(
                {"started": False, "reason": "refresh already running"}, status_code=409
            )
        state["last_slot"] = current_slot(times)
        asyncio.create_task(_refresh_job("manual"))
        return JSONResponse({"started": True})

    @app.post("/scan")
    async def scan_now(request: Request):
        """Trigger a source scan now. Never posts — it only queues drafts."""
        wants_html = "text/html" in request.headers.get("accept", "")
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
        asyncio.create_task(_scan_job("manual"))
        if wants_html:
            return RedirectResponse(
                f"/review?message={urllib.parse.quote('Scan started — refresh shortly')}",
                status_code=303,
            )
        return JSONResponse({"started": True})

    # -- review queue (human-gated publishing) ---------------------------

    @app.get("/review", response_class=HTMLResponse)
    async def review_index(message: str = "", source: str = "", status: str = ""):
        base = pipeline.list_drafts(cfg, pipeline.OPEN_STATES)
        drafts = pipeline.filter_drafts(base, source=source, state=status)
        # Keep every option visible (so the active chip never disappears) but
        # count each row within the other row's selection, so the numbers add up
        # to what clicking each chip would actually show.
        names = sorted({d.source for d in base if d.source})
        states = [s for s in pipeline.OPEN_STATES if any(d.state == s for d in base)]
        source_scope = pipeline.filter_drafts(base, state=status)
        state_scope = pipeline.filter_drafts(base, source=source)
        source_counts = Counter(d.source for d in source_scope if d.source)
        state_counts = Counter(d.state for d in state_scope)
        return _page(
            render_drafts_html(
                drafts,
                message=message,
                private=private,
                total=len(base),
                sources=[(name, source_counts.get(name, 0)) for name in names],
                statuses=[(state, state_counts.get(state, 0)) for state in states],
                selected_source=source,
                selected_status=status,
                source_total=len(source_scope),
                status_total=len(state_scope),
            )
        )

    @app.get("/review/{draft_id}", response_class=HTMLResponse)
    async def review_detail(draft_id: str, message: str = "", kind: str = "info"):
        draft = pipeline.get_draft(cfg, draft_id)
        if draft is None:
            return _page(render_message_html("Draft not found", f"No draft {draft_id!r}."), 404)
        open_ids = [d.id for d in pipeline.list_drafts(cfg, pipeline.OPEN_STATES)]
        next_id = None
        if len(open_ids) > 1 and draft_id in open_ids:
            next_id = open_ids[(open_ids.index(draft_id) + 1) % len(open_ids)]
        return _page(
            render_draft_html(
                draft,
                dna=pipeline.dna_text(cfg),
                message=message,
                message_kind=kind,
                private=private,
                image_enabled=image_enabled and draft.state in pipeline.OPEN_STATES,
                image_status=state["images"].get(draft_id),
                next_id=next_id,
            )
        )

    @app.post("/review/{draft_id}/publish")
    async def review_publish(draft_id: str, request: Request):
        form = await request.form()
        hashtags = form.get("hashtags")
        dry_run = str(form.get("dry_run", "")) in ("1", "true", "on", "yes")
        try:
            pipeline.edit_draft(
                cfg,
                draft_id,
                caption=str(form.get("caption", "") or ""),
                hashtags=None if hashtags is None else str(hashtags),
            )
            result = await asyncio.to_thread(
                pipeline.publish_draft, cfg, draft_id, dry_run=dry_run
            )
        except ValueError as exc:
            return _page(render_message_html("Cannot publish", str(exc)), 400)
        except (PublisherError, ApiError) as exc:
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
            text = f"Posted: {result['draft'].get('permalink') or result['draft'].get('post_id')}"
            kind = "success"
        return RedirectResponse(
            f"/review/{urllib.parse.quote(draft_id)}?message={urllib.parse.quote(text)}"
            f"&kind={kind}",
            status_code=303,
        )

    @app.post("/review/{draft_id}/reject")
    async def review_reject(draft_id: str):
        try:
            pipeline.reject_draft(cfg, draft_id)
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
        return _page(render_publish_html(pipeline.list_published(cfg), private=private))

    @app.get("/status", response_class=HTMLResponse)
    async def status_page():
        return _page(
            render_status_html(
                pipeline.status(cfg),
                refresh=_refresh_runtime(),
                scan=_scan_runtime(),
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
    async def api_drafts():
        drafts = pipeline.list_drafts(cfg, pipeline.OPEN_STATES)
        return JSONResponse(
            {"dna": pipeline.dna_text(cfg), "drafts": [d.to_dict() for d in drafts]}
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
            draft = pipeline.receive_rewrite(cfg, draft_id, body)
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
