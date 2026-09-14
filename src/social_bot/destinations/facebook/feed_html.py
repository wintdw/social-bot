"""HTML rendering of a cached page feed (pure logic, no network).

`render_feed_section` yields the posts fragment the dashboard embeds;
`render_feed_html` wraps it as a standalone page (written to latest.html by
`refresh`). All user content is escaped.

Each post renders as a row in the review queue's own idiom — the shared
`.qrow` / `.qthumb` / `.qbody` / `.qtitle` / `.qmeta` / `.qpreview` classes — so
the dashboard reads the same whether it is showing drafts or what is already
live. Every row carries a title, so posts stay consistent whatever their
provenance: the hook under the leading series masthead, or the caption's own
first line when there is no masthead (see `caption.split_title`). The masthead
itself rides along as a pill, so the series cue stays visible.
"""

from __future__ import annotations

import datetime as dt
import html

from ...caption import leading_masthead, split_title
from ...ui import layout
from .feed import FeedItem


def _render_created(created: dt.datetime | None) -> str:
    if created is None:
        return "(no timestamp)"
    return created.astimezone().strftime("%Y-%m-%d %H:%M %Z")


def render_feed_section(items: list[FeedItem]) -> str:
    """The feed posts as an embeddable fragment, one review-queue row each."""
    if not items:
        return '<p class="empty">No posts on the feed.</p>'
    parts: list[str] = []
    for item in items:
        # A photo post carries the image Graph resolved from its attachment; the
        # placeholder matches the queue's empty thumbnail.
        if item.image:
            thumb = (
                f'<span class="qthumb"><img src="{html.escape(item.image)}" alt="" '
                'loading="lazy"></span>'
            )
        else:
            thumb = '<span class="qthumb empty" aria-hidden="true"></span>'

        # Every row is titled by what the post says: the hook under the series
        # masthead, or the first line when there is no masthead. The masthead
        # itself rides along as a pill so the series cue stays visible. A post
        # with no text at all (a bare photo) still fills the slot, so no row
        # reads as truncated.
        title, rest = split_title(item.text)
        if not title:
            title = f"(no text — {item.status_type or 'media'} post)"

        meta: list[str] = []
        masthead = leading_masthead(item.text)
        if masthead:
            meta.append(f'<span class="pill">{html.escape(masthead)}</span>')
        if item.created is not None:
            machine = html.escape(item.created.isoformat())
            meta.append(
                f'<time datetime="{machine}">'
                f"{html.escape(_render_created(item.created))}</time>"
            )
        else:
            meta.append(html.escape(_render_created(None)))

        body: list[str] = [
            f'<span class="qtitle">{html.escape(title)}</span>',
            f'<span class="qmeta">{"".join(meta)}</span>',
        ]
        if rest:
            body.append(f'<span class="qpreview">{html.escape(rest)}</span>')

        content = thumb + f'<span class="qbody">{"".join(body)}</span>'
        if item.permalink_url:
            url = html.escape(item.permalink_url)
            parts.append(
                f'<a class="qrow" href="{url}">{content}'
                '<span class="qgo" aria-hidden="true">›</span></a>'
            )
        else:
            parts.append(f'<div class="qrow">{content}</div>')
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
        "<header><div>"
        f"<h1>{html.escape(title)}</h1>"
        f'<div class="sub">{len(items)} most recent post(s) · cached '
        f"{html.escape(generated_at.astimezone().strftime('%Y-%m-%d %H:%M %Z'))}</div>"
        "</div></header>"
    )
    body = (
        '<section class="panel">'
        '<div class="panel-head"><span class="label">Page feed</span></div>'
        f'<div class="qlist">{render_feed_section(items)}</div></section>'
    )
    return layout(f"Social Content Factory — {title}", header + body, active="dashboard")
