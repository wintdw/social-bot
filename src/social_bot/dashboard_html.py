"""Operator UI pages: the dashboard, the published log, and the status page.

Pure rendering (no network, no fastapi). `render_dashboard_html` is the single
control surface — feed + refresh/scan controls + queue/published counts — while
`render_publish_html` lists the publish audit and `render_status_html` is the
human-readable view of the /api/status snapshot.
"""

from __future__ import annotations

import datetime as dt
import html

from .feed import FeedItem
from .feed_html import render_feed_section
from .ui import badge, layout


def _stamp(when: dt.datetime) -> str:
    return when.astimezone().strftime("%Y-%m-%d %H:%M %Z")


def _card(num, label: str, sub: str = "") -> str:
    extra = f'<div class="sub">{html.escape(sub)}</div>' if sub else ""
    return (
        f'<div class="card"><div class="num">{html.escape(str(num))}</div>'
        f'<div class="label">{html.escape(label)}</div>{extra}</div>'
    )


def _run_line(name: str, runtime: dict) -> str:
    """One line describing a scheduler's last run and next one."""
    if runtime.get("busy"):
        state = "running now"
    elif runtime.get("ok") is True:
        state = "last run ok"
    elif runtime.get("ok") is False:
        state = f"last run failed — {runtime.get('error') or 'unknown error'}"
    else:
        state = "not run yet"
    last = runtime.get("last_finished") or "—"
    nxt = runtime.get("next") or "—"
    schedule = ", ".join(str(s) for s in runtime.get("schedule") or [])
    return (
        f'<p class="muted">{html.escape(name)}: {html.escape(state)} · '
        f"last {html.escape(str(last))} · next {html.escape(str(nxt))} · "
        f"at {html.escape(schedule)}</p>"
    )


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
        return (
            "<h2>Image jobs</h2>"
            '<p class="muted">Disabled — set <code>image_gen.enabled</code> to true '
            "to generate an image for every rewrite.</p>"
        )
    jobs = list(images.get("jobs") or [])
    if not jobs:
        return (
            "<h2>Image jobs</h2>"
            '<p class="muted">No image jobs yet — one runs in the background after '
            "each rewrite.</p>"
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
        f'<p class="muted">{len(jobs)} job(s) · {images.get("running", 0)} running · '
        f'{images.get("failed", 0)} failed{more}</p>'
    )
    return (
        "<h2>Image jobs</h2>"
        + summary
        + _table(["Draft", "Status", "Error", "Started", "Finished"], rows)
    )


def _token_section(token: dict | None) -> str:
    """The token's validity and expiry, from /debug_token (see api.check_token)."""
    token = token or {}
    valid = token.get("valid")
    checked = token.get("checked_at")
    error = token.get("error")

    if valid is None and checked is None and not error:
        return '<h2>Token</h2><p class="muted">Not checked yet.</p>'

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

    rows = [
        ["Status", state],
        ["Expires", html.escape(expiry)],
        ["Checked", html.escape(str(checked or "—"))],
        ["Type", html.escape(str(token.get("type") or "—"))],
        ["Permissions", html.escape(f"{len(token.get('scopes') or [])} granted")],
    ]
    if error:
        rows.append(["Error", html.escape(str(error))])
    return "<h2>Token</h2>" + _table(["Field", "Value"], rows)


