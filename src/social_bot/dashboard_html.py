"""Operator UI pages: the factory dashboard, the post queue, the published log,
and status.

Pure rendering (no network, no fastapi). `render_dashboard_html` is the single
control surface — a pipeline strip (sources -> queue -> approved -> published)
that highlights the stage needing a human, the schedulers and ledger, the cached
page feed, and what needs attention. `render_queue_html` is the **post queue**:
the approved drafts in the order they will post, and the one place that order is
set. `render_publish_html` lists the publish audit and `render_status_html` is
the human-readable view of the /api/status snapshot.
"""

from __future__ import annotations

import datetime as dt
import html

from .caption import display_title, leading_masthead
from .destinations import label_for
from .destinations import names as destination_names
from .drafts import Draft, parse_when
from .ui import badge, fmt_when, layout


def _stamp(when: dt.datetime) -> str:
    return when.astimezone().strftime("%Y-%m-%d %H:%M %Z")


def _panel(label: str, body: str, *, extra: str = "", anchor: str = "") -> str:
    """A titled panel: uppercase label head, optional right-hand pill, body.

    ``anchor`` gives the section an id, so a page can link straight to it.
    """
    ident = f' id="{html.escape(anchor)}"' if anchor else ""
    return (
        f'<section class="panel"{ident}>'
        f'<div class="panel-head"><span class="label">{html.escape(label)}</span>{extra}</div>'
        f"{body}</section>"
    )


