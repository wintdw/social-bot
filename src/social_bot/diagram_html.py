"""Browser-rendered explainer diagrams (pure logic, no network, stdlib only).

A plate is drawn exactly once, as SVG, in ``diagram``. This module only wraps
that SVG in a standalone HTML document so a headless Chromium can screenshot it
to the PNG bytes the publisher uploads — the wrapper sets the page box and
nothing else, so the PNG and the SVG preview can never disagree. The Chromium
call itself lives in ``browser_shot``; nothing here imports it, so tests never
need a browser.
"""

from __future__ import annotations

from social_bot import diagram

WIDTH = diagram.WIDTH
HEIGHT = diagram.HEIGHT


def _wrap(svg: str) -> str:
    """The SVG in a bare, full-bleed page (no margin, no baseline gap)."""
    return (
        "<!doctype html><html><head><meta charset='utf-8'></head>"
        f"<body style='margin:0;width:{WIDTH}px;height:{HEIGHT}px;line-height:0'>{svg}</body>"
        "</html>"
    )


def render_sparse_index_html(**kwargs) -> str:
    """The sparse-index plate as a page: its SVG, wrapped."""
    return _wrap(diagram.render_sparse_index(**kwargs))


def render_write_concern_html(**kwargs) -> str:
    """The write-concern plate as a page: its SVG, wrapped."""
    return _wrap(diagram.render_write_concern(**kwargs))


def render_for_draft_html(draft) -> str:
    """The page for a draft, or '' when no plate matches it."""
    svg = diagram.render_for_draft(draft)
    return _wrap(svg) if svg else ""


__all__ = [
    "HEIGHT",
    "WIDTH",
    "render_for_draft_html",
    "render_sparse_index_html",
    "render_write_concern_html",
]
