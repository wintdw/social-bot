"""HTML rendering of the draft review queue (pure logic, no network).

Backs the operator UI's /review pages. The overview list is render_drafts_html;
the detail page with the editable caption and approve/reject actions is
render_draft_html. All content is escaped.

The queue rows are scannable: a thumbnail, the state badge, the source, the
series masthead, the item's own date, and a one-line caption preview. A row is
titled by the caption's hook — the rule shared with the feed in `caption.py` —
falling back to the source's own title while the draft is still unwritten. The
detail page reads as a production sheet — image hero, editable caption, a live
Facebook-style preview, a pipeline stepper, and one clearly primary action.
"""

from __future__ import annotations

import datetime as dt
import html
import urllib.parse

from .caption import display_title, leading_masthead
from .destinations import label_for, labels_for
from .drafts import Draft, parse_when
from .ui import BRAND_EYEBROW, badge, layout

# Human labels for the status filter chips (the badge shows the raw state).
_STATE_LABELS = {
    "extracted": "Extracted",
    "ai_draft": "AI draft",
    "approved": "Approved",
    "posted": "Posted",
    "rejected": "Rejected",
}

# The pipeline stages a draft moves through, in order.
_PIPELINE_STEPS = (("extracted", "Extracted"), ("ai_draft", "AI draft"),
                   ("approved", "Approved"), ("posted", "Posted"))

# Sort orders offered on the queue. The default is the queue's own order.
_SORTS = (("newest", "Newest first"), ("oldest", "Oldest first"))

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
    var isApprove = !!button && button.name === 'approve';
    var isSave = !!button && button.name === 'save';
    if (!isApprove && !isSave && form.dataset.private !== 'true') {
      if (!window.confirm('Post this publicly to __DEST__?')) {
        event.preventDefault();
        return;
      }
    }
    form.dataset.submitting = '1';
    for (var i = 0; i < buttons.length; i++) {
      if (buttons[i] !== button) buttons[i].disabled = true;
    }
    if (isApprove) button.textContent = 'Approving\u2026';
    else if (isSave) button.textContent = 'Saving\u2026';
    else if (button) button.textContent = 'Posting\u2026';
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
    """One queue row: thumbnail, title, state/source/date, caption preview."""
    url = html.escape(f"/review/{draft.id}")
    title = html.escape(display_title(draft.caption, draft.title or draft.id))
    if draft.image:
        thumb = (
            f'<span class="qthumb"><img src="{html.escape(draft.image)}" alt="" '
            'loading="lazy"></span>'
        )
    else:
        thumb = '<span class="qthumb empty" aria-hidden="true"></span>'

    meta = [badge(draft.state)]
    if draft.source:
        meta.append(f'<span class="badge badge-source">{html.escape(draft.source)}</span>')
    masthead = leading_masthead(draft.caption)
    if masthead:
        meta.append(f'<span class="pill">{html.escape(masthead)}</span>')
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

    body = [
        f'<span class="qtitle">{title}</span>',
        f'<span class="qmeta">{"".join(meta)}</span>',
    ]
    if draft.excerpt:
        body.append(f'<span class="qpreview">{html.escape(draft.excerpt)}</span>')

    return (
        f'<a class="qrow" href="{url}">'
        f"{thumb}"
        f'<span class="qbody">{"".join(body)}</span>'
        '<span class="qgo" aria-hidden="true">›</span>'
        "</a>"
    )


