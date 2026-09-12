"""Operator UI pages: the factory dashboard, the published log, and status.

Pure rendering (no network, no fastapi). `render_dashboard_html` is the single
control surface — a pipeline strip (sources -> queue -> approved -> published)
that highlights the stage needing a human, the schedulers and ledger, the cached
page feed, and what needs attention — while `render_publish_html` lists the
publish audit and `render_status_html` is the human-readable view of the
/api/status snapshot.
"""

from __future__ import annotations

import datetime as dt
import html

from .feed import FeedItem
from .feed_html import render_feed_section
from .ui import badge, layout


def _stamp(when: dt.datetime) -> str:
    return when.astimezone().strftime("%Y-%m-%d %H:%M %Z")


def _panel(label: str, body: str, *, extra: str = "") -> str:
    """A titled panel: uppercase label head, optional right-hand pill, body."""
    return (
        '<section class="panel">'
        f'<div class="panel-head"><span class="label">{html.escape(label)}</span>{extra}</div>'
        f"{body}</section>"
    )


def _kv_rows(rows: list[tuple[str, object]]) -> str:
    """A definition list of label/value rows (values are pre-escaped HTML)."""
    return '<dl class="kv">' + "".join(
        f'<div class="kv-row"><dt>{html.escape(str(k))}</dt><dd>{v}</dd></div>'
        for k, v in rows
    ) + "</dl>"


def _card(num, label: str, sub: str = "") -> str:
    extra = f'<div class="sub">{html.escape(sub)}</div>' if sub else ""
    return (
        f'<div class="card"><div class="num">{html.escape(str(num))}</div>'
        f'<div class="label">{html.escape(label)}</div>{extra}</div>'
    )


def _state(runtime: dict) -> tuple[str, str]:
    """(dot class, human-readable state) for a scheduler's last run."""
    if runtime.get("busy"):
        return "dot-warn", "running now"
    if runtime.get("ok") is True:
        return "dot-ok", "last run ok"
    if runtime.get("ok") is False:
        return "dot-danger", f"last run failed — {runtime.get('error') or 'unknown error'}"
    return "dot-warn", "not run yet"


def _run_line(name: str, runtime: dict, next_item: str = "") -> str:
    """One scheduler row: state dot, last run + schedule, and the next run."""
    dot, state = _state(runtime)
    last = runtime.get("last_finished") or "—"
    nxt = runtime.get("next") or "—"
    schedule = ", ".join(str(s) for s in runtime.get("schedule") or []) or "—"
    detail = f" · next up {html.escape(next_item)}" if next_item else ""
    return (
        '<div class="sched-row">'
        f'<span class="{dot}" aria-hidden="true"></span>'
        f'<span class="sched-name">{html.escape(name)}'
        f'<span class="small">{html.escape(state)} · last {html.escape(str(last))} · '
        f"at {html.escape(schedule)}{detail}</span></span>"
        f'<span class="sched-when">next {html.escape(str(nxt))}</span>'
        "</div>"
    )


def _next_draft_label(publish: dict) -> str:
    """A short 'which draft goes next' label from the publish stats, or ''."""
    upcoming = (publish or {}).get("next_draft") or None
    if not upcoming:
        return ""
    title = str(upcoming.get("title") or "").strip()
    ident = str(upcoming.get("id") or "").strip()
    if title and ident:
        return f"{title} ({ident})"
    return title or ident


def _next_post_note(publish: dict) -> str:
    """The 'Next post' row's subtitle: when it may fire and which draft."""
    parts: list[str] = []
    remaining = int((publish or {}).get("interval_remaining") or 0)
    if remaining > 0:
        parts.append(f"in {remaining} day(s)")
    label = _next_draft_label(publish)
    if label:
        parts.append(label)
    elif int((publish or {}).get("approved") or 0) == 0:
        parts.append("nothing approved yet")
    return " · ".join(parts)


def _posting_detail(publish: dict) -> str:
    """The scheduler row's 'next up …' detail, noting an interval hold."""
    label = _next_draft_label(publish)
    remaining = int((publish or {}).get("interval_remaining") or 0)
    if remaining <= 0:
        return label
    hold = f"waits {remaining} day(s)"
    return f"{label} — {hold}" if label else hold


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _days_phrase(days: int | None) -> str:
    if days is None:
        return ""
    if days < 0:
        return f"expired {-days} day(s) ago"
    if days == 0:
        return "expires today"
    return f"in {days} day(s)"


