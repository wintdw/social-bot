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

# Flash-message kinds accepted by notice_html(); anything else falls back to info.
_NOTICE_KINDS = {
    "info": "",
    "success": " notice-ok",
    "warning": " notice-warn",
    "error": " notice-error",
}

_CSS = """
:root {
  color-scheme: light dark;
  --bg: #ffffff;
  --fg: #17181a;
  --muted: #5c6169;
  --surface: #f5f6f7;
  --surface-2: #e9ebee;
  --border: #d6d9de;
  --accent: #1667d6;
  --accent-fg: #ffffff;
  --danger: #c0392b;
  --ok: #1a7f37;
  --warn: #8a6100;
  --radius: .5rem;
  --radius-lg: .75rem;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #101216;
    --fg: #e6e8ea;
    --muted: #9aa1ab;
    --surface: #1a1e24;
    --surface-2: #232932;
    --border: #333a44;
    --accent: #3b82f6;
    --accent-fg: #08121f;
    --danger: #ef6b6b;
    --ok: #56c271;
    --warn: #d8a93b;
  }
}
* { box-sizing: border-box; }
body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
       background: var(--bg); color: var(--fg);
       max-width: 60rem; margin: 0 auto; padding: 0 1rem 4rem; line-height: 1.5; }
a { color: var(--accent); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
nav { display: flex; flex-wrap: wrap; align-items: center; gap: .25rem;
      padding: .75rem 0; margin-bottom: 1.25rem;
      border-bottom: 1px solid var(--border); }
nav .brand { font-weight: 700; margin-right: .75rem; }
nav a { padding: .35rem .65rem; border-radius: var(--radius); text-decoration: none;
        color: var(--fg); opacity: .7; }
nav a:hover { opacity: 1; background: var(--surface); }
nav a[aria-current="page"] { opacity: 1; font-weight: 600; background: var(--surface-2); }
h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
h2 { font-size: 1.1rem; margin: 0 0 .6rem; }
h3 { font-size: .9rem; margin: 1rem 0 .3rem; }
header { padding-bottom: .9rem; margin-bottom: 1.25rem;
         border-bottom: 1px solid var(--border); }
.meta { color: var(--muted); font-size: .85rem; }
.muted { color: var(--muted); font-size: .85rem; }
.head-meta { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; margin-top: .3rem; }
.head-meta .next { margin-left: auto; font-size: .85rem; text-decoration: none; }
.head-meta .next:hover { text-decoration: underline; }
.back { display: inline-block; margin-bottom: .5rem; font-size: .85rem;
        color: var(--muted); text-decoration: none; }
.back:hover { color: var(--fg); }
.notice { padding: .7rem .9rem; margin-bottom: 1rem; border: 1px solid var(--border);
          border-left: 4px solid var(--muted); border-radius: var(--radius);
          background: var(--surface); }
.notice-ok { border-left-color: var(--ok); }
.notice-warn { border-left-color: var(--warn); }
.notice-error { border-left-color: var(--danger); }
.controls { display: flex; flex-wrap: wrap; gap: .75rem; align-items: center;
            margin: 1rem 0 1.5rem; }
.toolbar { display: flex; flex-wrap: wrap; gap: .75rem; align-items: center;
           margin-top: .75rem; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
         gap: .75rem; margin-bottom: 1.25rem; }
.card { border: 1px solid var(--border); border-radius: var(--radius-lg);
        padding: .7rem .9rem; background: var(--surface); }
.card .num { font-size: 1.4rem; font-weight: 700; line-height: 1.2; }
.card .label { font-size: .8rem; color: var(--muted); }
.card .sub { font-size: .78rem; color: var(--muted); margin-top: .15rem; }
button, .btn { font: inherit; display: inline-flex; align-items: center;
               justify-content: center; gap: .4rem; min-height: 2.75rem;
               padding: .5rem 1rem; border-radius: var(--radius);
               border: 1px solid var(--border); background: var(--surface);
               color: var(--fg); cursor: pointer; text-decoration: none; }
button:hover, .btn:hover { background: var(--surface-2); }
button:disabled { opacity: .55; cursor: not-allowed; }
.btn-primary, button.btn-primary { background: var(--accent); border-color: var(--accent);
               color: var(--accent-fg); font-weight: 600; }
.btn-primary:hover, button.btn-primary:hover { filter: brightness(1.07); background: var(--accent); }
.btn-quiet { background: transparent; border-color: transparent; color: var(--muted); }
.btn-quiet:hover { background: var(--surface); color: var(--fg); }
.btn-danger { background: transparent; color: var(--danger);
              border-color: color-mix(in srgb, var(--danger) 45%, var(--border)); }
.btn-danger:hover { background: color-mix(in srgb, var(--danger) 12%, transparent); }
form { display: inline; }
.form-block { display: block; }
article { padding: 1rem 0;
          border-bottom: 1px solid var(--border); }
article:last-child { border-bottom: none; }
article time { font-size: .8rem; color: var(--muted); }
article p { margin: .5rem 0; white-space: pre-wrap; }
article a { word-break: break-all; }
a.permalink { font-size: .82rem; word-break: break-all; }
.badge { display: inline-block; font-size: .7rem; text-transform: uppercase;
         letter-spacing: .05em; font-weight: 600; padding: .15rem .5rem;
         border-radius: 999px; color: var(--badge, var(--muted));
         border: 1px solid color-mix(in srgb, var(--badge, var(--muted)) 45%, transparent);
         background: color-mix(in srgb, var(--badge, var(--muted)) 12%, transparent); }
.badge-extracted { --badge: var(--warn); }
.badge-ai-draft, .badge-approved { --badge: var(--accent); }
.badge-posted, .badge-public { --badge: var(--ok); }
.badge-rejected { --badge: var(--danger); }
.badge-private { --badge: var(--warn); }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { text-align: left; padding: .45rem .5rem; vertical-align: top;
         border-bottom: 1px solid var(--border); }
th { font-size: .8rem; color: var(--muted); font-weight: 600; }
td a { word-break: break-all; }
.field { margin: .85rem 0; }
.field label { display: block; font-size: .8rem; font-weight: 600;
               color: var(--muted); margin-bottom: .3rem; }
textarea, input[type=text] { width: 100%; font: inherit; padding: .55rem .6rem;
         color: var(--fg); border-radius: var(--radius);
         border: 1px solid var(--border); background: var(--surface); }
textarea { min-height: 12rem; resize: vertical; }
.field-hint { font-size: .78rem; color: var(--muted); margin-top: .3rem; }
img.preview { max-width: 100%; border-radius: var(--radius-lg); }
.excerpt { color: var(--muted); font-style: italic; }
.empty { color: var(--muted); }
.detail-grid { display: grid;
               grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr);
               gap: 1.5rem; align-items: start; }
@media (max-width: 46rem) { .detail-grid { grid-template-columns: 1fr; } }
.panel { border: 1px solid var(--border); border-radius: var(--radius-lg);
         padding: 1rem 1.1rem; }
.post-media { margin: 0 0 1rem; aspect-ratio: 16 / 9; overflow: hidden;
              border-radius: var(--radius); background: var(--surface); }
.post-media img { width: 100%; height: 100%; object-fit: cover; display: block; }
.fb-preview { border: 1px solid var(--border); border-radius: var(--radius-lg);
              padding: .9rem 1rem; background: var(--surface); margin-bottom: .5rem; }
.fb-preview .body { white-space: pre-wrap; overflow-wrap: anywhere; }
.fb-preview .tags { margin-top: .6rem; color: var(--accent); overflow-wrap: anywhere; }
.rail h2 { font-size: .95rem; text-transform: uppercase; letter-spacing: .06em;
           color: var(--muted); }
.rail .source-link a { word-break: break-all; }
.rail p { margin: .5rem 0; }
.action-bar { position: sticky; bottom: 0; z-index: 5; display: flex; flex-wrap: wrap;
              gap: .6rem; align-items: center; margin-top: 1.5rem; padding: .8rem .2rem;
              background: color-mix(in srgb, var(--bg) 88%, transparent);
              border-top: 1px solid var(--border); backdrop-filter: blur(6px); }
.action-bar .spacer { margin-left: auto; }
details.dna { margin-top: 1.5rem; border: 1px solid var(--border);
              border-radius: var(--radius); padding: .6rem .9rem; }
details.dna summary { cursor: pointer; font-size: .85rem; font-weight: 600; }
details.dna pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 24rem;
                  overflow: auto; margin: .6rem 0 0; font-size: .8rem;
                  line-height: 1.55; color: var(--fg); }
"""