def _kv_rows(rows: list[tuple[str, object]]) -> str:
    """A definition list of label/value rows (values are pre-escaped HTML)."""
    return (
        '<dl class="kv">'
        + "".join(
            f'<div class="kv-row"><dt>{html.escape(str(k))}</dt><dd>{v}</dd></div>' for k, v in rows
        )
        + "</dl>"
    )


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
    if runtime.get("paused"):
        return "dot-warn", "paused"
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
    when = "paused" if runtime.get("paused") else f"next {html.escape(str(nxt))}"
    return (
        '<div class="sched-row">'
        f'<span class="{dot}" aria-hidden="true"></span>'
        f'<span class="sched-name">{html.escape(name)}'
        f'<span class="small">{html.escape(state)} · last {html.escape(str(last))} · '
        f"at {html.escape(schedule)}{detail}</span></span>"
        f'<span class="sched-when">{when}</span>'
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


def _post_at_label(publish: dict) -> str:
    """The posting slots per destination ('facebook 20:00-20:30 · linkedin 14:00-14:30').

    A destination with skip days appends them ('linkedin 14:00-14:30 skips Sat, Sun'),
    so the operator sees the weekend hold on the schedule row itself.
    """
    schedule = (publish or {}).get("destination_post_at") or {}
    skips = (publish or {}).get("destination_skip_days") or {}
    if schedule:
        parts = []
        for name, slots in schedule.items():
            if not slots:
                continue
            text = f"{name} {', '.join(slots)}"
            days = skips.get(name) or []
            labels = []
            for day in days:
                try:
                    labels.append(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[int(day)])
                except (ValueError, TypeError, IndexError):
                    labels.append(str(day))
            if labels:
                text += f" (skips {', '.join(labels)})"
            parts.append(text)
        return " · ".join(parts)
    return ", ".join((publish or {}).get("post_at", []) or [])


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


def _linkedin_section(linkedin: dict | None) -> str:
    """The linkin-bot gateway status, from its ``GET /status`` (see linkedin.status).

    ``None`` renders nothing (older callers); any dict renders a panel, so the
    page degrades to "unreachable" instead of hiding the destination.
    """
    if linkedin is None:
        return ""
    base_url = str(linkedin.get("base_url") or "")
    checked = str(linkedin.get("checked_at") or "")
    if not linkedin.get("configured", True):
        rows: list[tuple[str, object]] = [
            ("Status", badge("unknown")),
            ("Gateway", html.escape(base_url or "—")),
            ("Checked", html.escape(checked or "—")),
        ]
        error = str(linkedin.get("error") or "")
        if error:
            rows.append(("Error", html.escape(error)))
        return _panel("LinkedIn", f'<div class="panel-body">{_kv_rows(rows)}</div>')
    if not linkedin.get("ok"):
        rows = [
            ("Status", badge("invalid")),
            ("Gateway", html.escape(base_url or "—")),
            ("Checked", html.escape(checked or "—")),
            ("Error", html.escape(str(linkedin.get("error") or "unknown error"))),
        ]
        return _panel("LinkedIn", f'<div class="panel-body">{_kv_rows(rows)}</div>')

    connected = linkedin.get("connected")
    if connected is True:
        state = badge("valid")
    elif connected is False:
        state = badge("invalid")
    else:
        state = badge("unknown")
    summary = str(linkedin.get("session_summary") or linkedin.get("oauth_summary") or "—")
    kill = "on" if linkedin.get("kill_switch") else "off"
    rows = [
        ("Status", state),
        ("Session", html.escape(summary)),
    ]
    check = str(linkedin.get("session_check") or "")
    if check:
        rows.append(("Session check", html.escape(check)))
    page_url = str(linkedin.get("page_url") or "")
    if page_url:
        link = f'<a href="{html.escape(page_url)}">{html.escape(page_url)}</a>'
        rows.append(("Page posts", link))
    rows += [
        ("Kill switch", html.escape(kill)),
        ("Checked", html.escape(checked or "—")),
    ]
    blocks = [f"<div>{_kv_rows(rows)}</div>"]

    caps = [c for c in (linkedin.get("caps") or []) if isinstance(c, dict)]
    if caps:

        def _num(value) -> str:
            return "—" if value is None or value == "" else str(value)

        cap_rows = [
            [
                html.escape(str(cap.get("kind") or "")),
                html.escape(_num(cap.get("sent_today"))),
                html.escape(_num(cap.get("day_remaining"))),
                html.escape(_num(cap.get("week_remaining"))),
            ]
            for cap in caps
        ]
        blocks.append(_table(["Flow", "Sent today", "Day left", "Week left"], cap_rows))

    schedule = linkedin.get("schedule") or {}
    next_run = linkedin.get("next_run") or {}
    flows = sorted(set(list(schedule.keys()) + list(next_run.keys())))
    if flows:
        sched_rows = [
            [
                html.escape(flow),
                html.escape(", ".join(schedule.get(flow) or []) or "—"),
                html.escape(str(next_run.get(flow) or "—")),
            ]
            for flow in flows
        ]
        blocks.append(_table(["Flow", "Schedule", "Next run"], sched_rows))
    return _panel("LinkedIn", f'<div class="panel-body">{"".join(blocks)}</div>')


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

    if post and post.get("paused"):
        approved_sub = "posting paused"
    elif post:
        approved_sub = f"next post {post.get('next_post') or '—'}"
    else:
        approved_sub = "ready to post"

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


def _attention(stats: dict, token: dict | None) -> str:
    """What needs a person right now. Says so explicitly when nothing does.

    Approved drafts are deliberately absent: they need no decision, and their
    order and next send belong to the Post queue tab.
    """
    drafts = stats.get("drafts", {})
    open_drafts = int(drafts.get("open", 0) or 0)
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
            '<div class="panel-body"><p class="muted">Nothing needs you right now.</p></div>',
            extra='<span class="pill"><span class="dot dot-ok"></span>all clear</span>',
        )
    return _panel(
        "Needs attention",
        '<div class="attn">' + "".join(rows) + "</div>",
        extra=f'<span class="pill">{len(rows)} item(s)</span>',
    )


# -- post queue (the Post queue tab, /queue) -----------------------------
#
# The queue is the one place the posting order is set: the approved drafts, in
# the order the poster drains them (`draft_pipeline.scheduled_queue`), with the
# draft that goes out next marked. Because this is the order that actually
# posts, the list an operator sees and the list the poster walks are the same
# list — never a second ordering rule.
#
# Reordering is progressive: drag a row, or use the row's own Top / Up / Down
# buttons, which are plain forms and work with no JavaScript at all. Every move
# comes back to this same panel.

_QUEUE_ANCHOR = "post-queue"
# Every move returns to the queue panel, so the controls share one `next` target.
_QUEUE_NEXT_URL = f"/queue#{_QUEUE_ANCHOR}"

