"""HTML rendering of the draft review queue (pure logic, no network).

Backs the operator UI's /review pages. The overview list is render_drafts_html;
the detail page with the editable caption and approve/reject actions is
render_draft_html. All content is escaped.
"""

from __future__ import annotations

import datetime as dt
import html
import urllib.parse

from .drafts import Draft, parse_when
from .ui import badge, layout

# Human labels for the status filter chips (the badge shows the raw state).
_STATE_LABELS = {
    "extracted": "Extracted",
    "ai_draft": "AI draft",
    "approved": "Approved",
    "posted": "Posted",
    "rejected": "Rejected",
}

# Client-side enhancement for the detail page: keeps the post preview and the
# character count in sync while editing, blocks a double submit, and asks for
# confirmation before a public post. The form still works without it.
_DETAIL_SCRIPT = """<script>
(function () {
  var form = document.getElementById('publish-form');
  if (!form) return;
  var caption = document.getElementById('caption');
  var tags = document.getElementById('hashtags');
  var body = document.getElementById('preview-body');
  var tagLine = document.getElementById('preview-tags');
  var count = document.getElementById('caption-count');
  var buttons = document.querySelectorAll('button[form="publish-form"]');
  function normTags() {
    return tags.value.trim().replace(/[,\\n]+/g, ' ').replace(/\\s+/g, ' ');
  }
  function sync() {
    var text = caption.value;
    var tagText = normTags();
    body.textContent = text;
    tagLine.textContent = tagText;
    count.textContent = String(text.length + (tagText ? 2 + tagText.length : 0));
  }
  caption.addEventListener('input', sync);
  tags.addEventListener('input', sync);
  sync();
  form.addEventListener('submit', function (event) {
    if (form.dataset.submitting === '1') { event.preventDefault(); return; }
    var button = event.submitter;
    var isDry = !!button && button.name === 'dry_run';
    var isApprove = !!button && button.name === 'approve';
    if (!isDry && !isApprove && form.dataset.private !== 'true') {
      if (!window.confirm('Post this publicly to the Facebook Page?')) {
        event.preventDefault();
        return;
      }
    }
    form.dataset.submitting = '1';
    for (var i = 0; i < buttons.length; i++) {
      if (buttons[i] !== button) buttons[i].disabled = true;
    }
    if (isApprove) button.textContent = 'Approving\u2026';
    else if (button && !isDry) button.textContent = 'Posting\u2026';
  });
  var reject = document.getElementById('reject-form');
  if (reject) reject.addEventListener('submit', function (event) {
    if (!window.confirm('Reject this draft? It leaves the review queue.')) {
      event.preventDefault();
    }
  });
})();
</script>"""


def _fmt_date(value: str) -> str:
    """An item timestamp as local 'YYYY-MM-DD HH:MM'.

    Returns the raw text when unparseable — source feeds date their items in
    several formats (RSS pubDate is RFC 822, Atom is ISO 8601).
    """
    parsed = parse_when(value)
    if parsed is None:
        return str(value or "").strip()
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def _draft_card(draft: Draft) -> str:
    """One queue entry: title, badges (state/source/date), and excerpt."""
    url = html.escape(f"/review/{draft.id}")
    title = html.escape(draft.title or draft.id)
    meta = [badge(draft.state)]
    if draft.source:
        meta.append(html.escape(draft.source))
    # Show the item's own date — the one the queue is sorted by — falling back
    # to when it was queued (a source without dates still shows something).
    stamp = draft.published or draft.created_at or draft.updated_at
    label = "published" if draft.published else "queued"
    shown = _fmt_date(stamp)
    if shown:
        machine = parse_when(stamp)
        if machine:  # <time datetime> must be ISO 8601, not the raw RFC 822
            meta.append(
                f'<time datetime="{html.escape(machine.isoformat())}">'
                f"{label} {html.escape(shown)}</time>"
            )
        else:
            meta.append(f"<span>{label} {html.escape(shown)}</span>")
    parts = [
        f'<h2><a href="{url}">{title}</a></h2>',
        f'<div class="meta">{" · ".join(meta)}</div>',
    ]
    if draft.excerpt:
        parts.append(f'<p class="excerpt">{html.escape(draft.excerpt)}</p>')
    return "".join(parts)


def _review_query(
    source: str = "", status: str = "", *, page: int = 0, per_page: int = 0
) -> str:
    """The /review URL for these filters, omitting empties and page defaults."""
    params = {
        "source": source,
        "status": status,
        "page": str(page) if page and page > 1 else "",
        "per_page": str(per_page) if per_page else "",
    }
    query = urllib.parse.urlencode({key: value for key, value in params.items() if value})
    return f"/review?{query}" if query else "/review"