# Background image-job states (see web.image_jobs_view) -> the word shown.
_IMAGE_STATUS_LABEL = {
    "running": "running",
    "ok": "done",
    "unchanged": "no change",
    "skipped": "skipped",
    "error": "failed",
}


def _image_section(images: dict | None, *, limit: int = 10) -> str:
    """The background image jobs: how the async post-rewrite work is going.

    `images` is web.image_jobs_view()'s payload. Returns "" when it was not
    supplied (older callers), so the section stays optional.
    """
    if images is None:
        return ""
    if not images.get("enabled"):
        return _panel(
            "Image jobs",
            '<div class="panel-body"><p class="muted">Disabled — set '
            "<code>image_gen.enabled</code> to true to generate an image for "
            "every rewrite.</p></div>",
        )
    jobs = list(images.get("jobs") or [])
    if not jobs:
        return _panel(
            "Image jobs",
            '<div class="panel-body"><p class="muted">No image jobs yet — one runs '
            "in the background after each rewrite.</p></div>",
        )
    rows: list[list[str]] = []
    for job in reversed(jobs[-limit:]):  # newest first
        status = str(job.get("status", ""))
        rows.append(
            [
                html.escape(str(job.get("draft_id", ""))),
                badge(_IMAGE_STATUS_LABEL.get(status, status or "unknown")),
                html.escape(str(job.get("error", "") or "")),
                html.escape(str(job.get("started_at", "") or "—")),
                html.escape(str(job.get("finished_at", "") or "—")),
            ]
        )
    more = "" if len(jobs) <= limit else f" (showing the latest {limit})"
    summary = (
        f'{len(jobs)} job(s) · {images.get("running", 0)} running · '
        f'{images.get("failed", 0)} failed{more}'
    )
    return _panel(
        "Image jobs",
        '<div class="panel-body">'
        + _table(["Draft", "Status", "Error", "Started", "Finished"], rows)
        + "</div>",
        extra=f'<span class="pill">{html.escape(summary)}</span>',
    )


def _token_section(token: dict | None) -> str:
    """The token's validity and expiry, from /debug_token (see api.check_token)."""
    token = token or {}
    valid = token.get("valid")
    checked = token.get("checked_at")
    error = token.get("error")

    if valid is None and checked is None and not error:
        return _panel(
            "Token", '<div class="panel-body"><p class="muted">Not checked yet.</p></div>'
        )

    if valid is True:
        state = badge("valid")
    elif valid is False:
        state = badge("invalid")
    else:
        state = badge("unknown")

    expires = token.get("expires_at")
    if expires:
        phrase = _days_phrase(token.get("expires_in_days"))
        expiry = _stamp(dt.datetime.fromisoformat(expires))
        if phrase:
            expiry += f" ({phrase})"
    elif token.get("never_expires"):
        expiry = "never"
    else:
        expiry = "—"

    rows: list[tuple[str, object]] = [
        ("Status", state),
        ("Expires", html.escape(expiry)),
        ("Checked", html.escape(str(checked or "—"))),
        ("Type", html.escape(str(token.get("type") or "—"))),
        ("Permissions", html.escape(f"{len(token.get('scopes') or [])} granted")),
    ]
    if error:
        rows.append(("Error", html.escape(str(error))))
    return _panel("Token", f'<div class="panel-body">{_kv_rows(rows)}</div>')