# Drag a row to reorder the queue; the server renumbers and the page reloads to
# show the new order. The buttons on each row do the same job without it.
#
# The drop surface is the whole document, not the rows: a drop is committed
# wherever it lands (just above the first row, over the dragged row itself), so a
# drag that visibly moved a row can never silently revert on the next load.
_QUEUE_SCRIPT = """<script>
(function () {
  var list = document.getElementById('post-queue-list');
  if (!list || !window.fetch) return;
  function rows() {
    return Array.prototype.slice.call(list.querySelectorAll('.qrow-manage'));
  }
  var managed = rows();
  if (managed.length < 2) return;
  var dragged = null;
  function save() {
    var ids = rows().map(function (row) { return row.getAttribute('data-draft-id'); });
    fetch('/queue/order', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: ids })
    }).then(function (response) { return response.json(); }).then(function (data) {
      if (data && data.ok) window.location.reload();
    }).catch(function () {});
  }
  // Put the dragged row where the pointer is: into the half of the row it is over,
  // or at the end of the list when the pointer is past the last row.
  function place(event) {
    var under = document.elementFromPoint(event.clientX, event.clientY);
    var row = under && under.closest ? under.closest('.qrow-manage') : null;
    if (row) {
      if (row === dragged) return;
      var box = row.getBoundingClientRect();
      if (event.clientY < box.top + box.height / 2) list.insertBefore(dragged, row);
      else list.insertBefore(dragged, row.nextSibling);
      return;
    }
    var edge = list.getBoundingClientRect();
    if (event.clientY < edge.top) list.insertBefore(dragged, list.firstChild);
    else if (event.clientY > edge.bottom) list.appendChild(dragged);
  }
  managed.forEach(function (row) {
    row.setAttribute('draggable', 'true');
    row.addEventListener('dragstart', function (event) {
      dragged = row;
      row.classList.add('qrow-dragging');
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', row.getAttribute('data-draft-id') || '');
      }
    });
    row.addEventListener('dragend', function () {
      row.classList.remove('qrow-dragging');
      dragged = null;
    });
  });
  document.addEventListener('dragover', function (event) {
    if (!dragged) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    place(event);
  });
  document.addEventListener('drop', function (event) {
    if (!dragged) return;
    event.preventDefault();
    save();
  });
})();
</script>"""


def _queue_move_form(draft: Draft, position: int, total: int) -> str:
    """One row's order controls: Top / Up / Down, as a plain form.

    The ends are disabled rather than hidden, so the row's shape never changes.
    """
    action = html.escape(f"/queue/{draft.id}/move")
    hidden = f'<input type="hidden" name="next" value="{_QUEUE_NEXT_URL}">'
    buttons = "".join(
        f'<button type="submit" name="direction" value="{direction}" class="btn btn-sm"'
        f' aria-label="{label}"{" disabled" if blocked else ""}>{text}</button>'
        for direction, text, label, blocked in (
            ("top", "Top", "Move to the top of the queue", position <= 1),
            ("up", "Up", "Move up one place in the queue", position <= 1),
            ("down", "Down", "Move down one place in the queue", position >= total),
        )
    )
    return f'<form method="post" action="{action}">{hidden}{buttons}</form>'


def _queue_publish_forms(draft: Draft, private: bool = False) -> str:
    """One manual-post icon button per destination still pending on this draft.

    Plain forms (no JS needed): each posts this single draft to one platform
    through ``POST /queue/{id}/publish``. Icon-only (the row already names each
    destination with its pending pill above), with the platform in ``title`` /
    ``aria-label`` and in the confirm dialog. A finished destination is never
    offered again — a send cannot be undone. In private mode a Facebook send
    stays unpublished (admins only); LinkedIn has no unpublished equivalent
    and always posts publicly.
    """
    # Short brand marks; the full platform name stays in title/aria-label.
    _ICONS = {"facebook": "f", "linkedin": "in"}
    done = set(draft.posted_destinations())
    pending = [name for name in (draft.destinations or ["facebook"]) if name not in done]
    if not pending:
        return ""
    forms: list[str] = []
    for name in pending:
        label = label_for(name)
        icon = _ICONS.get(name, label[:2])
        if private and name == "facebook":
            confirm = f"Post this privately to {label} (admins only)?"
        else:
            confirm = f"Post this publicly to {label}?"
        # Labels come from the registry; still keep the JS string single-quote
        # safe so the inline confirm can never break out of its quotes.
        confirm = confirm.replace("'", "’")
        cls = "btn btn-sm"
        forms.append(
            f'<form method="post" action="/queue/{html.escape(draft.id)}/publish"'
            f" onsubmit=\"return confirm('{html.escape(confirm, quote=True)}');\">"
            f'<input type="hidden" name="next" value="{_QUEUE_NEXT_URL}">'
            f'<input type="hidden" name="destination" value="{html.escape(name)}">'
            f'<button type="submit" class="{cls}" title="Post to {html.escape(label)}"'
            f' aria-label="Post now to {html.escape(label)}">'
            f'<span aria-hidden="true">{html.escape(icon)}</span></button></form>'
        )
    return "".join(forms)