def _review_query(
    source: str = "",
    status: str = "",
    *,
    q: str = "",
    sort: str = "",
    page: int = 0,
    per_page: int = 0,
) -> str:
    """The /review URL for these filters, omitting empties and page defaults."""
    params = {
        "source": source,
        "status": status,
        "q": q,
        "sort": sort,
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


def _segment(label: str, href: str, *, active: bool, count: int | None = None) -> str:
    """One option in the status segmented control (a plain link, no JS)."""
    current = ' aria-current="true"' if active else ""
    num = f'<span class="count">{count}</span>' if count is not None else ""
    return (
        f'<a class="seg-item" href="{html.escape(href)}"{current}>'
        f"{html.escape(label)}{num}</a>"
    )


def _pagination_bar(
    page: dict, source: str, status: str, *, q: str = "", sort: str = ""
) -> str:
    """Prev/next pager for the review list, preserving the active filters."""
    pages = int(page.get("pages") or 1)
    if pages <= 1:
        return ""
    per_page = int(page.get("per_page") or 0)
    total = int(page.get("total") or 0)
    current = int(page.get("page") or 1)
    first = (current - 1) * per_page + 1
    last = min(current * per_page, total)
    nav: list[str] = []
    if page.get("has_prev"):
        nav.append(
            f'<a class="btn btn-sm" href="{html.escape(_review_query(source, status, q=q, sort=sort, page=current - 1, per_page=per_page))}">← Newer</a>'
        )
    nav.append(f'<span class="pill">Page {current} / {pages}</span>')
    if page.get("has_next"):
        nav.append(
            f'<a class="btn btn-sm" href="{html.escape(_review_query(source, status, q=q, sort=sort, page=current + 1, per_page=per_page))}">Older →</a>'
        )
    return (
        f'<div class="pager"><span>Showing {first}–{last} / {total}</span>'
        f'<span class="cmdbar">{"".join(nav)}</span></div>'
    )


def _filter_bar(
    sources: list[tuple[str, int]],
    statuses: list[tuple[str, int]],
    selected_source: str,
    selected_status: str,
    source_total: int,
    status_total: int,
    *,
    q: str = "",
    sort: str = "",
) -> str:
    """Status as a segmented control, source as chips (plain links, no JS)."""
    if not sources and not statuses:
        return ""
    rows: list[str] = []
    if statuses:
        segs = [
            _segment(
                "All",
                _review_query(selected_source, q=q, sort=sort),
                active=not selected_status,
                count=status_total,
            )
        ]
        segs += [
            _segment(
                _STATE_LABELS.get(state, state),
                _review_query(selected_source, state, q=q, sort=sort),
                active=state == selected_status,
                count=count,
            )
            for state, count in statuses
        ]
        rows.append(
            '<div class="filter-row"><span class="filter-label">Status</span>'
            f'<span class="seg">{"".join(segs)}</span></div>'
        )
    if sources:
        chips = [
            _chip(
                "All",
                _review_query(status=selected_status, q=q, sort=sort),
                active=not selected_source,
                count=source_total,
            )
        ]
        chips += [
            _chip(
                name,
                _review_query(name, selected_status, q=q, sort=sort),
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


def _search_form(
    selected_source: str,
    selected_status: str,
    q: str,
    sort: str,
    per_page: int,
) -> str:
    """Search + sort as a plain GET form, so it works without JS."""
    hidden = ""
    for name, value in (("source", selected_source), ("status", selected_status)):
        if value:
            hidden += f'<input type="hidden" name="{name}" value="{html.escape(value)}">'
    if per_page:
        hidden += f'<input type="hidden" name="per_page" value="{per_page}">'
    options = "".join(
        f'<option value="{html.escape(value)}"'
        f'{" selected" if value == (sort or "newest") else ""}>'
        f"{html.escape(label)}</option>"
        for value, label in _SORTS
    )
    return (
        '<form class="search-form" method="get" action="/review">'
        f"{hidden}"
        '<span class="field-inline"><label class="filter-label" for="q">Search</label>'
        f'<input type="search" id="q" name="q" value="{html.escape(q)}" '
        'placeholder="Title, excerpt, or caption…"></span>'
        '<span class="field-inline"><label class="filter-label" for="sort">Sort</label>'
        f'<select id="sort" name="sort">{options}</select></span>'
        '<button type="submit" class="btn btn-sm">Apply</button>'
        "</form>"
    )


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
    q: str = "",
    sort: str = "",
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
    per_page = int((page or {}).get("per_page") or 0)
    filtered = total != matched or bool(q)
    count_text = (
        f"{matched} of {total} open draft(s)" if filtered else f"{matched} open draft(s)"
    )
    header = (
        "<header><div><h1>Review</h1>"
        f'<div class="sub">{count_text} · generated '
        f"{html.escape(generated_at.astimezone().strftime('%Y-%m-%d %H:%M %Z'))}</div></div>"
        '<div class="cmdbar">'
        + (
            '<form method="post" action="/publish/run">'
            '<button type="submit">Post approved now</button></form>'
            if scheduling
            else ""
        )
        + '<form method="post" action="/scan">'
        '<button type="submit" class="btn-primary">Scan sources now</button></form>'
        "</div></header>"
    )
    toolbar = _search_form(selected_source, selected_status, q, sort, per_page)
    filters = _filter_bar(
        sources,
        statuses,
        selected_source,
        selected_status,
        source_total,
        status_total,
        q=q,
        sort=sort,
    )
    pager = _pagination_bar(page, selected_source, selected_status, q=q, sort=sort) if page else ""

    if not drafts:
        if filtered:
            body = (
                '<div class="panel-body"><p class="muted">No drafts match this filter. '
                '<a href="/review">Clear filters</a>.</p></div>'
            )
        else:
            body = (
                '<div class="panel-body"><p class="muted">No open drafts. Click '
                "<strong>Scan sources now</strong> (or wait for the scheduled scan)."
                "</p></div>"
            )
    else:
        body = '<div class="qlist">' + "".join(_draft_card(draft) for draft in drafts) + "</div>"

    queue = (
        '<section class="panel">'
        f'<div class="panel-head"><span class="label">Queue</span>{pager}</div>'
        f"{body}</section>"
    )
    return layout(
        "Social Content Factory — review",
        header + toolbar + filters + queue,
        active="review",
        message=message,
        private=private,
    )


def _stepper(draft: Draft) -> str:
    """The draft's position in the pipeline: extracted -> ai_draft -> approved -> posted."""
    order = [key for key, _ in _PIPELINE_STEPS]
    try:
        current = order.index(draft.state)
    except ValueError:
        current = -1
    rows: list[str] = []
    for index, (key, label) in enumerate(_PIPELINE_STEPS):
        if index < current:
            cls, mark, note = "step is-done", "✓", "done"
        elif index == current:
            cls, mark, note = "step is-now", "●", "now"
        else:
            cls, mark, note = "step", "·", "not yet"
        if key == "extracted" and draft.source:
            note = f"queued from {draft.source}"
        elif key == "ai_draft" and draft.state == "ai_draft":
            note = "rewritten · waiting on you"
        elif key == "posted" and draft.post_id:
            note = draft.permalink or draft.post_id
        rows.append(
            f'<div class="{cls}"><span class="step-dot" aria-hidden="true">{mark}</span>'
            f'<span class="step-name">{html.escape(label)}'
            f'<span class="small">{html.escape(note)}</span></span></div>'
        )
    return '<div class="stepper">' + "".join(rows) + "</div>"


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
    posting_paused: bool = False,
) -> str:
    """Render one draft: the post it will create, its source, and the actions."""
    title = html.escape(display_title(draft.caption, draft.title or draft.id))
    dest_text = ", ".join(labels_for(draft.destinations or ["facebook"]))
    meta_bits = [badge(draft.state)]
    if draft.source:
        meta_bits.append(f'<span class="badge badge-source">{html.escape(draft.source)}</span>')
    if draft.published:
        # Sources date items several ways (RFC 822, ISO 8601); show it the same
        # way the queue rows do rather than leaking the raw string.
        meta_bits.append(f"<span>published {html.escape(_fmt_date(draft.published))}</span>")
    next_link = ""
    if next_id:
        next_link = (
            f'<a class="next" href="/review/{html.escape(next_id)}">Next draft →</a>'
        )
    header = (
        "<header><div>"
        '<a class="crumbs" href="/review">← Review queue</a>'
        f"<h1>{title}</h1>"
        f'<div class="head-meta">{"".join(meta_bits)}{next_link}</div>'
        "</div></header>"
    )

    media = ""
    if draft.image:
        alt = html.escape(draft.image_prompt or draft.title or "Post image")
        media = (
            '<figure class="hero">'
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
    prompt = html.escape(draft.image_prompt or "")
    action = html.escape(f"/review/{draft.id}")

    form = (
        f'<form id="publish-form" class="form-block" method="post" action="{action}/publish"'
        f' data-private="{"true" if private else "false"}">'
        '<div class="field"><label for="caption">Caption · Vietnamese</label>'
        f'<textarea id="caption" name="caption" lang="vi">{caption}</textarea>'
        '<div class="countbar"><span id="caption-count">'
        f"{len(draft.post_text)}</span> characters posted (caption + hashtags)"
        "</div></div>"
        '<div class="field"><label for="hashtags">Hashtags</label>'
        f'<input type="text" id="hashtags" name="hashtags" value="{tags}">'
        '<div class="field-hint">Appended to the caption when posted. '
        "Space or comma separated.</div></div>"
        '<div class="field"><label for="image_prompt">Image prompt · English</label>'
        f'<input type="text" id="image_prompt" name="image_prompt" value="{prompt}">'
        '<div class="field-hint">Subject and composition for the generated image — '
        "also the image's alt text. Falls back to the source title when blank."
        "</div></div>"
        "</form>"
    )

    masthead = leading_masthead(draft.caption)
    masthead_pill = (
        f'<span class="pill">{html.escape(masthead)}</span>'
        if masthead
        else '<span class="pill"><span class="dot dot-warn"></span>no masthead on line 1</span>'
    )
    compose = (
        '<section class="panel">'
        '<div class="panel-head"><span class="label">Compose</span>'
        f"{masthead_pill}</div>"
        f'<div class="composer">{image_note}{form}</div></section>'
    )

    preview_media = ""
    if draft.image:
        preview_media = (
            f'<img class="media" src="{html.escape(draft.image)}" alt="" loading="lazy">'
        )
    preview = (
        '<section class="panel">'
        '<div class="panel-head"><span class="label">Preview</span>'
        '<span class="pill">exactly what posts</span></div>'
        '<div class="panel-body"><div class="post-preview">'
        '<div class="head"><span class="avatar" aria-hidden="true">A</span>'
        f'<span class="meta"><span class="name">{html.escape(BRAND_EYEBROW)}</span>'
        '<span class="when">Just now · 🌐</span></span></div>'
        f'<div class="body" id="preview-body" lang="vi">{caption}</div>'
        f'<div class="tags" id="preview-tags">{tags}</div>'
        f"{preview_media}"
        "</div>"
        '<p class="field-hint">The feed shows roughly the first two lines before '
        "“See more”.</p></div></section>"
    )

    primary = "Publish privately" if private else "Post publicly"
    target = (
        "Private mode: posted unpublished, visible to page admins only."
        if private
        else f"This publishes to {dest_text}."
    )
    image_button = ""
    if image_enabled:
        label = "Regenerate image" if draft.image else "Generate image"
        image_button = (
            f'<form id="image-form" method="post" action="{action}/image">'
            f'<button type="submit" class="btn btn-quiet">{label}</button></form>'
        )
    # Timed posting: a human approves here, the serve scheduler posts later.
    # The button submits the caption form too, so edits are saved with the
    # approval instead of being silently dropped. Only an ai_draft can approve.
    approve_button = ""
    when = f"the next slot ({next_post})" if next_post else "the next slot"
    if scheduling and draft.state == "ai_draft":
        approve_button = (
            '<button type="submit" form="publish-form" name="approve" value="1" '
            'class="btn">Approve &amp; schedule</button>'
        )
    action_bar = (
        '<div class="action-bar">'
        f'<button type="submit" form="publish-form" class="btn-primary">{primary}</button>'
        f"{approve_button}"
        f'<button type="submit" form="publish-form" formaction="{action}/save" '
        'name="save" value="1" class="btn btn-quiet">Save</button>'
        f"{image_button}"
        f'<span class="hint">{target}</span>'
        '<span class="spacer"></span>'
        f'<form id="reject-form" method="post" action="{action}/reject">'
        '<button type="submit" class="btn btn-danger">Reject</button></form>'
        "</div>"
    )

    schedule_note = ""
    if scheduling and draft.state == "approved":
        if posting_paused:
            schedule_note = (
                '<p class="field-hint">Approved — posting is paused, so it waits until '
                "you resume. Use Post now to send it immediately.</p>"
            )
        else:
            schedule_note = (
                f'<p class="field-hint">Approved — waiting for {html.escape(when)}. '
                "Use Post now to send it immediately.</p>"
            )
    elif scheduling and draft.state == "ai_draft":
        if posting_paused:
            schedule_note = (
                '<p class="field-hint">Approve &amp; schedule queues this; posting is '
                "paused, so it sends when you resume. Post now sends it immediately.</p>"
            )
        else:
            schedule_note = (
                "<p class=\"field-hint\">Approve &amp; schedule queues this for "
                f"{html.escape(when)}; Post now sends it immediately.</p>"
            )

    posted_lines: list[str] = []
    for name, record in draft.posts.items():
        if record.get("private"):
            continue
        link = str(record.get("permalink") or record.get("post_id") or "")
        posted_lines.append(
            f"Already posted to {html.escape(label_for(name))}: {html.escape(link)}"
        )
    posted = ""
    if posted_lines:
        posted = '<p class="muted">' + "<br>".join(posted_lines) + "</p>"

    rail_parts: list[str] = []
    rail_parts.append('<div class="rail-block"><span class="section-label">Source</span>')
    if draft.title:
        rail_parts.append(f"<p>{html.escape(draft.title)}</p>")
    if draft.url:
        rail_parts.append(
            f'<p><a href="{html.escape(draft.url)}">{html.escape(draft.url)}</a></p>'
        )
    if draft.published:
        rail_parts.append(
            f'<p class="muted">Published {html.escape(_fmt_date(draft.published))}</p>'
        )
    if draft.excerpt:
        rail_parts.append(f'<p class="excerpt">{html.escape(draft.excerpt)}</p>')
    rail_parts.append("</div>")
    if draft.commentary:
        rail_parts.append(
            '<div class="rail-block"><span class="section-label">Rewriter notes</span>'
            f'<p class="notes">{html.escape(draft.commentary)}</p></div>'
        )
    if draft.cta:
        rail_parts.append(
            '<div class="rail-block"><span class="section-label">CTA · review only, '
            "not posted</span>"
            f'<p class="excerpt">{html.escape(draft.cta)}</p></div>'
        )
    if dna:
        rail_parts.append(
            '<div class="rail-block"><details class="dna">'
            "<summary>Atento DNA · brand voice</summary>"
            f"<pre>{html.escape(dna)}</pre></details></div>"
        )
    rail = '<aside class="panel">' + "".join(rail_parts) + "</aside>"

    pipeline_panel = (
        '<section class="panel">'
        '<div class="panel-head"><span class="label">Pipeline</span></div>'
        f'<div class="panel-body">{_stepper(draft)}</div></section>'
    )

    tail = (
        '<p class="muted">Publishing is human-gated: only the buttons here send '
        "anything.</p>"
    )

    body = (
        header
        + '<div class="detail">'
        + '<div class="stack">'
        + media
        + compose
        + preview
        + "</div>"
        + '<div class="stack">'
        + pipeline_panel
        + rail
        + "</div>"
        + "</div>"
        + schedule_note
        + posted
        + action_bar
        + tail
        + _DETAIL_SCRIPT.replace("__DEST__", dest_text)
    )
    return layout(
        f"Social Content Factory — {draft.id}",
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