def _pipeline(stats: dict, refresh: dict, scan: dict, post: dict | None) -> str:
    """The four pipeline stages, left to right, with live counts.

    The queue stage is tinted because it is the one that needs a human: nothing
    publishes until someone reviews it.
    """
    drafts = stats.get("drafts", {})
    published = stats.get("published", {})
    publish = stats.get("publish", {}) or {}
    open_drafts = int(drafts.get("open", 0) or 0)
    approved = int(publish.get("approved") or 0)

    approved_sub = f"next post {post.get('next_post') or '—'}" if post else "ready to post"

    def stage(name: str, num, sub: str, *, dot: str, focus: bool = False) -> str:
        cls = "stage is-focus" if focus else "stage"
        return (
            f'<div class="{cls}">'
            f'<div class="stage-name"><span class="{dot}" aria-hidden="true"></span>'
            f"{html.escape(name)}</div>"
            f'<div class="stage-num">{html.escape(str(num))}</div>'
            f'<div class="stage-sub">{html.escape(sub)}</div>'
            "</div>"
        )

    return (
        '<div class="pipeline" role="group" aria-label="Pipeline stages">'
        + stage(
            "Sources",
            len(stats.get("sources", [])),
            f"next scan {scan.get('next') or '—'}",
            dot="dot-ok",
        )
        + stage(
            "Queue",
            open_drafts,
            f"waiting for review · {drafts.get('total', 0)} total",
            dot="dot-warn" if open_drafts else "dot-ok",
            focus=bool(open_drafts),
        )
        + stage(
            "Approved",
            approved,
            approved_sub,
            dot="dot-ok" if approved else "dot-warn",
        )
        + stage(
            "Published",
            published.get("total", 0),
            "all time",
            dot="dot-ok",
        )
        + "</div>"
    )


def _attention(
    stats: dict,
    images: dict | None,
    token: dict | None,
    *,
    post: dict | None,
) -> str:
    """What needs a person right now. Says so explicitly when nothing does."""
    drafts = stats.get("drafts", {})
    publish = stats.get("publish", {}) or {}
    open_drafts = int(drafts.get("open", 0) or 0)
    approved = int(publish.get("approved") or 0)
    rows: list[str] = []

    if open_drafts:
        rows.append(
            '<div class="attn-row">'
            f'<span class="attn-ico act" aria-hidden="true">{open_drafts}</span>'
            '<span class="attn-text"><strong>'
            f"{open_drafts} draft(s) waiting for review</strong>"
            f'<span class="small">{drafts.get("total", 0)} in the queue · '
            "nothing posts until a human approves it</span></span>"
            '<a class="btn btn-primary btn-sm" href="/review">Open queue</a>'
            "</div>"
        )
    if post and approved:
        label = _next_draft_label(publish) or "the approved queue"
        rows.append(
            '<div class="attn-row">'
            f'<span class="attn-ico" aria-hidden="true">{approved}</span>'
            '<span class="attn-text"><strong>'
            f"{approved} approved and scheduled</strong>"
            f'<span class="small">oldest first — {html.escape(label)}</span></span>'
            '<a class="btn btn-quiet btn-sm" href="/review?status=approved">View</a>'
            "</div>"
        )
    if images is not None and images.get("failed"):
        rows.append(
            '<div class="attn-row">'
            '<span class="attn-ico warn" aria-hidden="true">!</span>'
            '<span class="attn-text"><strong>'
            f"{images.get('failed')} image job(s) failed</strong>"
            '<span class="small">the draft keeps its existing image; '
            "regenerate from the draft page</span></span>"
            '<a class="btn btn-quiet btn-sm" href="/status">Inspect</a>'
            "</div>"
        )
    if token is not None and token.get("valid") is False:
        rows.append(
            '<div class="attn-row">'
            '<span class="attn-ico warn" aria-hidden="true">!</span>'
            '<span class="attn-text"><strong>Token invalid</strong>'
            f'<span class="small">{html.escape(str(token.get("error") or "see Status"))}'
            "</span></span>"
            '<a class="btn btn-quiet btn-sm" href="/status">Inspect</a>'
            "</div>"
        )

    if not rows:
        return _panel(
            "Needs attention",
            '<div class="panel-body"><p class="muted">Nothing needs you right now.'
            "</p></div>",
            extra='<span class="pill"><span class="dot dot-ok"></span>all clear</span>',
        )
    return _panel(
        "Needs attention",
        '<div class="attn">' + "".join(rows) + "</div>",
        extra=f'<span class="pill">{len(rows)} item(s)</span>',
    )


