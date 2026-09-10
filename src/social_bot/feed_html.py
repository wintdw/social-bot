"""HTML rendering of a cached page feed (pure logic, no network).

`render_feed_section` yields the posts fragment the dashboard embeds;
`render_feed_html` wraps it as a standalone page (written to latest.html by
`refresh`). All user content is escaped.
"""

from __future__ import annotations

import datetime as dt
import html

from .feed import FeedItem
from .ui import layout


def _render_created(created: dt.datetime | None) -> str:
    if created is None:
        return "(no timestamp)"
    return created.astimezone().strftime("%Y-%m-%d %H:%M %Z")


def render_feed_section(items: list[FeedItem]) -> str:
    """The feed posts as an embeddable fragment (no page chrome)."""
    if not items:
        return '<p class="empty">No posts on the feed.</p>'
    parts: list[str] = []
    for item in items:
        created = html.escape(_render_created(item.created))
        parts.append(f"<article><time>{created}</time>")
        if item.text:
            parts.append(f"<p>{html.escape(item.text)}</p>")
        else:
            label = html.escape(item.status_type or "media")
            parts.append(f'<p class="empty">(no text — {label} post)</p>')
        if item.permalink_url:
            url = html.escape(item.permalink_url)
            parts.append(f'<a class="permalink" href="{url}">{url}</a>')
        parts.append("</article>")
    return "".join(parts)


def render_feed_html(
    items: list[FeedItem],
    *,
    page_name: str = "",
    page_id: str = "",
    generated_at: dt.datetime | None = None,
) -> str:
    """Render feed items as a standalone HTML document."""
    generated_at = generated_at or dt.datetime.now()
    title = page_name or page_id or "Page"
    header = (
        "<header>"
        f"<h1>{html.escape(title)}</h1>"
        f'<div class="meta">{len(items)} most recent post(s) · cached '
        f"{html.escape(generated_at.astimezone().strftime('%Y-%m-%d %H:%M %Z'))}</div>"
        "</header>"
    )
    return layout(f"social-bot — {title}", header + render_feed_section(items), active="dashboard")