def _queue_row(
    draft: Draft, position: int, total: int, known: list[str] | None = None, private: bool = False
) -> str:
    """One queued draft: what posts, where it posts, and where it sits in the order.

    A managed row is a div wrapping the row link plus the order controls — a
    control cannot live inside an `<a>` — and carries its draft id so a drag can
    report the new order. The destination pills name the platforms this draft
    still has to reach (posted ones read as posted); the per-destination Post
    buttons send this one draft now (a human action, like Post now on
    /review/{id}). Retargeting lives on /review/{id} — the queue only reorders
    and posts.
    """
    url = html.escape(f"/review/{draft.id}")
    title = html.escape(display_title(draft.caption, draft.title or draft.id))
    if draft.image:
        thumb = (
            f'<span class="qthumb"><img src="{html.escape(draft.image)}" alt="" '
            'loading="lazy"></span>'
        )
    else:
        thumb = '<span class="qthumb empty" aria-hidden="true"></span>'

    posted = set(draft.posted_destinations())
    meta: list[str] = []
    if position == 1:
        # The row that goes out next — the same draft the poster takes first.
        meta.append('<span class="pill is-next">Next to post</span>')
    if draft.source:
        meta.append(f'<span class="badge badge-source">{html.escape(draft.source)}</span>')
    for name in draft.destinations or ["facebook"]:
        state = "posted" if name in posted else "pending"
        dot = "dot-ok" if name in posted else "dot-warn"
        meta.append(
            f'<span class="pill"><span class="dot {dot}" aria-hidden="true"></span>'
            f"{html.escape(label_for(name))} · {state}</span>"
        )
    masthead = leading_masthead(draft.caption)
    if masthead:
        meta.append(f'<span class="pill">{html.escape(masthead)}</span>')
    stamp = draft.published or draft.created_at or draft.updated_at
    shown = fmt_when(stamp)
    if shown:
        machine = parse_when(stamp)
        label = "published" if draft.published else "queued"
        if machine:  # <time datetime> must be ISO 8601, not the raw source format
            meta.append(
                f'<time datetime="{html.escape(machine.isoformat())}">'
                f"{label} {html.escape(shown)}</time>"
            )
        else:
            meta.append(f"<span>{label} {html.escape(shown)}</span>")

    body = [
        f'<span class="qtitle">{title}</span>',
        f'<span class="qmeta">{"".join(meta)}</span>',
    ]
    if draft.excerpt:
        body.append(f'<span class="qpreview">{html.escape(draft.excerpt)}</span>')

    return (
        f'<div class="qrow qrow-manage" data-draft-id="{html.escape(draft.id)}">'
        f'<a class="qrow-main" href="{url}" draggable="false">'
        f"{thumb}"
        f'<span class="qbody">{"".join(body)}</span>'
        '<span class="qgo" aria-hidden="true">›</span>'
        "</a>"
        # A div, not a span: the order controls are a <form>, which may not sit
        # inside phrasing content.
        '<div class="qmove">'
        '<span class="qgrip" role="img" aria-label="Drag to reorder" '
        'title="Drag to reorder">⠿</span>'
        f'<span class="pill">#{position} / {total}</span>'
        f"{_queue_move_form(draft, position, total)}"
        f"{_queue_publish_forms(draft, private)}"
        "</div>"
        "</div>"
    )


def _queue_summary(total: int, post: dict | None) -> str:
    """The queue page's one-liner: how much is queued, and when it goes out."""
    if post and post.get("paused"):
        return f"{total} approved · posting paused"
    if not (post and post.get("schedule")):
        return f"{total} approved · posting is manual"
    return f"{total} approved · next post {post.get('next_post') or '—'}"