def render_dashboard_html(
    *,
    items: list[FeedItem] | None,
    stats: dict,
    refresh: dict,
    scan: dict,
    post: dict | None = None,
    images: dict | None = None,
    token: dict | None = None,
    page_id: str = "",
    page_name: str = "",
    message: str = "",
    private: bool = False,
    generated_at: dt.datetime | None = None,
) -> str:
    """The single control surface: pipeline, controls, attention, and feed."""
    generated_at = generated_at or dt.datetime.now()
    drafts = stats.get("drafts", {})
    published = stats.get("published", {})
    publish = stats.get("publish", {}) or {}

    controls = (
        '<div class="cmdbar">'
        '<form method="post" action="/refresh"><button type="submit">Refresh feed</button></form>'
        '<form method="post" action="/scan"><button type="submit">Scan sources</button></form>'
        + (
            '<form method="post" action="/publish/run">'
            '<button type="submit">Post approved now</button></form>'
            if post
            else ""
        )
        + "</div>"
    )
    header = (
        "<header><div><h1>Factory</h1>"
        f'<div class="sub">Page {html.escape(page_name or page_id or "—")} · generated '
        f"{html.escape(_stamp(generated_at))}</div></div>"
        + controls
        + "</header>"
    )

    if items is None:
        feed_panel = _panel(
            "Page feed",
            '<div class="panel-body"><p class="muted">No feed cached yet — click '
            "<strong>Refresh feed</strong> to load it.</p></div>",
        )
    else:
        feed_panel = _panel(
            "Page feed",
            f'<div class="qlist">{render_feed_section(items)}</div>',
            extra=f'<span class="pill">{len(items)} cached</span>',
        )

    schedule_rows = _run_line("Feed refresh", refresh) + _run_line("Source scan", scan)
    if post:
        schedule_rows += _run_line("Post schedule", post, _posting_detail(publish))
        schedule_rows += (
            '<div class="sched-row">'
            '<span class="dot dot-ok" aria-hidden="true"></span>'
            '<span class="sched-name">Next post'
            f'<span class="small">{html.escape(_next_post_note(publish))}</span></span>'
            f'<span class="sched-when">{html.escape(str(post.get("next_post") or "—"))}</span>'
            "</div>"
        )
    schedule_panel = _panel(
        "Schedulers",
        f'<div class="sched">{schedule_rows}</div>',
        extra=f'<span class="pill">{len(stats.get("sources", []) or [])} source(s)</span>',
    )
    ledger_panel = _panel(
        "Ledger",
        '<div class="panel-body">'
        + _kv_rows(
            [
                ("Seen items", html.escape(str(stats.get("seen", 0)))),
                ("Drafts total", html.escape(str(drafts.get("total", 0)))),
                ("Open drafts", html.escape(str(drafts.get("open", 0)))),
                ("Published", html.escape(str(published.get("total", 0)))),
                ("Min interval (days)", html.escape(str(publish.get("interval_days", "")))),
            ]
        )
        + "</div>",
    )

    left = (
        '<div class="stack">'
        + _attention(stats, images, token, post=post)
        + feed_panel
        + "</div>"
    )
    right = (
        '<div class="stack">'
        + schedule_panel
        + ledger_panel
        + _image_section(images, limit=5)
        + "</div>"
    )

    return layout(
        "Social Content Factory — factory",
        header
        + _pipeline(stats, refresh, scan, post)
        + f'<div class="cols">{left}{right}</div>',
        active="dashboard",
        message=message,
        private=private,
    )