def _chip(label: str, href: str, *, active: bool, count: int | None = None) -> str:
    current = ' aria-current="true"' if active else ""
    cls = "chip chip-active" if active else "chip"
    num = f'<span class="count">{count}</span>' if count is not None else ""
    return f'<a class="{cls}" href="{html.escape(href)}"{current}>{html.escape(label)}{num}</a>'


def _pagination_bar(page: dict, source: str, status: str) -> str:
    """Prev/next pager for the review list, preserving the active filters."""
    pages = int(page.get("pages") or 1)
    if pages <= 1:
        return ""
    per_page = int(page.get("per_page") or 0)
    current = int(page.get("page") or 1)
    chips: list[str] = []
    if page.get("has_prev"):
        chips.append(
            _chip(
                "← Newer",
                _review_query(source, status, page=current - 1, per_page=per_page),
                active=False,
            )
        )
    chips.append(f'<span class="chip chip-active">Page {current} / {pages}</span>')
    if page.get("has_next"):
        chips.append(
            _chip(
                "Older →",
                _review_query(source, status, page=current + 1, per_page=per_page),
                active=False,
            )
        )
    return (
        '<div class="filter-row"><span class="filter-label">Page</span>'
        + "".join(chips)
        + "</div>"
    )


def _filter_bar(
    sources: list[tuple[str, int]],
    statuses: list[tuple[str, int]],
    selected_source: str,
    selected_status: str,
    source_total: int,
    status_total: int,
) -> str:
    """Source / Status filter chips (plain links, so they work without JS)."""
    if not sources and not statuses:
        return ""
    rows: list[str] = []
    if statuses:
        chips = [
            _chip("All", _review_query(selected_source), active=not selected_status, count=status_total)
        ]
        chips += [
            _chip(
                _STATE_LABELS.get(state, state),
                _review_query(selected_source, state),
                active=state == selected_status,
                count=count,
            )
            for state, count in statuses
        ]
        rows.append(
            '<div class="filter-row"><span class="filter-label">Status</span>'
            + "".join(chips)
            + "</div>"
        )
    if sources:
        chips = [
            _chip("All", _review_query(status=selected_status), active=not selected_source, count=source_total)
        ]
        chips += [
            _chip(
                name,
                _review_query(name, selected_status),
                active=name == selected_source,
                count=count,
            )
            for name, count in sources
        ]
        rows.append(
            '<div class="filter-row"><span class="filter-label">Source</span>'
            + "".join(chips)
            + "</div>"
        )
    return '<div class="filters">' + "".join(rows) + "</div>"


def render_drafts_html(
    drafts: list[Draft],
    *,
    message: str = "",
    private: bool = False,
    generated_at: dt.datetime | None = None,
    total: int | None = None,
    matched: int | None = None,
    sources: list[tuple[str, int]] = (),
    statuses: list[tuple[str, int]] = (),
    selected_source: str = "",
    selected_status: str = "",
    source_total: int | None = None,
    status_total: int | None = None,
    page: dict | None = None,
    scheduling: bool = False,
) -> str:
    """Render the draft queue as a standalone HTML list page.

    ``drafts`` is the (already filtered, newest-first) *page* to show. ``sources``
    and ``statuses`` are the ``(value, count)`` filter choices, computed by the
    caller against the *other* active filter, with ``source_total`` /
    ``status_total`` the count each row's "All" chip should show; ``total`` is
    the unfiltered queue size and ``matched`` the count matching the filters
    (defaults to the page size), so the header can read "3 of 12 open draft(s)".
    ``page`` is ``draft_pipeline.paginate``'s metadata (prev/next pager) or None.
    """
    generated_at = generated_at or dt.datetime.now()
    matched = len(drafts) if matched is None else matched
    total = matched if total is None else total
    source_total = total if source_total is None else source_total
    status_total = total if status_total is None else status_total
    filtered = total != matched
    count_text = (
        f"{matched} of {total} open draft(s)" if filtered else f"{matched} open draft(s)"
    )
    header = (
        "<header>"
        "<h1>Review</h1>"
        f'<div class="meta">{count_text} · generated '
        f"{html.escape(generated_at.astimezone().strftime('%Y-%m-%d %H:%M %Z'))}</div>"
        '<form class="toolbar" method="post" action="/scan">'
        '<button type="submit">Scan sources now</button>'
        '<span class="muted">fetch new items from the source feeds</span>'
        "</form>"
        + (
            '<form class="toolbar" method="post" action="/publish/run">'
            '<button type="submit">Post approved now</button>'
            '<span class="muted">post the approved queue without waiting for a slot</span>'
            "</form>"
            if scheduling
            else ""
        )
        + "</header>"
    )
    filters = _filter_bar(
        sources,
        statuses,
        selected_source,
        selected_status,
        source_total,
        status_total,
    )
    pager = _pagination_bar(page, selected_source, selected_status) if page else ""
    if not drafts:
        if filtered:
            body = (
                '<p class="muted">No drafts match this filter. '
                '<a href="/review">Clear filters</a>.</p>'
            )
        else:
            body = (
                '<p class="muted">No open drafts. Click <strong>Scan sources now</strong> '
                "(or wait for the scheduled scan).</p>"
            )
    else:
        body = "".join(f"<article>{_draft_card(draft)}</article>" for draft in drafts)

    return layout(
        "social-bot — review",
        header + filters + pager + body,
        active="review",
        message=message,
        private=private,
    )