def _queue_panel(queue: list[Draft], known: list[str] | None = None, private: bool = False) -> str:
    """The post queue: the approved drafts, in the order they will post.

    ``queue`` is `draft_pipeline.scheduled_queue`, so row #1 is exactly the draft
    the poster sends next. Each row carries its own manual Post buttons alongside
    the order controls; retargeting lives on /review/{id}.
    """
    total = len(queue)
    if not queue:
        return _panel(
            "Queue",
            '<div class="panel-body"><p class="muted">Nothing approved yet — drafts you '
            "approve on the <strong>Review queue</strong> tab land here, in the order they "
            'will post. <a href="/review">Open Review queue</a>.</p></div>',
            anchor=_QUEUE_ANCHOR,
        )
    rows = "".join(
        _queue_row(draft, index + 1, total, known, private) for index, draft in enumerate(queue)
    )
    # One draft needs no ordering, so the hint and the reset control stay away
    # until there is an order to set.
    foot = ""
    if total > 1:
        foot = (
            '<div class="qfoot">'
            "<span>Drag a row, or use Top / Up / Down, to set what posts first.</span>"
            '<form method="post" action="/queue/reset">'
            f'<input type="hidden" name="next" value="{_QUEUE_NEXT_URL}">'
            '<button type="submit" class="btn btn-sm btn-quiet">Reset order</button></form>'
            "</div>"
        )
    return _panel(
        "Queue",
        f'<div class="qlist" id="post-queue-list">{rows}</div>{foot}',
        anchor=_QUEUE_ANCHOR,
    )


def render_queue_html(
    queue: list[Draft],
    *,
    post: dict | None = None,
    message: str = "",
    private: bool = False,
    generated_at: dt.datetime | None = None,
    destinations: list[str] | None = None,
) -> str:
    """The post queue page: the approved drafts, in the order they will post.

    ``queue`` is `draft_pipeline.scheduled_queue` — the poster's own list — so
    row #1 is exactly the draft that posts next; the reorder controls set
    that order and each row's Post buttons send that one draft now (one
    platform per button). ``post`` is the poster's runtime, for the header's
    one-line summary of when the queue goes out. ``destinations`` is accepted
    for backward compatibility and ignored: retargeting lives on /review/{id}.
    """
    generated_at = generated_at or dt.datetime.now()
    post_control = ""
    if post and post.get("schedule"):
        post_control = (
            '<div class="cmdbar">'
            '<form method="post" action="/publish/run">'
            f'<input type="hidden" name="next" value="{_QUEUE_NEXT_URL}">'
            '<button type="submit">Post approved now</button></form>'
            "</div>"
        )
    header = (
        "<header><div><h1>Post queue</h1>"
        f'<div class="sub">{html.escape(_queue_summary(len(queue), post))} · generated '
        f"{html.escape(_stamp(generated_at))}</div></div>" + post_control + "</header>"
    )
    body = header + _queue_panel(queue, destinations or destination_names(), private)
    if queue:  # the drag-to-reorder enhancement only means anything with rows
        body += _QUEUE_SCRIPT
    return layout(
        "Social Content Factory — post queue",
        body,
        active="queue",
        message=message,
        private=private,
    )