def nav_html(active: str = "") -> str:
    """The top navigation bar, marking `active` as the current page."""
    links = []
    for key, href, label in NAV:
        current = ' aria-current="page"' if key == active else ""
        links.append(f'<a href="{href}"{current}>{html.escape(label)}</a>')
    return f'<nav><span class="brand">social-bot</span>{"".join(links)}</nav>'


def notice_html(message: str = "", private: bool = False, kind: str = "info") -> str:
    """The flash message and the private-mode banner, both optional."""
    parts: list[str] = []
    if message:
        cls = _NOTICE_KINDS.get(kind, "")
        parts.append(f'<div class="notice{cls}" role="status">{html.escape(message)}</div>')
    if private:
        parts.append(
            '<div class="notice notice-warn"><strong>Private mode</strong>: posts are '
            "unpublished and visible to page admins only.</div>"
        )
    return "".join(parts)


def badge(state: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in str(state).lower()).strip("-")
    return f'<span class="badge badge-{slug}">{html.escape(state)}</span>'


def layout(
    title: str,
    body: str,
    *,
    active: str = "",
    message: str = "",
    private: bool = False,
    head: str = "",
    kind: str = "info",
) -> str:
    """Wrap `body` in the shared document, navigation, and notices."""
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n{head}"
        f"<style>{_CSS}</style>\n</head>\n<body>\n"
        f"{nav_html(active)}\n{notice_html(message, private, kind)}\n{body}\n"
        "</body>\n</html>\n"
    )