def render_draft_html(
    draft: Draft,
    *,
    dna: str = "",
    message: str = "",
    message_kind: str = "info",
    private: bool = False,
    image_enabled: bool = False,
    image_status: dict | None = None,
    generated_at: dt.datetime | None = None,
    next_id: str | None = None,
    scheduling: bool = False,
    next_post: str = "",
) -> str:
    """Render one draft: the post it will create, its source, and the actions."""
    title = html.escape(draft.title or draft.id)
    meta_bits = [badge(draft.state)]
    if draft.source:
        meta_bits.append(f"<span>{html.escape(draft.source)}</span>")
    if draft.published:
        meta_bits.append(f"<span>· {html.escape(draft.published)}</span>")
    next_link = ""
    if next_id:
        next_link = (
            f'<a class="next" href="/review/{html.escape(next_id)}">Next draft →</a>'
        )
    header = (
        "<header>"
        '<a class="back" href="/review">← Review queue</a>'
        f"<h1>{title}</h1>"
        f'<div class="meta head-meta">{"".join(meta_bits)}{next_link}</div>'
        "</header>"
    )

    media = ""
    if draft.image:
        alt = html.escape(draft.alt_text or draft.title or "Post image")
        media = (
            '<figure class="post-media">'
            f'<img src="{html.escape(draft.image)}" alt="{alt}" loading="lazy">'
            "</figure>"
        )

    # The image is generated in the background after a rewrite, so say whether
    # it is still coming, failed, or was never started — "no image" alone is
    # ambiguous. Only shown while the draft still has no image.
    image_note = ""
    if not draft.image:
        status = (image_status or {}).get("status")
        if status == "running":
            image_note = (
                '<p class="muted">Generating the image in the background… '
                "reload in a moment.</p>"
            )
        elif status == "error":
            detail = html.escape(str((image_status or {}).get("error") or "unknown error"))
            image_note = (
                '<div class="notice notice-error">'
                f"Image generation failed: {detail}</div>"
            )
        else:
            hint = (
                ' Use “Generate image” below.'
                if image_enabled
                else " Run `blog image --missing-only`, or the scheduled rewrite will fill it."
            )
            image_note = f'<p class="muted">No image yet — every post is a photo post.{hint}</p>'

    caption = html.escape(draft.caption or "")
    tags = html.escape(" ".join(draft.hashtags))
    action = html.escape(f"/review/{draft.id}")

    form = (
        f'<form id="publish-form" class="form-block" method="post" action="{action}/publish"'
        f' data-private="{"true" if private else "false"}">'
        '<div class="field"><label for="caption">Caption</label>'
        f'<textarea id="caption" name="caption" lang="vi">{caption}</textarea>'
        '<div class="field-hint"><span id="caption-count">'
        f"{len(draft.post_text)}</span> characters posted (caption + hashtags)"
        "</div></div>"
        '<div class="field"><label for="hashtags">Hashtags</label>'
        f'<input type="text" id="hashtags" name="hashtags" value="{tags}">'
        '<div class="field-hint">Appended to the caption when posted. '
        "Space or comma separated.</div></div>"
        "</form>"
    )

    preview = (
        '<div class="fb-preview">'
        f'<div class="body" id="preview-body" lang="vi">{caption}</div>'
        f'<div class="tags" id="preview-tags">{tags}</div>'
        "</div>"
        '<p class="field-hint">Preview of the exact text that posts. Facebook shows '
        "roughly the first two lines before “See more”.</p>"
    )

    primary = "Publish privately" if private else "Post publicly"
    target = (
        "Private mode: posted unpublished, visible to page admins only."
        if private
        else "This publishes to the Facebook Page."
    )
    image_button = ""
    if image_enabled:
        label = "Regenerate image" if draft.image else "Generate image"
        image_button = (
            f'<form id="image-form" method="post" action="{action}/image">'
            f'<button type="submit" class="btn-quiet">{label}</button></form>'
        )
    # Timed posting: a human approves here, the serve scheduler posts later.
    # The button submits the caption form too, so edits are saved with the
    # approval instead of being silently dropped. Only an ai_draft can approve.
    approve_button = ""
    when = f"the next slot ({next_post})" if next_post else "the next slot"
    if scheduling and draft.state == "ai_draft":
        approve_button = (
            '<button type="submit" form="publish-form" name="approve" value="1" '
            'class="btn-quiet">Approve &amp; schedule</button>'
        )
    action_bar = (
        '<div class="action-bar">'
        f'<button type="submit" form="publish-form" class="btn-primary">{primary}</button>'
        '<button type="submit" form="publish-form" name="dry_run" value="1" '
        'class="btn-quiet">Dry run</button>'
        f"{approve_button}"
        f"{image_button}"
        f'<span class="muted">{target}</span>'
        '<span class="spacer"></span>'
        f'<form id="reject-form" method="post" action="{action}/reject">'
        '<button type="submit" class="btn-danger">Reject</button></form>'
        "</div>"
    )

    schedule_note = ""
    if scheduling and draft.state == "approved":
        schedule_note = (
            f'<p class="field-hint">Approved — waiting for {html.escape(when)}. '
            "Use Post now to send it immediately.</p>"
        )
    elif scheduling and draft.state == "ai_draft":
        schedule_note = (
            f'<p class="field-hint">Approve &amp; schedule queues this for '
            f"{html.escape(when)}; Post now sends it immediately.</p>"
        )

    posted = ""
    if draft.post_id:
        posted = (
            f'<p class="muted">Already posted: '
            f"{html.escape(draft.permalink or draft.post_id)}</p>"
        )

    post_panel = (
        '<main class="panel">'
        + media
        + image_note
        + form
        + preview
        + action_bar
        + schedule_note
        + posted
        + "</main>"
    )

    rail_parts = ["<h2>Source</h2>"]
    if draft.url:
        rail_parts.append(
            f'<p class="source-link"><a href="{html.escape(draft.url)}">'
            f"{html.escape(draft.url)}</a></p>"
        )
    if draft.published:
        rail_parts.append(f'<p class="meta">Published {html.escape(draft.published)}</p>')
    if draft.excerpt:
        rail_parts.append(f'<p class="excerpt">{html.escape(draft.excerpt)}</p>')
    if draft.commentary:
        rail_parts.append(f"<h3>Rewriter notes</h3><p>{html.escape(draft.commentary)}</p>")
    if draft.cta:
        rail_parts.append(
            f'<h3>CTA (review only, not posted)</h3>'
            f'<p class="muted">{html.escape(draft.cta)}</p>'
        )
    if draft.alt_text:
        rail_parts.append(
            f"<h3>Image alt text</h3><p class=\"muted\">{html.escape(draft.alt_text)}</p>"
        )
    rail = '<aside class="panel rail">' + "".join(rail_parts) + "</aside>"

    tail: list[str] = []
    if dna:
        tail.append(
            '<details class="dna"><summary>Atento DNA: brand voice</summary>'
            f"<pre>{html.escape(dna)}</pre></details>"
        )
    tail.append(
        '<p class="muted">Publishing is human-gated: only the buttons here send anything.</p>'
    )

    body = (
        header
        + f'<div class="detail-grid">{post_panel}{rail}</div>'
        + "".join(tail)
        + _DETAIL_SCRIPT
    )
    return layout(
        f"social-bot — {draft.id}",
        body,
        active="review",
        message=message,
        private=private,
        kind=message_kind,
    )


def render_message_html(title: str, message: str) -> str:
    """A tiny standalone notice page (used for errors / not-found)."""
    body = (
        f"<h1>{html.escape(title)}</h1>\n<p>{html.escape(message)}</p>\n"
        '<p><a class="btn" href="/review">Back to review</a></p>'
    )
    return layout(title, body, active="")
