"""HTML rendering of the draft review queue (pure logic, no network).

Backs the operator UI's /review pages. The overview list is render_drafts_html;
the detail page with the editable caption and approve/reject actions is
render_draft_html. All content is escaped.

The queue rows are scannable: a thumbnail, the state badge, the source, the
series masthead, the item's own date, and a one-line caption preview. A row is
titled by the caption's hook — the rule shared with the feed in `caption.py` —
falling back to the source's own title while the draft is still unwritten. The
detail page reads as a production sheet — image hero, editable caption, a live
Facebook-style preview, a pipeline stepper, and one clearly primary action. Its
secondary controls are grouped in the Compose panel under the fields they act on
(the image tools), so the sticky action bar carries only the terminal actions that
move the draft: post, approve & schedule, save, reject.
"""

from __future__ import annotations

import datetime as dt
import html
import urllib.parse

from .caption import display_title, leading_masthead
from .destinations import label_for, labels_for
from .destinations import names as destination_names
from .drafts import Draft, parse_when
from .ui import BRAND_EYEBROW, badge, fmt_when, layout

# Human labels for the status filter chips (the badge shows the raw state).
_STATE_LABELS = {
    "extracted": "Extracted",
    "ai_draft": "AI draft",
    "approved": "Approved",
    "posted": "Posted",
    "rejected": "Rejected",
}

# The pipeline stages a draft moves through, in order.
_PIPELINE_STEPS = (
    ("extracted", "Extracted"),
    ("ai_draft", "AI draft"),
    ("approved", "Approved"),
    ("posted", "Posted"),
)

# Sort orders offered on the review list. Whether a draft posts, and when, is
# not a review concern — that order lives on the Post queue tab.
_SORTS = (
    ("newest", "Newest first"),
    ("oldest", "Oldest first"),
)

# Client-side enhancement for the detail page: keeps the post preview and the
# character count in sync while editing, blocks a double submit, and asks for
# confirmation before a public post. The form still works without it.
_DETAIL_SCRIPT = """<script>
(function () {
  var form = document.getElementById('publish-form');
  if (!form) return;
  var caption = document.getElementById('caption');
  var tags = document.getElementById('hashtags');
  var count = document.getElementById('caption-count');
  var buttons = document.querySelectorAll('button[form="publish-form"]');
  function normTags() {
    return tags.value.trim().replace(/[,\\n]+/g, ' ').replace(/\\s+/g, ' ');
  }
  function sync() {
    var text = caption.value;
    var tagText = normTags();
    var body = document.getElementById('preview-body');
    var tagLine = document.getElementById('preview-tags');
    if (body) body.textContent = text;
    if (tagLine) tagLine.textContent = tagText;
    count.textContent = String(text.length + (tagText ? 2 + tagText.length : 0));
  }
  caption.addEventListener('input', sync);
  tags.addEventListener('input', sync);
  sync();
  form.addEventListener('submit', function (event) {
    if (form.dataset.submitting === '1') { event.preventDefault(); return; }
    var button = event.submitter;
    // What a submit *does* is read off where it goes, not off a list of button
    // names: Save overrides the form's action with formaction, so only a submit of
    // the form's own action publishes — and only that one asks for the posting
    // confirmation. A submit with no button (Enter in a field) counts as a post.
    var target = (button && button.getAttribute('formaction')) || form.getAttribute('action');
    var posts = target === form.getAttribute('action');
    var isApprove = !!button && button.name === 'approve';
    if (posts && !isApprove && form.dataset.private !== 'true') {
      // The button names the platform it sends to, so the confirmation matches
      // which one is about to go out rather than the draft's whole target list.
      var dest = (button && button.dataset && button.dataset.dest) || '__DEST__';
      if (!window.confirm('Post this publicly to ' + dest + '?')) {
        event.preventDefault();
        return;
      }
    }
    form.dataset.submitting = '1';
    for (var i = 0; i < buttons.length; i++) {
      if (buttons[i] !== button) buttons[i].disabled = true;
    }
    if (!button) return;
    // The button's own name is only a cue for which verb to show.
    if (isApprove) button.textContent = 'Approving\u2026';
    else if (button.name === 'save') button.textContent = 'Saving\u2026';
    else if (posts) button.textContent = 'Posting\u2026';
  });
  var reject = document.getElementById('reject-form');
  if (reject) reject.addEventListener('submit', function (event) {
    if (!window.confirm('Reject this draft? It leaves the review queue.')) {
      event.preventDefault();
    }
  });
})();
</script>"""


