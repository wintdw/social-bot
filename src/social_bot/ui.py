"""Shared operator-UI chrome: stylesheet, navigation, and page layout.

Pure rendering (no network, no fastapi) so every page module — dashboard,
review, publish, status, feed — composes the same look and the same top
navigation. Dynamic content is escaped here or by the caller.
"""

from __future__ import annotations

import html

# (key, href, label); `key` is the `active` value a page passes to layout().
NAV = (
    ("dashboard", "/", "Dashboard"),
    ("review", "/review", "Review"),
    ("publish", "/publish", "Published"),
    ("status", "/status", "Status"),
)

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
       max-width: 56rem; margin: 0 auto; padding: 0 1rem 3rem; line-height: 1.5; }
nav { display: flex; flex-wrap: wrap; align-items: center; gap: .25rem;
      padding: .75rem 0; margin-bottom: 1.25rem;
      border-bottom: 1px solid color-mix(in srgb, currentColor 20%, transparent); }
nav .brand { font-weight: 600; margin-right: .75rem; }
nav a { padding: .3rem .6rem; border-radius: .4rem; text-decoration: none; opacity: .65; }
nav a:hover { opacity: 1; }
nav a.active { opacity: 1; background: color-mix(in srgb, currentColor 14%, transparent); }
h1 { font-size: 1.4rem; margin: 0 0 .25rem; }
h2 { font-size: 1.05rem; margin: 1.5rem 0 .4rem; }
header { padding-bottom: .75rem; margin-bottom: 1.25rem;
         border-bottom: 1px solid color-mix(in srgb, currentColor 20%, transparent); }
.meta { opacity: .65; font-size: .85rem; }
.muted { opacity: .6; font-size: .85rem; }
.notice { padding: .6rem .8rem; border: 1px solid currentColor; border-radius: .5rem;
          margin-bottom: 1rem; opacity: .85; }
.controls { display: flex; flex-wrap: wrap; gap: .75rem; align-items: center;
            margin: 1rem 0 1.5rem; }
.toolbar { display: flex; flex-wrap: wrap; gap: .75rem; align-items: center;
           margin-top: .75rem; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
         gap: .75rem; margin-bottom: 1.25rem; }
.card { border: 1px solid color-mix(in srgb, currentColor 18%, transparent);
        border-radius: .6rem; padding: .7rem .9rem; }
.card .num { font-size: 1.4rem; font-weight: 600; line-height: 1.2; }
.card .label { font-size: .8rem; opacity: .7; }
.card .sub { font-size: .78rem; opacity: .6; margin-top: .15rem; }
button, .btn { font: inherit; padding: .45rem .9rem; border-radius: .45rem;
               border: 1px solid color-mix(in srgb, currentColor 45%, transparent);
               background: color-mix(in srgb, currentColor 8%, transparent);
               cursor: pointer; color: inherit; text-decoration: none; display: inline-block; }
button:hover, .btn:hover { background: color-mix(in srgb, currentColor 16%, transparent); }
form { display: inline; }
article { padding: 1rem 0;
          border-bottom: 1px solid color-mix(in srgb, currentColor 12%, transparent); }
article:last-child { border-bottom: none; }
article time { font-size: .8rem; opacity: .65; }
article p { margin: .5rem 0; white-space: pre-wrap; }
article a { word-break: break-all; }
a.permalink { font-size: .82rem; word-break: break-all; }
.badge { display: inline-block; font-size: .72rem; text-transform: uppercase;
         letter-spacing: .05em; padding: .1rem .4rem; border-radius: .4rem;
         border: 1px solid currentColor; opacity: .75; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { text-align: left; padding: .45rem .5rem; vertical-align: top;
         border-bottom: 1px solid color-mix(in srgb, currentColor 12%, transparent); }
th { font-size: .8rem; opacity: .7; font-weight: 600; }
td a { word-break: break-all; }
.field { margin: .6rem 0; }
.field label { display: block; font-size: .8rem; opacity: .7; }
textarea, input[type=text] { width: 100%; font: inherit; padding: .5rem; color: inherit;
         border-radius: .4rem; border: 1px solid color-mix(in srgb, currentColor 35%, transparent);
         background: color-mix(in srgb, currentColor 4%, transparent); }
textarea { min-height: 9rem; }
img.preview { max-width: 100%; border-radius: .5rem; }
.excerpt { opacity: .8; font-style: italic; }
.empty { opacity: .7; }
"""


def nav_html(active: str = "") -> str:
    """The top navigation bar, marking `active` as the current page."""
    links = []
    for key, href, label in NAV:
        cls = ' class="active"' if key == active else ""
        links.append(f'<a href="{href}"{cls}>{html.escape(label)}</a>')
    return f'<nav><span class="brand">social-bot</span>{"".join(links)}</nav>'


def notice_html(message: str = "", private: bool = False) -> str:
    """The flash message and the private-mode banner, both optional."""
    parts: list[str] = []
    if message:
        parts.append(f'<div class="notice">{html.escape(message)}</div>')
    if private:
        parts.append(
            '<div class="notice"><strong>Private mode</strong> — posts are '
            "unpublished and visible to page admins only.</div>"
        )
    return "".join(parts)


def badge(state: str) -> str:
    return f'<span class="badge">{html.escape(state)}</span>'


def layout(
    title: str,
    body: str,
    *,
    active: str = "",
    message: str = "",
    private: bool = False,
    head: str = "",
) -> str:
    """Wrap `body` in the shared document, navigation, and notices."""
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n{head}"
        f"<style>{_CSS}</style>\n</head>\n<body>\n"
        f"{nav_html(active)}\n{notice_html(message, private)}\n{body}\n"
        "</body>\n</html>\n"
    )
