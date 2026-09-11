"""HTML rendering of the draft review queue (pure logic, no network).

Backs the operator UI's /review pages. The overview list is render_drafts_html;
the detail page with the editable caption and approve/reject actions is
render_draft_html. All content is escaped.
"""

from __future__ import annotations

import datetime as dt
import html

from .drafts import Draft
from .ui import badge, layout

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
    var isDry = !!button && button.value === '1';
    if (!isDry && form.dataset.private !== 'true') {
      if (!window.confirm('Post this publicly to the Facebook Page?')) {
        event.preventDefault();
        return;
      }
    }
    form.dataset.submitting = '1';
    for (var i = 0; i < buttons.length; i++) {
      if (buttons[i] !== button) buttons[i].disabled = true;
    }
    if (button && !isDry) button.textContent = 'Posting\u2026';
  });
  var reject = document.getElementById('reject-form');
  if (reject) reject.addEventListener('submit', function (event) {
    if (!window.confirm('Reject this draft? It leaves the review queue.')) {
      event.preventDefault();
    }
  });
})();
</script>"""


def render_drafts_html(
    drafts: list[Draft],
    *,
    message: str = "",
    private: bool = False,
    generated_at: dt.datetime | None = None,
) -> str:
    """Render the draft queue as a standalone HTML list page."""
    generated_at = generated_at or dt.datetime.now()
    header = (
        "<header>"
        "<h1>Review</h1>"
        f'<div class="meta">{len(drafts)} open draft(s) · generated '
        f"{html.escape(generated_at.astimezone().strftime('%Y-%m-%d %H:%M %Z'))}</div>"
        '<form class="toolbar" method="post" action="/scan">'
        '<button type="submit">Scan sources now</button>'
        '<span class="muted">fetch new items from the source feeds</span>'
        "</form>"
        "</header>"
    )
    if not drafts:
        body = (
            '<p class="muted">No open drafts. Click <strong>Scan sources now</strong> '
            "(or wait for the scheduled scan).</p>"
        )
    else:
        parts: list[str] = []
        for draft in drafts:
            url = html.escape(f"/review/{draft.id}")
            title = html.escape(draft.title or draft.id)
            parts.append("<article>")
            parts.append(
                f'<h2><a href="{url}">{title}</a></h2>'
                f'<div class="meta">{badge(draft.state)} · '
                f"{html.escape(draft.source)} · {html.escape(draft.published or '')}</div>"
            )
            if draft.excerpt:
                parts.append(f'<p class="excerpt">{html.escape(draft.excerpt)}</p>')
            parts.append("</article>")
        body = "".join(parts)

    return layout(
        "social-bot — review",
        header + body,
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
    generated_at: dt.datetime | None = None,
    next_id: str | None = None,
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
    action_bar = (
        '<div class="action-bar">'
        f'<button type="submit" form="publish-form" class="btn-primary">{primary}</button>'
        '<button type="submit" form="publish-form" name="dry_run" value="1" '
        'class="btn-quiet">Dry run</button>'
        f'<span class="muted">{target}</span>'
        '<span class="spacer"></span>'
        f'<form id="reject-form" method="post" action="{action}/reject">'
        '<button type="submit" class="btn-danger">Reject</button></form>'
        "</div>"
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
        + form
        + preview
        + action_bar
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