def _draft_card(draft: Draft) -> str:
    """One review row: thumbnail, title, state/source/date, caption preview."""
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
    # Show the item's own date — the one the list is sorted by — falling back
    # to when it was queued (a source without dates still shows something).
    stamp = draft.published or draft.created_at or draft.updated_at
    label = "published" if draft.published else "queued"
    shown = fmt_when(stamp)
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
    return f'<a class="seg-item" href="{html.escape(href)}"{current}>{html.escape(label)}{num}</a>'


def _pagination_bar(page: dict, source: str, status: str, *, q: str = "", sort: str = "") -> str:
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
        f"{' selected' if value == (sort or 'newest') else ''}>"
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

    Rows are plain links. The posting order is set on the Post queue tab, not
    here, so a review row carries no reorder controls.
    """
    generated_at = generated_at or dt.datetime.now()
    matched = len(drafts) if matched is None else matched
    total = matched if total is None else total
    source_total = total if source_total is None else source_total
    status_total = total if status_total is None else status_total
    per_page = int((page or {}).get("per_page") or 0)
    filtered = total != matched or bool(q)
    count_text = f"{matched} of {total} open draft(s)" if filtered else f"{matched} open draft(s)"
    header = (
        "<header><div><h1>Review queue</h1>"
        f'<div class="sub">{count_text} · generated '
        f"{html.escape(generated_at.astimezone().strftime('%Y-%m-%d %H:%M %Z'))}</div></div>"
        '<div class="cmdbar">'
        '<form method="post" action="/scan">'
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


def _lint_notice(draft: Draft) -> str:
    """The advisory AI-tell warnings on a caption ('' when clean).

    Lint is advice, never a gate: it never blocks an approval or a post, so it
    renders as a warning notice above the caption the reviewer is about to edit.
    """
    if not draft.lint:
        return ""
    items = "".join(
        f"<li>{html.escape(str(warning.get('message', '')))}</li>" for warning in draft.lint
    )
    return (
        '<div class="notice notice-warn">'
        "<strong>AI tells to check</strong>"
        f'<ul class="lint-list">{items}</ul></div>'
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
            note = "caption written · waiting on you"
        elif key == "posted" and draft.post_id:
            if "facebook" in draft.posted_destinations():
                note = draft.permalink or draft.post_id
            else:
                # The primary post is LinkedIn, whose URL is a read-back
                # guess — don't present it as the post's link.
                note = "posted"
        rows.append(
            f'<div class="{cls}"><span class="step-dot" aria-hidden="true">{mark}</span>'
            f'<span class="step-name">{html.escape(label)}'
            f'<span class="small">{html.escape(note)}</span></span></div>'
        )
    return '<div class="stepper">' + "".join(rows) + "</div>"


def render_draft_html(
    draft: Draft,
    *,
    message: str = "",
    message_kind: str = "info",
    private: bool = False,
    image_generated: bool = False,
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
        # way the list rows do rather than leaking the raw string.
        meta_bits.append(f"<span>published {html.escape(fmt_when(draft.published))}</span>")
    next_link = ""
    if next_id:
        next_link = f'<a class="next" href="/review/{html.escape(next_id)}">Next draft →</a>'
    header = (
        "<header><div>"
        '<a class="crumbs" href="/review">← Review queue</a>'
        f"<h1>{title}</h1>"
        f'<div class="head-meta">{"".join(meta_bits)}{next_link}</div>'
        "</div></header>"
    )

    media = ""
    if draft.image:
        alt = html.escape(draft.title or "Post image")
        media = (
            '<figure class="hero">'
            f'<img src="{html.escape(draft.image)}" alt="{alt}" loading="lazy">'
            "</figure>"
        )

    # Images are the source post's own cover or a drawn plate —
    # nothing is generated in the background anymore.
    image_note = ""
    if not draft.image:
        image_note = '<p class="muted">No image yet — the post will publish without one.</p>'
    elif image_generated:
        image_note = (
            '<p class="muted">A drawn plate, not the source post’s own — '
            "“Restore source image” below puts the original back.</p>"
        )

    caption = html.escape(draft.caption or "")
    tags = html.escape(" ".join(draft.hashtags))
    action = html.escape(f"/review/{draft.id}")

    # Where this post goes. One checkbox chip per known destination, submitted
    # with whichever button is pressed, so the picker saves alongside the
    # caption — and the action bar then carries one Post button per pending
    # platform, so Facebook and LinkedIn are separate sends rather than one
    # glued action. The chips reuse the shared `.chip` style (the tick is the
    # accent fill); each option also names its send state (posted/pending), so
    # the operator sees what is left to send without scrolling to the action
    # bar.
    known = destination_names()
    selected = [name for name in draft.destinations if name in known]
    posted = set(draft.posted_destinations())
    dest_picker = ""
    if len(known) > 1:

        def _dest_box(name: str) -> str:
            state = ""
            if name in posted:
                state = '<span class="count">· posted</span>'
            elif name in selected:
                state = '<span class="count">· pending</span>'
            checked = " checked" if name in selected else ""
            return (
                '<label class="chip">'
                f'<input type="checkbox" name="destinations" value="{html.escape(name)}"{checked}>'
                f"{html.escape(label_for(name))}"
                f"{state}</label>"
            )

        boxes = "".join(_dest_box(name) for name in known)
        hints = [
            "Every ticked platform posts separately, with its own button below.",
        ]
        if "linkedin" in selected and private:
            hints.append("Private mode does not apply to LinkedIn — it still posts publicly.")
        dest_picker = (
            '<div class="field"><span class="field-label">Destinations</span>'
            f'<div class="cmdbar">{boxes}</div>'
            '<input type="hidden" name="destinations_field" value="1">'
            f'<div class="field-hint">{" ".join(hints)}</div></div>'
        )

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
        f"{dest_picker}"
        "</form>"
    )

    # The current image is a diagram, so the source post's own picture is
    # still available (stored on the draft, or read back from the source page).
    # Its own form: restoring the image must not save or post the caption edits.
    restore_button = ""
    if image_generated:
        restore_button = (
            f'<form id="restore-image-form" method="post" action="{action}/restore-image">'
            '<button type="submit" class="btn btn-quiet">Restore source image</button>'
            "</form>"
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

    # Approval is reversible until the post goes out: a queued draft can be
    # pulled back to ai_draft, so the poster skips it while it stays on /review
    # for another pass. Its own form (like Reject): unapproving is a state
    # change, not a commit of the compose fields.
    unapprove_button = ""
    if draft.state == "approved":
        unapprove_button = (
            f'<form id="unapprove-form" method="post" action="{action}/unapprove">'
            '<button type="submit" class="btn btn-quiet">Unapprove</button></form>'
        )

    tool_groups = ""
    image_tools = restore_button
    if image_tools:
        tool_groups += (
            '<div class="toolgroup" role="group" aria-label="Image tools">'
            '<span class="toolgroup-label">Image</span>'
            f'<div class="cmdbar">{image_tools}</div></div>'
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
        f'<div class="composer">{_lint_notice(draft)}{image_note}'
        f"{form}{tool_groups}</div></section>"
    )

    preview_media = ""
    if draft.image:
        preview_media = (
            f'<img class="media" src="{html.escape(draft.image)}" alt="" loading="lazy">'
        )
    # One preview: exactly what posts. Both destinations receive the same text
    # and (when there is one) the same image, so no per-platform preview.
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

    # One button per platform still to receive this draft. A single send (the
    # only target, or the last gap left) keeps the plain Post publicly label;
    # with two pending the operator picks the platform, so each is its own send.
    done = set(draft.posted_destinations())
    pending = [name for name in (draft.destinations or known[:1]) if name not in done]
    several = len(pending) > 1
    post_buttons = ""
    for index, name in enumerate(pending):
        label = label_for(name)
        text = (
            f"Post to {label}" if several else ("Publish privately" if private else "Post publicly")
        )
        post_buttons += (
            f'<button type="submit" form="publish-form" '
            f'class="{"btn-primary" if index == 0 else "btn"}" '
            f'name="destination" value="{html.escape(name)}" '
            f'data-dest="{html.escape(label)}">{html.escape(text)}</button>'
        )
    if not post_buttons:
        post_buttons = '<span class="hint">Already posted to every destination.</span>'
    pending_text = ", ".join(labels_for(pending))
    if private:
        target = "Private mode: posted unpublished, visible to page admins only."
    elif several:
        target = f"This publishes to {pending_text} — one platform per button."
    else:
        target = f"This publishes to {pending_text or dest_text}."
    # The bar carries only the terminal actions — post, approve, save, reject.
    # The compose-local tools (image) are grouped up in the Compose
    # panel, under the fields they act on.
    action_bar = (
        '<div class="action-bar">'
        f"{post_buttons}"
        f"{approve_button}{unapprove_button}"
        f'<button type="submit" form="publish-form" formaction="{action}/save" '
        'name="save" value="1" class="btn btn-quiet">Save</button>'
        f'<span class="hint">{target}</span>'
        '<span class="spacer"></span>'
        f'<form id="reject-form" method="post" action="{action}/reject">'
        '<button type="submit" class="btn btn-danger">Reject</button></form>'
        "</div>"
    )

    schedule_note = ""
    if scheduling and draft.state == "approved":
        tail = "Use Post now to send it immediately; Unapprove pulls it from the queue."
        if posting_paused:
            schedule_note = (
                '<p class="field-hint">Approved — posting is paused, so it waits until '
                f"you resume. {tail}</p>"
            )
        else:
            schedule_note = (
                f'<p class="field-hint">Approved — waiting for {html.escape(when)}. {tail}</p>'
            )
    elif scheduling and draft.state == "ai_draft":
        if posting_paused:
            schedule_note = (
                '<p class="field-hint">Approve &amp; schedule queues this; posting is '
                "paused, so it sends when you resume. Post now sends it immediately.</p>"
            )
        else:
            schedule_note = (
                '<p class="field-hint">Approve &amp; schedule queues this for '
                f"{html.escape(when)}; Post now sends it immediately.</p>"
            )

    posted_lines: list[str] = []
    for name, record in draft.posts.items():
        if record.get("private"):
            continue
        if name == "linkedin":
            # LinkedIn's URL is a read-back guess, not the post's link.
            posted_lines.append(f"Already posted to {html.escape(label_for(name))}.")
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
        rail_parts.append(f'<p><a href="{html.escape(draft.url)}">{html.escape(draft.url)}</a></p>')
    if draft.topic:
        # An original draft has no source page — only the system/theme the idea
        # was drawn from, so provenance reads "Original idea · <topic>".
        rail_parts.append(f'<p class="muted">Original idea · {html.escape(draft.topic)}</p>')
    if draft.published:
        rail_parts.append(
            f'<p class="muted">Published {html.escape(fmt_when(draft.published))}</p>'
        )
    if draft.excerpt:
        rail_parts.append(f'<p class="excerpt">{html.escape(draft.excerpt)}</p>')
    rail_parts.append("</div>")
    if draft.commentary:
        rail_parts.append(
            '<div class="rail-block"><span class="section-label">Notes</span>'
            f'<p class="notes">{html.escape(draft.commentary)}</p></div>'
        )
    if draft.cta:
        rail_parts.append(
            '<div class="rail-block"><span class="section-label">CTA · review only, '
            "not posted</span>"
            f'<p class="excerpt">{html.escape(draft.cta)}</p></div>'
        )
    rail = '<aside class="panel">' + "".join(rail_parts) + "</aside>"

    pipeline_panel = (
        '<section class="panel">'
        '<div class="panel-head"><span class="label">Pipeline</span></div>'
        f'<div class="panel-body">{_stepper(draft)}</div></section>'
    )

    tail = (
        '<p class="muted">Publishing is human-gated: only the buttons on this page '
        "send anything.</p>"
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


def render_message_html(
    title: str, message: str, *, back: str = "/review", back_label: str = "Back to review"
) -> str:
    """A tiny standalone notice page (used for errors / not-found)."""
    body = (
        f"<h1>{html.escape(title)}</h1>\n<p>{html.escape(message)}</p>\n"
        f'<p><a class="btn" href="{html.escape(back)}">{html.escape(back_label)}</a></p>'
    )
    return layout(title, body, active="")