def render_dashboard_html(
    *,
    items: list[FeedItem] | None,
    stats: dict,
    refresh: dict,
    scan: dict,
    images: dict | None = None,
    page_id: str = "",
    message: str = "",
    private: bool = False,
    generated_at: dt.datetime | None = None,
) -> str:
    """The single control surface: controls, counts, scheduler state, and feed."""
    generated_at = generated_at or dt.datetime.now()
    drafts = stats.get("drafts", {})
    published = stats.get("published", {})

    controls = (
        '<div class="controls">'
        '<form method="post" action="/refresh"><button type="submit">Refresh feed</button></form>'
        '<form method="post" action="/scan"><button type="submit">Scan sources</button></form>'
        f'<span class="muted">Page {html.escape(page_id or "—")}</span>'
        "</div>"
    )
    cards = (
        '<div class="cards">'
        + _card(drafts.get("open", 0), "Open drafts", f"{drafts.get('total', 0)} total")
        + _card(published.get("total", 0), "Published", f"{published.get('private', 0)} private")
        + _card(stats.get("seen", 0), "Seen items")
        + _card(refresh.get("next", "—"), "Next refresh")
        + _card(scan.get("next", "—"), "Next scan")
        + "</div>"
    )
    runs = _run_line("Feed refresh", refresh) + _run_line("Source scan", scan)

    if items is None:
        feed = (
            "<h2>Page feed</h2>"
            '<p class="muted">No feed cached yet — click <strong>Refresh feed</strong> '
            "to load it.</p>"
        )
    else:
        feed = "<h2>Page feed</h2>" + render_feed_section(items)

    header = (
        "<header><h1>Dashboard</h1>"
        f'<div class="meta">generated {html.escape(_stamp(generated_at))}</div></header>'
    )
    return layout(
        "social-bot — dashboard",
        header + controls + cards + runs + _image_section(images, limit=5) + feed,
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
    public = sum(1 for r in records if not r.get("private"))
    header = (
        "<header><h1>Published</h1>"
        f'<div class="meta">{len(records)} post(s) · {public} public · '
        f'{len(records) - public} private · generated {html.escape(_stamp(generated_at))}</div>'
        "</header>"
    )
    if not records:
        return layout(
            "social-bot — published",
            header + '<p class="muted">Nothing published yet.</p>',
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
        # Only a public post has a permalink; a private/unpublished send (e.g. a
        # photo upload) returns no post — show no link rather than a bare id.
        post_cell = (
            f'<a href="{html.escape(permalink)}">{html.escape(permalink)}</a>'
            if permalink
            else ""
        )
        visibility = "private" if record.get("private") else "public"
        rows.append(
            [
                html.escape(str(record.get("posted_at", "") or "")),
                source_cell,
                html.escape(str(record.get("destination", "") or "")),
                post_cell,
                badge(visibility),
            ]
        )
    return layout(
        "social-bot — published",
        header + _table(["When", "Source", "Destination", "Post", "Visibility"], rows),
        active="publish",
        private=private,
    )


def render_status_html(
    stats: dict,
    *,
    refresh: dict,
    scan: dict,
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
        "<header><h1>Status</h1>"
        f'<div class="meta">generated {html.escape(_stamp(generated_at))}</div></header>'
    )
    cards = (
        '<div class="cards">'
        + _card(drafts.get("open", 0), "Open drafts", f"{drafts.get('total', 0)} total")
        + _card(published.get("total", 0), "Published", f"{published.get('private', 0)} private")
        + _card(stats.get("seen", 0), "Seen items")
        + "</div>"
    )

    source_rows = [
        [
            html.escape(str(s.get("name", ""))),
            html.escape(str(s.get("type", ""))),
            f'<a href="{html.escape(str(s.get("url", "")))}">{html.escape(str(s.get("url", "")))}</a>',
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
        ["private mode", str(bool(publish.get("private")))],
        ["destinations", html.escape(", ".join(publish.get("destinations", [])))],
        ["max per day", html.escape(str(publish.get("max_per_day", "")))],
        ["DNA file set", str(bool(publish.get("dna_file_set")))],
    ]

    body = (
        header
        + cards
        + _token_section(token)
        + "<h2>Schedules</h2>"
        + _run_line("Feed refresh", refresh)
        + _run_line("Source scan", scan)
        + _image_section(images)
        + "<h2>Sources</h2>"
        + _table(["Name", "Type", "URL", "Lang"], source_rows)
        + "<h2>Drafts by state</h2>"
        + _table(["State", "Count"], state_rows)
        + "<h2>Publishing</h2>"
        + _table(["Setting", "Value"], publish_rows)
    )
    return layout(
        "social-bot — status", body, active="status", private=private
    )