def render_dashboard_html(
    *,
    stats: dict,
    refresh: dict,
    scan: dict,
    post: dict | None = None,
    token: dict | None = None,
    feed_section: str = "",
    feed_label: str = "",
    feed_count: int = 0,
    account_label: str = "",
    message: str = "",
    private: bool = False,
    generated_at: dt.datetime | None = None,
) -> str:
    """The single control surface: pipeline, controls, feed.

    The feed panel is platform-owned: the caller (a destination's reader) renders
    ``feed_section`` and passes ``feed_label``; when there is no reader the panel
    is omitted entirely, so the core UI never imports a platform module.

    The post queue is not here: it has its own page (``render_queue_html``) on the
    Post queue tab, so the order and the controls that set it live together.
    """
    generated_at = generated_at or dt.datetime.now()
    drafts = stats.get("drafts", {})
    published = stats.get("published", {})
    publish = stats.get("publish", {}) or {}

    post_controls = ""
    if post:
        post_controls = (
            '<form method="post" action="/publish/run">'
            '<button type="submit">Post approved now</button></form>'
        )
        if post.get("paused"):
            post_controls += (
                '<form method="post" action="/publish/resume">'
                '<button type="submit">Resume posting</button></form>'
            )
        else:
            post_controls += (
                '<form method="post" action="/publish/pause">'
                '<button type="submit">Pause posting</button></form>'
            )
    refresh_control = ""
    if feed_label:
        refresh_control = (
            '<form method="post" action="/refresh">'
            '<button type="submit">Refresh feed</button></form>'
        )
    controls = (
        '<div class="cmdbar">'
        + refresh_control
        + '<form method="post" action="/scan"><button type="submit">Scan sources</button></form>'
        + post_controls
        + "</div>"
    )
    who = html.escape(account_label) if account_label else "no destination configured"
    header = (
        "<header><div><h1>Factory</h1>"
        f'<div class="sub">{who} · generated '
        f"{html.escape(_stamp(generated_at))}</div></div>" + controls + "</header>"
    )

    if not feed_label:
        # No reader for the enabled destinations — no feed panel to show.
        feed_panel = ""
    elif not feed_section:
        feed_panel = _panel(
            feed_label,
            '<div class="panel-body"><p class="muted">No feed cached yet — click '
            "<strong>Refresh feed</strong> to load it.</p></div>",
        )
    else:
        feed_panel = _panel(
            feed_label,
            f'<div class="qlist">{feed_section}</div>',
            extra=f'<span class="pill">{feed_count} cached</span>',
        )

    schedule_rows = _run_line("Feed refresh", refresh) + _run_line("Source scan", scan)
    if post:
        schedule_rows += _run_line("Post schedule", post, _posting_detail(publish))
        if post.get("paused"):
            schedule_rows += (
                '<div class="sched-row">'
                '<span class="dot dot-warn" aria-hidden="true"></span>'
                '<span class="sched-name">Next post'
                '<span class="small">paused — resume to schedule the next post</span></span>'
                '<span class="sched-when">—</span>'
                "</div>"
            )
        else:
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

    left = '<div class="stack">' + _attention(stats, token) + feed_panel + "</div>"
    right = '<div class="stack">' + schedule_panel + ledger_panel + "</div>"
    return layout(
        "Social Content Factory — factory",
        header + _pipeline(stats, refresh, scan, post) + f'<div class="cols">{left}{right}</div>',
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
                '<div class="panel-body"><p class="muted">Nothing published yet.</p></div>',
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
        destination = str(record.get("destination", "") or "")
        permalink = str(record.get("permalink", "") or "")
        if destination == "linkedin":
            # LinkedIn's post URL is a read-back guess from the Page's posts
            # list, not the created post's id — it repeatedly points at the
            # same old post. Don't present it as the post's link.
            post_cell = '<span class="muted">posted</span>'
        else:
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
                html.escape(destination),
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
    linkedin: dict | None = None,
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
            f"{html.escape(str(s.get('url', '')))}</a>",
            html.escape(str(s.get("lang", ""))),
        ]
        for s in stats.get("sources", [])
    ]
    state_rows = [
        [html.escape(str(state)), html.escape(str(count))]
        for state, count in sorted(by_state.items())
    ]
    destination_rows = [
        [
            html.escape(str(d.get("name", ""))),
            html.escape(str(d.get("label", ""))),
            "yes" if d.get("enabled") else "no",
            "yes" if d.get("configured") else "no",
        ]
        for d in publish.get("destination_state", [])
    ]
    publish_rows = [
        ["enabled", str(bool(publish.get("enabled")))],
        ["routed", html.escape(", ".join(publish.get("destinations", [])))],
        ["min interval (days)", html.escape(str(publish.get("interval_days", "")))],
        ["interval remaining (days)", html.escape(str(publish.get("interval_remaining", "")))],
        ["approved waiting", html.escape(str(publish.get("approved", "")))],
        ["next up", html.escape(_next_draft_label(publish) or "—")],
        ["post at", html.escape(_post_at_label(publish) or "—")],
        ["post per slot", html.escape(str(publish.get("post_per_slot", "")))],
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
        + _linkedin_section(linkedin)
        + _panel("Schedules", f'<div class="sched">{schedules}</div>')
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
        + (
            _panel(
                "Destinations",
                '<div class="panel-body">'
                + _table(["Name", "Label", "Routed", "Configured"], destination_rows)
                + "</div>",
            )
            if destination_rows
            else ""
        )
        + _panel(
            "Publishing",
            '<div class="panel-body">' + _table(["Setting", "Value"], publish_rows) + "</div>",
        )
        + "</div>"
        + "</div>"
    )
    return layout("Social Content Factory — status", body, active="status", private=private)
