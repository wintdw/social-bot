"""Feed parsing and rendering (pure logic, no network).

Kept separate from api.py so feed formatting is unit-testable offline:
given Graph API /{page}/feed JSON it produces FeedItem dataclasses and a
plain-markdown digest.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

_OFFSET_NO_COLON_RE = re.compile(r"^(.{19})([+-]\d{2})(\d{2})$")


def parse_fb_datetime(text: str | None) -> dt.datetime | None:
    """Parse a Graph API created_time into an aware datetime.

    Meta sends ISO-8601 with a colon-less numeric offset ("+0000"); plain
    datetime.fromisoformat rejects that until the offset gets a colon.
    """
    if not text:
        return None
    if _OFFSET_NO_COLON_RE.match(text):
        text = _OFFSET_NO_COLON_RE.sub(r"\1\2:\3", text)
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class FeedItem:
    id: str = ""
    created: dt.datetime | None = None
    message: str = ""
    story: str = ""
    status_type: str = ""
    permalink_url: str = ""
    from_name: str = ""

    @property
    def text(self) -> str:
        """The human-readable body: message, falling back to story text."""
        return self.message or self.story


def parse_feed_response(payload: dict) -> list[FeedItem]:
    """Turn a decoded /{page}/feed response into FeedItems (newest first)."""
    items: list[FeedItem] = []
    for raw in payload.get("data", []):
        source = raw.get("from") or {}
        items.append(
            FeedItem(
                id=str(raw.get("id", "")),
                created=parse_fb_datetime(raw.get("created_time")),
                message=str(raw.get("message", "") or ""),
                story=str(raw.get("story", "") or ""),
                status_type=str(raw.get("status_type", "") or ""),
                permalink_url=str(raw.get("permalink_url", "") or ""),
                from_name=str(source.get("name", "") or ""),
            )
        )
    return items


def _render_created(created: dt.datetime | None) -> str:
    if created is None:
        return "(no timestamp)"
    local = created.astimezone()
    return local.strftime("%Y-%m-%d %H:%M %Z")


def format_feed_md(items: list[FeedItem]) -> str:
    """Render feed items as a plain markdown digest for printing."""
    if not items:
        return "No posts on the feed."
    lines = [f"{len(items)} most recent post(s):\n"]
    for i, item in enumerate(items, start=1):
        lines.append(f"### {i}. {item.from_name or '(page)'} — {_render_created(item.created)}")
        if item.text:
            lines.append("")
            lines.append(item.text)
        else:
            lines.append("")
            lines.append(f"*(no text — {item.status_type or 'media'} post)*")
        if item.permalink_url:
            lines.append("")
            lines.append(item.permalink_url)
        if i < len(items):
            lines.append("")
    return "\n".join(lines)
