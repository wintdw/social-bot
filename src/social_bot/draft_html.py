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
    private: bool = False,
    generated_at: dt.datetime | None = None,
) -> str:
    """Render one draft with an editable caption and approve/reject actions."""
    info: list[str] = [
        "<header>",
        f"<h1>{html.escape(draft.title or draft.id)}</h1>",
        f'<div class="meta">{badge(draft.state)} · '
        f"{html.escape(draft.source)} · {html.escape(draft.published or '')}</div>",
        "</header>",
    ]
    info.append(f'<p><a href="{html.escape(draft.url)}">{html.escape(draft.url)}</a></p>')
    if draft.image:
        info.append(
            f'<p><img class="preview" src="{html.escape(draft.image)}" '
            f'alt="{html.escape(draft.alt_text or draft.title)}"></p>'
        )
    if draft.excerpt:
        info.append(f'<p class="excerpt">{html.escape(draft.excerpt)}</p>')

    caption = html.escape(draft.caption or "")
    hashtags = html.escape(" ".join(draft.hashtags))
    action = html.escape(f"/review/{draft.id}")
    body = [
        f'<form method="post" action="{action}/publish">',
        '<div class="field"><label for="caption">Caption (editable — this is what gets posted)</label>',
        f'<textarea id="caption" name="caption">{caption}</textarea></div>',
        '<div class="field"><label for="hashtags">Hashtags (comma or space separated)</label>',
        f'<input type="text" id="hashtags" name="hashtags" value="{hashtags}"></div>',
        '<div class="field"><button type="submit" name="dry_run" value="1">Dry run</button>',
        '<button type="submit">Approve &amp; post</button></div>',
        "</form>",
        f'<form method="post" action="{action}/reject"><button type="submit">Reject</button></form>',
    ]
    if draft.post_id:
        permalink = html.escape(draft.permalink or draft.post_id)
        body.append(f'<p class="muted">Posted: {permalink}</p>')
    if dna:
        body.append(
            '<details class="field"><summary>Atento DNA (brand voice)</summary>'
            f"<pre class='muted'>{html.escape(dna)}</pre></details>"
        )
    body.append(
        '<p class="muted">Publishing is human-gated: only the buttons above send anything.</p>'
    )

    return layout(
        f"social-bot — {draft.id}",
        "".join(info) + "\n" + "".join(body),
        active="review",
        message=message,
        private=private,
    )


def render_message_html(title: str, message: str) -> str:
    """A tiny standalone notice page (used for errors / not-found)."""
    body = (
        f"<h1>{html.escape(title)}</h1>\n<p>{html.escape(message)}</p>\n"
        '<p><a class="btn" href="/review">Back to review</a></p>'
    )
    return layout(title, body, active="")