def render_publish_html(
    records: list[dict],
    *,
    private: bool = False,
    generated_at: dt.datetime | None = None,
) -> str:
    """The publish audit log (records oldest-first, as stored)."""
    generated_at = generated_at or dt.datetime.now()
    header = (
        "<header><div><h1>Published</h1>"
        f'<div class="sub">{len(records)} post(s) · generated '
        f"{html.escape(_stamp(generated_at))}</div></div></header>"
    )
    if not records:
        return layout(
            "Social Content Factory — published",
            header
            + _panel(
                "Audit log",
                '<div class="panel-body"><p class="muted">Nothing published yet.</p>'
                "</div>",
            ),
            active="publish",
            private=private,
        )

    rows: list[list[str]] = []
    for record in reversed(records):
        source = str(record.get("source", "") or "")
        url = str(record.get("url", "") or "")
        source_cell = html.escape(source)
        if url:
            source_cell = f'<a href="{html.escape(url)}">{html.escape(source)}</a>'
        permalink = str(record.get("permalink", "") or "")
        # A send with no feed story (e.g. a photo upload) returns no post —
        # show no link rather than a bare id.
        post_cell = (
            f'<a href="{html.escape(permalink)}">{html.escape(permalink)}</a>'
            if permalink
            else ""
        )
        rows.append(
            [
                html.escape(str(record.get("posted_at", "") or "")),
                source_cell,
                html.escape(str(record.get("destination", "") or "")),
                post_cell,
            ]
        )
    return layout(
        "Social Content Factory — published",
        header
        + _panel(
            "Audit log",
            '<div class="panel-body">'
            + _table(["When", "Source", "Destination", "Post"], rows)
            + "</div>",
            extra=f'<span class="pill">{len(records)} record(s)</span>',
        ),
        active="publish",
        private=private,
    )


def render_status_html(
    stats: dict,
    *,
    refresh: dict,
    scan: dict,
    post: dict | None = None,
    token: dict | None = None,
    images: dict | None = None,
    private: bool = False,
    generated_at: dt.datetime | None = None,
) -> str:
    """Human-readable view of the /api/status snapshot plus scheduler state."""
    generated_at = generated_at or dt.datetime.now()
    drafts = stats.get("drafts", {})
    by_state = drafts.get("by_state", {})
    published = stats.get("published", {})
    publish = stats.get("publish", {})

    header = (
        "<header><div><h1>Status</h1>"
        f'<div class="sub">generated {html.escape(_stamp(generated_at))}</div></div></header>'
    )
    cards = (
        '<div class="cards">'
        + _card(drafts.get("open", 0), "Open drafts", f"{drafts.get('total', 0)} total")
        + _card(published.get("total", 0), "Published")
        + _card(stats.get("seen", 0), "Seen items")
        + "</div>"
    )

    source_rows = [
        [
            html.escape(str(s.get("name", ""))),
            html.escape(str(s.get("type", ""))),
            f'<a href="{html.escape(str(s.get("url", "")))}">'
            f'{html.escape(str(s.get("url", "")))}</a>',
            html.escape(str(s.get("lang", ""))),
        ]
        for s in stats.get("sources", [])
    ]
    state_rows = [
        [html.escape(str(state)), html.escape(str(count))]
        for state, count in sorted(by_state.items())
    ]
    publish_rows = [
        ["enabled", str(bool(publish.get("enabled")))],
        ["destinations", html.escape(", ".join(publish.get("destinations", [])))],
        ["min interval (days)", html.escape(str(publish.get("interval_days", "")))],
        ["interval remaining (days)", html.escape(str(publish.get("interval_remaining", "")))],
        ["approved waiting", html.escape(str(publish.get("approved", "")))],
        ["next up", html.escape(_next_draft_label(publish) or "—")],
        ["post at", html.escape(", ".join(publish.get("post_at", []) or []) or "—")],
        ["post per slot", html.escape(str(publish.get("post_per_slot", "")))],
        ["DNA file set", str(bool(publish.get("dna_file_set")))],
    ]

    schedules = _run_line("Feed refresh", refresh) + _run_line("Source scan", scan)
    if post:
        schedules += _run_line("Post schedule", post, _posting_detail(publish))

    body = (
        header
        + cards
        + '<div class="cols">'
        + '<div class="stack">'
        + _token_section(token)
        + _panel("Schedules", f'<div class="sched">{schedules}</div>')
        + _image_section(images)
        + _panel(
            "Sources",
            '<div class="panel-body">'
            + _table(["Name", "Type", "URL", "Lang"], source_rows)
            + "</div>",
        )
        + "</div>"
        + '<div class="stack">'
        + _panel(
            "Drafts by state",
            '<div class="panel-body">' + _table(["State", "Count"], state_rows) + "</div>",
        )
        + _panel(
            "Publishing",
            '<div class="panel-body">' + _table(["Setting", "Value"], publish_rows) + "</div>",
        )
        + "</div>"
        + "</div>"
    )
    return layout(
        "Social Content Factory — status", body, active="status", private=private
    )
