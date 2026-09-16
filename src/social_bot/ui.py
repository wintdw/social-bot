"""Shared operator-UI chrome: stylesheet, navigation, and page layout.

Pure rendering (no network, no fastapi) so every page module — dashboard,
review, published, status, feed — composes the same look and the same top
navigation. Dynamic content is escaped here or by the caller.

The visual language is "editorial factory floor": warm paper surfaces, near-black
ink, one deep petrol-teal signal colour reserved for the primary action and the
pipeline stage needing a human, and strictly semantic green/amber/red for state.
Neutrals are warm (tinted toward the accent hue) so surfaces read as authored
rather than empty. Counts, times and character counts use tabular figures so
columns line up.
"""

from __future__ import annotations

import html
import re

from .drafts import parse_when

# The product wordmark. The UI is "Social Content Factory"; "Atento Education"
# is the account it operates, shown as an eyebrow above the name.
BRAND = "Social Content Factory"
BRAND_EYEBROW = "Atento Education"

# (key, href, label); `key` is the `active` value a page passes to layout().
NAV = (
    ("dashboard", "/", "Factory"),
    ("review", "/review", "Review queue"),
    ("queue", "/queue", "Post queue"),
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

# Spacing follows the 1-4-9 rhythm: micro steps are 4px, macro breaks are 24px.
_CSS = """
:root {
  color-scheme: light dark;
  --bg: #f6f3ed;
  --surface: #ffffff;
  --surface-2: #f1ece2;
  --fg: #171a19;
  --ink-2: #39423e;
  --muted: #616963;
  --border: #e1dacd;
  --border-strong: #cbc2b1;
  --accent: #0e6b64;
  --accent-2: #0b5852;
  --accent-soft: #dcece9;
  --accent-fg: #ffffff;
  --badge-ink-base: #171a19;
  --badge-ink-mix: 86%;
  --danger: #b03628;
  --ok: #2c7a4b;
  --warn: #9c6200;
  --radius: 7px;
  --radius-sm: 4px;
  --radius-lg: 12px;
  --shadow: 0 1px 2px rgba(23, 26, 25, .05);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1312;
    --surface: #171c1b;
    --surface-2: #1e2524;
    --fg: #e9e6df;
    --ink-2: #c6cbc7;
    --muted: #969e99;
    --border: #28302e;
    --border-strong: #3a4541;
    --accent: #46b3a6;
    --accent-2: #6ac7bb;
    --accent-soft: #16302c;
    --accent-fg: #06201d;
    --badge-ink-mix: 100%;
    --danger: #e6756a;
    --ok: #58be7c;
    --warn: #d9a63f;
    --shadow: none;
  }
}
* { box-sizing: border-box; }
body { font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
       background: radial-gradient(1200px 600px at 100% -10%,
                     color-mix(in srgb, var(--accent) 7%, transparent), transparent 60%),
                   var(--bg);
       color: var(--fg); margin: 0 auto; padding: 0 1rem 4rem;
       max-width: 78rem; line-height: 1.5; -webkit-font-smoothing: antialiased; }
a { color: var(--accent); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
h1 { font-size: 1.6rem; margin: 0; line-height: 1.25; letter-spacing: -.02em; font-weight: 650; }
h2 { font-size: 1rem; margin: 0; line-height: 1.3; font-weight: 650; }
h3 { font-size: .9rem; margin: .75rem 0 0; font-weight: 650; }
p { margin: 0; }

/* ---------- top bar ---------- */
nav { display: flex; flex-wrap: wrap; align-items: center; gap: 1.25rem;
      min-height: 62px; padding: .6rem 0; margin-bottom: 1.5rem;
      border-bottom: 1px solid var(--border); }
nav .brand { display: flex; align-items: center; gap: .75rem; text-decoration: none;
             color: inherit; }
nav .brand-mark { width: 34px; height: 34px; border-radius: var(--radius); display: grid;
                  place-items: center; background: var(--accent); color: var(--accent-fg);
                  font-weight: 800; font-size: 1rem; flex: 0 0 auto;
                  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent-fg) 18%, transparent); }
nav .brand-text { display: flex; flex-direction: column; line-height: 1.15; }
nav .brand-eyebrow { font-size: .7rem; letter-spacing: .14em; text-transform: uppercase;
                     color: var(--muted); font-weight: 650; }
nav .brand-name { font-weight: 700; letter-spacing: -.02em; white-space: nowrap; }
nav .links { display: flex; flex-wrap: wrap; gap: .25rem; margin-left: auto; }
nav a.tab { padding: .6rem .85rem; min-height: 44px; display: inline-flex; align-items: center;
            border-radius: var(--radius); text-decoration: none; color: var(--ink-2);
            font-weight: 550; position: relative; }
nav a.tab:hover { background: var(--surface-2); color: var(--fg); }
nav a[aria-current="page"] { color: var(--accent); font-weight: 700; }
nav a[aria-current="page"]::after { content: ""; position: absolute; left: .85rem;
            right: .85rem; bottom: .3rem; height: 2px; background: var(--accent);
            border-radius: 2px; }

/* ---------- status dots + pills ---------- */
.dot { width: 7px; height: 7px; border-radius: 50%; background: var(--muted);
       display: inline-block; flex: 0 0 auto; }
.dot-ok { background: var(--ok); }
.dot-warn { background: var(--warn); }
.dot-danger { background: var(--danger); }
.pill { display: inline-flex; align-items: center; gap: .4rem; font-size: .78rem;
        border: 1px solid var(--border); background: var(--surface); color: var(--ink-2);
        padding: .2rem .6rem; border-radius: 999px; white-space: nowrap;
        font-variant-numeric: tabular-nums; }
/* The draft that goes out next, in the post queue: the same accent tint the
   pipeline strip gives the stage you are working on now. */
.pill.is-next { border-color: color-mix(in srgb, var(--accent) 45%, transparent);
                background: var(--accent-soft);
                color: color-mix(in srgb, var(--accent) 78%, var(--fg)); font-weight: 650; }

/* ---------- page header ---------- */
header { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between;
         gap: 1rem; margin-bottom: 1.5rem; }
header .sub, .meta { color: var(--muted); font-size: .85rem; margin-top: .25rem;
                     font-variant-numeric: tabular-nums; }
.muted { color: var(--muted); font-size: .85rem; }
.empty { color: var(--muted); }
.excerpt { color: var(--ink-2); font-size: .85rem; }
.head-meta { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; margin-top: .4rem; }
.head-meta .next { margin-left: auto; font-size: .85rem; text-decoration: none; }
.head-meta .next:hover { text-decoration: underline; }
.back, .crumbs { display: inline-block; margin-bottom: .5rem; font-size: .85rem;
                 color: var(--muted); text-decoration: none; }
.back:hover, .crumbs:hover { color: var(--fg); }

/* ---------- notices ---------- */
.notice { padding: .7rem .9rem; margin-bottom: 1rem; border: 1px solid var(--border);
          border-left: 4px solid var(--muted); border-radius: var(--radius);
          background: var(--surface); }
.notice-ok { border-left-color: var(--ok); }
.notice-warn { border-left-color: var(--warn); }
.notice-error { border-left-color: var(--danger); }
.lint-list { margin: .5rem 0 0; padding-left: 1.1rem; display: grid; gap: .25rem;
             font-size: .85rem; color: var(--ink-2); }

/* ---------- pipeline strip ---------- */
.pipeline { display: grid; grid-template-columns: repeat(4, 1fr);
            border: 1px solid var(--border); border-radius: var(--radius-lg); overflow: hidden;
            background: var(--surface); box-shadow: var(--shadow); margin-bottom: 1.5rem; }
.stage { padding: 1rem 1rem .85rem; position: relative; border-right: 1px solid var(--border); }
.stage:last-child { border-right: 0; }
.stage-name { font-size: .7rem; letter-spacing: .12em; text-transform: uppercase;
              color: var(--muted); font-weight: 700; display: flex; align-items: center;
              gap: .4rem; }
.stage-num { font-size: 2.1rem; font-weight: 750; letter-spacing: -.03em; line-height: 1.15;
             margin-top: .4rem; font-variant-numeric: tabular-nums; }
.stage-sub { font-size: .8rem; color: var(--muted); margin-top: .15rem;
             font-variant-numeric: tabular-nums; }
.stage.is-focus { background: var(--accent-soft); }
.stage.is-focus .stage-num, .stage.is-focus .stage-name { color: var(--accent); }
.stage.is-focus .stage-sub { color: color-mix(in srgb, var(--accent) 72%, var(--fg)); }
.stage + .stage::before { content: ""; position: absolute; left: -5px; top: 50%; width: 8px;
              height: 8px; border-top: 1.5px solid var(--border-strong);
              border-right: 1.5px solid var(--border-strong);
              transform: translateY(-50%) rotate(45deg); background: var(--surface); }

/* ---------- layout ---------- */
.cols { display: grid; grid-template-columns: minmax(0, 1.85fr) minmax(0, 1fr);
        gap: 1.5rem; align-items: start; }
.stack { display: flex; flex-direction: column; gap: 1.5rem; min-width: 0; }
.panel { border: 1px solid var(--border); border-radius: var(--radius-lg);
         background: var(--surface); box-shadow: var(--shadow); min-width: 0; }
.panel-head { display: flex; align-items: center; justify-content: space-between; gap: .75rem;
              padding: .75rem 1rem; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
.panel-head .label, .section-label { font-size: .7rem; letter-spacing: .12em;
              text-transform: uppercase; color: var(--muted); font-weight: 700; }
.panel-body { padding: 1rem; }
.section-label { display: block; margin-bottom: .75rem; }

/* ---------- stat cards (status) ---------- */
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
         gap: .75rem; margin-bottom: 1.5rem; }
.card { border: 1px solid var(--border); border-radius: var(--radius-lg); padding: .7rem .9rem;
        background: var(--surface); box-shadow: var(--shadow); }
.card .num { font-size: 1.6rem; font-weight: 750; line-height: 1.2; letter-spacing: -.02em;
             font-variant-numeric: tabular-nums; }
.card .label { font-size: .8rem; color: var(--muted); }
.card .sub { font-size: .78rem; color: var(--muted); margin-top: .15rem; }

/* ---------- attention list ---------- */
.attn { display: flex; flex-direction: column; }
.attn-row { display: flex; align-items: center; gap: .75rem; padding: .75rem 1rem;
            border-bottom: 1px solid var(--border); flex-wrap: wrap; }
.attn-row:last-child { border-bottom: 0; }
.attn-ico { width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center;
            flex: 0 0 auto; font-size: .8rem; font-weight: 800;
            background: var(--surface-2); color: var(--ink-2); }
.attn-ico.act { background: var(--accent); color: var(--accent-fg); }
.attn-ico.warn { background: color-mix(in srgb, var(--warn) 18%, transparent);
                 color: var(--warn); }
.attn-text { flex: 1 1 14rem; min-width: 0; }
.attn-text strong { font-weight: 650; }
.attn-text .small { display: block; color: var(--muted); font-size: .8rem; }

/* ---------- scheduler rows + key/value ---------- */
.sched, .kv { display: flex; flex-direction: column; }
.sched-row { display: grid; grid-template-columns: 12px 1fr auto; align-items: center;
             gap: .75rem; padding: .7rem 1rem; border-bottom: 1px solid var(--border); }
.sched-row:last-child { border-bottom: 0; }
.sched-name { font-weight: 600; min-width: 0; }
.sched-name .small { display: block; font-weight: 400; color: var(--muted); font-size: .8rem; }
.sched-when { font-size: .8rem; color: var(--muted); font-variant-numeric: tabular-nums;
              text-align: right; white-space: nowrap; }
.kv-row { display: flex; align-items: baseline; justify-content: space-between; gap: .75rem;
          padding: .5rem 0; border-bottom: 1px dashed var(--border); }
.kv-row:last-child { border-bottom: 0; }
.kv-row dt { color: var(--muted); font-size: .85rem; }
.kv-row dd { margin: 0; font-weight: 600; font-variant-numeric: tabular-nums;
             text-align: right; }

/* ---------- image job rows ---------- */
/* Rows, not a table: the job panel is a narrow column, where a five-column
   table wrapped the id, the badge, and the timestamps to unreadable pieces. */
.joblist { display: flex; flex-direction: column; }
.job { display: grid; gap: .3rem; padding: .7rem 1rem; min-width: 0;
       border-bottom: 1px solid var(--border); }
.job:last-child { border-bottom: 0; }
.job-top { display: flex; align-items: center; gap: .5rem; min-width: 0; }
.job-name { min-width: 0; font-weight: 650; font-size: .85rem; color: var(--fg);
            text-decoration: none; overflow: hidden; text-overflow: ellipsis;
            white-space: nowrap; }
.job-name:hover { text-decoration: underline; }
.job-meta { font-size: .78rem; color: var(--muted); font-variant-numeric: tabular-nums; }
.job-error { font-size: .78rem; color: var(--danger); overflow-wrap: anywhere; }

/* ---------- controls ---------- */
.controls, .cmdbar, .toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; }
.controls { margin-bottom: 1.5rem; }
.toolbar { margin-bottom: 1rem; }
.toolbar .spacer { margin-left: auto; }
button, .btn { font: inherit; display: inline-flex; align-items: center; justify-content: center;
               gap: .4rem; min-height: 2.75rem; padding: .5rem 1rem; border-radius: var(--radius);
               border: 1px solid var(--border-strong); background: var(--surface); color: var(--fg);
               cursor: pointer; text-decoration: none; font-weight: 600;
               transition: background .14s ease, border-color .14s ease; }
button:hover, .btn:hover { background: var(--surface-2); }
button:disabled { opacity: .55; cursor: not-allowed; }
.btn-primary, button.btn-primary { background: var(--accent); border-color: var(--accent);
               color: var(--accent-fg); }
.btn-primary:hover, button.btn-primary:hover { background: var(--accent-2);
               border-color: var(--accent-2); }
.btn-quiet { background: transparent; border-color: transparent; color: var(--ink-2);
             font-weight: 550; }
.btn-quiet:hover { background: var(--surface-2); color: var(--fg); }
.btn-danger { background: transparent; color: var(--danger);
              border-color: color-mix(in srgb, var(--danger) 42%, var(--border)); }
.btn-danger:hover { background: color-mix(in srgb, var(--danger) 10%, transparent); }
.btn-sm { min-height: 2.25rem; padding: .35rem .75rem; font-size: .85rem; }
form { display: inline; }
.form-block { display: block; }

/* ---------- filters: status as a segmented control, source as chips ---------- */
.filters { display: flex; flex-direction: column; gap: 1rem; margin-bottom: 1.25rem; }
.filter-row { display: flex; flex-wrap: wrap; align-items: center; gap: .4rem; }
.filter-label { font-size: .7rem; text-transform: uppercase; letter-spacing: .1em;
                color: var(--muted); font-weight: 700; min-width: 3.6rem; }
.seg { display: inline-flex; max-width: 100%; border: 1px solid var(--border);
       border-radius: 999px; background: var(--surface); padding: 3px;
       overflow-x: auto; scrollbar-width: none; }
.seg::-webkit-scrollbar { display: none; }
.seg-item { display: inline-flex; align-items: center; gap: .4rem; padding: .4rem .9rem;
            min-height: 2.25rem; border-radius: 999px; font-size: .85rem; font-weight: 600;
            text-decoration: none; color: var(--ink-2); background: transparent;
            white-space: nowrap; flex: 0 0 auto; }
.seg-item:hover { background: var(--surface-2); color: var(--fg); }
.seg-item[aria-current="true"] { background: var(--accent); color: var(--accent-fg); }
.seg-item .count { font-variant-numeric: tabular-nums; opacity: .75; font-size: .8rem; }
.seg-item[aria-current="true"] .count { opacity: .88; }
.chip { display: inline-flex; align-items: center; gap: .35rem; padding: .25rem .7rem;
        min-height: 2.75rem; border: 1px solid var(--border); border-radius: 999px;
        font-size: .82rem; text-decoration: none; color: var(--ink-2);
        background: var(--surface); }
.chip:hover { background: var(--surface-2); color: var(--fg); }
.chip-active { background: var(--accent); border-color: var(--accent); color: var(--accent-fg);
               font-weight: 600; }
.chip .count { font-size: .72rem; opacity: .75; font-variant-numeric: tabular-nums; }
.chip-active .count { opacity: .88; }
.search-form { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem;
               margin-bottom: 1rem; }
.field-inline { display: inline-flex; align-items: center; gap: .5rem; }

/* ---------- form controls ---------- */
.field { margin: .85rem 0; }
.field label, .field-label { display: block; font-size: .7rem; font-weight: 700;
        letter-spacing: .1em; text-transform: uppercase; color: var(--muted);
        margin-bottom: .4rem; }
textarea, input[type=text], input[type=search], select {
        font: inherit; width: 100%; padding: .55rem .6rem; color: var(--fg);
        border-radius: var(--radius); border: 1px solid var(--border);
        background: var(--surface-2); }
input[type=search], select { min-height: 2.75rem; }
textarea { min-height: 14rem; resize: vertical; line-height: 1.6; }
.field-hint { font-size: .78rem; color: var(--muted); margin-top: .3rem; }
.countbar { display: flex; align-items: center; gap: .75rem; margin-top: .4rem;
            font-size: .8rem; color: var(--muted); font-variant-numeric: tabular-nums;
            flex-wrap: wrap; }
img.preview { max-width: 100%; border-radius: var(--radius-lg); }

/* ---------- badges: state carried by colour AND a dot AND the label ---------- */
.badge { display: inline-flex; align-items: center; gap: 5px; font-size: .7rem;
         text-transform: uppercase; letter-spacing: .04em; font-weight: 700;
         padding: .15rem .5rem; border-radius: 999px; white-space: nowrap;
         border: 1px solid color-mix(in srgb, var(--badge, var(--muted)) 42%, transparent);
         background: color-mix(in srgb, var(--badge, var(--muted)) 12%, transparent);
         color: var(--badge, var(--muted));
         color: color-mix(in srgb, var(--badge, var(--muted)) var(--badge-ink-mix),
                          var(--badge-ink-base)); }
.badge::before { content: ""; width: 6px; height: 6px; border-radius: 50%;
                 background: currentColor; flex: 0 0 auto; }
.badge-extracted { --badge: var(--warn); }
.badge-ai-draft, .badge-approved { --badge: var(--accent); }
.badge-posted, .badge-public { --badge: var(--ok); }
.badge-rejected { --badge: var(--danger); }
.badge-private { --badge: var(--warn); }
.badge-valid { --badge: var(--ok); }
.badge-invalid { --badge: var(--danger); }
.badge-unknown, .badge-running, .badge-skipped { --badge: var(--warn); }
.badge-done, .badge-no-change { --badge: var(--ok); }
.badge-failed { --badge: var(--danger); }
.badge-source { --badge: var(--muted); text-transform: none; letter-spacing: 0; font-weight: 600; }
.badge-source::before { display: none; }

/* ---------- tables ---------- */
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { text-align: left; padding: .5rem; vertical-align: top;
         border-bottom: 1px solid var(--border); overflow-wrap: anywhere; }
th { font-size: .75rem; color: var(--muted); font-weight: 700;
     text-transform: uppercase; letter-spacing: .08em; }
td { font-variant-numeric: tabular-nums; }
td a, .permalink { word-break: break-all; }
a.permalink { font-size: .82rem; }

/* ---------- queue + feed rows (shared) ---------- */
.qlist { display: flex; flex-direction: column; }
.qrow { display: grid; grid-template-columns: 76px minmax(0, 1fr) auto; gap: 1rem;
        align-items: center; padding: .75rem 1rem; border-bottom: 1px solid var(--border);
        text-decoration: none; color: inherit; }
.qrow:last-child { border-bottom: 0; }
.qrow:hover { background: var(--surface-2); }
.qthumb { width: 76px; height: 57px; border-radius: var(--radius-sm); overflow: hidden;
          position: relative; background: linear-gradient(135deg, var(--surface-2),
                      color-mix(in srgb, var(--accent) 16%, var(--surface-2))); }
.qthumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.qthumb.empty { background: repeating-linear-gradient(45deg, transparent, transparent 7px,
                      color-mix(in srgb, var(--border) 55%, transparent) 7px,
                      color-mix(in srgb, var(--border) 55%, transparent) 8px); }
.qthumb.empty::after { content: "no image"; position: absolute; inset: 0; display: grid;
        place-items: center; font-size: .62rem; letter-spacing: .04em; color: var(--muted);
        font-weight: 600; }
.qbody { min-width: 0; }
.qtitle { display: block; font-weight: 650; letter-spacing: -.01em; }
.qmeta { display: flex; flex-wrap: wrap; align-items: center; gap: .4rem; color: var(--muted);
         font-size: .8rem; margin-top: .3rem; }
.qpreview { display: block; color: var(--ink-2); font-size: .85rem; margin-top: .35rem;
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.qgo { color: var(--muted); font-size: 1rem; text-decoration: none; }
.qrow:hover .qgo { color: var(--accent); }

/* ---------- queue reorder (managed rows) ---------- */
/* A managed row is a div wrapping the row link plus its order controls: a
   control cannot live inside an <a>. Used by the post queue page, the one
   place the order is set. */
.qrow-manage { grid-template-columns: minmax(0, 1fr) auto; }
.qrow-manage.qrow-dragging { opacity: .5; }
.qrow-main { display: grid; grid-template-columns: 76px minmax(0, 1fr) auto; gap: 1rem;
             align-items: center; text-decoration: none; color: inherit; min-width: 0; }
.qmove { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end;
         gap: .4rem; }
.qmove form { display: inline-flex; gap: .25rem; }
.qgrip { cursor: grab; color: var(--muted); user-select: none; letter-spacing: -.12em;
         font-size: 1.1rem; line-height: 1; padding: 0 .15rem; }
.qmove-form { display: flex; flex-wrap: wrap; gap: .5rem; }
.qorder { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column;
          gap: .4rem; }
.qorder li { display: flex; align-items: baseline; gap: .5rem; font-size: .85rem;
             color: var(--muted); min-width: 0; }
.qorder li.is-current { color: var(--fg); font-weight: 650; }
.qrank { font-variant-numeric: tabular-nums; min-width: 1.25rem; }
.qname { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* The post queue's footer: the reorder hint on the left, the queue-level control
   on the right. Sits under the rows the way .pager sits under the review list. */
.qfoot { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
         gap: .75rem; padding: .75rem 1rem; border-top: 1px solid var(--border);
         color: var(--muted); font-size: .85rem; }
.pager { display: flex; align-items: center; justify-content: space-between; gap: .75rem;
         padding: .75rem 1rem; color: var(--muted); font-size: .85rem; flex-wrap: wrap;
         border-top: 1px solid var(--border); }
/* ---------- draft detail ---------- */
.detail-grid, .detail { display: grid;
        grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr); gap: 1.5rem;
        align-items: start; }
.hero { border-radius: var(--radius-lg); overflow: hidden; border: 1px solid var(--border);
        background: var(--surface-2); margin-bottom: 1.5rem; }
.hero img { display: block; width: 100%; aspect-ratio: 16 / 9; object-fit: cover; }
.composer { padding: 1rem; display: flex; flex-direction: column; gap: 1rem; }
.masthead { display: flex; align-items: center; gap: .75rem; flex-wrap: wrap; }
.rail-block { padding: 1rem; border-bottom: 1px solid var(--border); }
.rail-block:last-child { border-bottom: 0; }
.rail-block p { margin: .4rem 0; }
.notes { background: var(--surface-2); border-radius: var(--radius); padding: .75rem;
         font-size: .85rem; color: var(--ink-2); }
details.dna, details.voice { border: 1px solid var(--border); border-radius: var(--radius); padding: .6rem .9rem; }
details.dna summary, details.voice summary { cursor: pointer; font-size: .85rem; font-weight: 650; }
details.dna pre, details.voice pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 20rem;
        overflow: auto; margin: .6rem 0 0; font-size: .78rem; line-height: 1.55;
        color: var(--fg); }
.post-preview { border: 1px solid var(--border); border-radius: var(--radius-lg); overflow: hidden;
              background: var(--surface); }
.post-preview .head { display: flex; align-items: center; gap: .75rem; padding: .75rem 1rem; }
.post-preview .avatar { width: 40px; height: 40px; border-radius: 50%; background: var(--accent);
              color: var(--accent-fg); display: grid; place-items: center; font-weight: 800;
              flex: 0 0 auto; }
.post-preview .meta { display: grid; gap: .15rem; }
.post-preview .name { font-weight: 700; }
.post-preview .when { color: var(--muted); font-size: .8rem; }
.post-preview .body { padding: 0 1rem .5rem; white-space: pre-wrap; overflow-wrap: anywhere; }
.post-preview .tags { padding: .5rem 1rem .75rem; color: var(--accent); overflow-wrap: anywhere;
              border-top: 1px solid var(--border); font-size: .85rem; font-weight: 600; }
.post-preview .media { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; display: block;
              border-top: 1px solid var(--border); }
.action-bar { position: sticky; bottom: 0; z-index: 5; display: flex; flex-wrap: wrap;
              gap: .5rem; align-items: center; margin-top: 1.5rem; padding: .8rem .2rem;
              background: color-mix(in srgb, var(--bg) 88%, transparent);
              border-top: 1px solid var(--border); backdrop-filter: blur(8px); }
.action-bar .spacer { margin-left: auto; }
.action-bar .hint { color: var(--muted); font-size: .8rem; }

/* ---------- compose tool groups ---------- */
/* The Compose panel's secondary controls, grouped under a small label so the
   sticky action bar carries only the terminal actions (post / approve / save /
   reject). A tool that acts on a field sits under it. */
.toolgroup { display: flex; flex-direction: column; gap: .5rem; padding-top: 1rem;
             border-top: 1px dashed var(--border); }
.toolgroup-label { font-size: .7rem; letter-spacing: .1em; text-transform: uppercase;
                   color: var(--muted); font-weight: 700; }

/* ---------- stepper ---------- */
.stepper { display: flex; flex-direction: column; }
.step { display: grid; grid-template-columns: 20px 1fr; gap: .75rem; padding-bottom: .75rem;
        position: relative; }
.step:last-child { padding-bottom: 0; }
.step::before { content: ""; position: absolute; left: 9px; top: 20px; bottom: -2px; width: 1.5px;
        background: var(--border); }
.step:last-child::before { display: none; }
.step-dot { width: 20px; height: 20px; border-radius: 50%; display: grid; place-items: center;
        border: 1.5px solid var(--border-strong); background: var(--surface); font-size: .65rem;
        color: transparent; z-index: 1; }
.step.is-done .step-dot { background: var(--ok); border-color: var(--ok); color: var(--surface); }
.step.is-now .step-dot { background: var(--accent); border-color: var(--accent);
        color: var(--accent-fg); }
.step-name { font-weight: 600; font-size: .85rem; }
.step-name .small { display: block; font-weight: 400; color: var(--muted); font-size: .8rem; }
.step.is-now .step-name { color: var(--accent); }

/* ---------- responsive ---------- */
@media (max-width: 1040px) {
  .pipeline { grid-template-columns: repeat(2, 1fr); }
  .stage:nth-child(2) { border-right: 0; }
  .stage:nth-child(3), .stage:nth-child(4) { border-top: 1px solid var(--border); }
  .stage + .stage::before { display: none; }
  .cols, .detail-grid, .detail { grid-template-columns: 1fr; }
}
@media (max-width: 760px) {
  body { padding: 0 .75rem 3rem; }
  nav .links { order: 3; width: 100%; margin-left: 0; overflow-x: auto; }
  h1 { font-size: 1.3rem; }
  .pipeline { grid-template-columns: 1fr; }
  .stage { border-right: 0; border-top: 1px solid var(--border); }
  .stage:first-child { border-top: 0; }
  .stage-num { font-size: 1.7rem; }
  .qrow { grid-template-columns: 56px minmax(0, 1fr); }
  .qthumb { width: 56px; height: 44px; }
  .qgo { display: none; }

  .qrow-manage { grid-template-columns: minmax(0, 1fr); }
  .qrow-main { grid-template-columns: 56px minmax(0, 1fr); }
  .qmove { justify-content: flex-start; }

  .toolbar { align-items: stretch; }
  .seg { width: 100%; }
  .field-inline { flex: 1 1 100%; }
  input[type=search], select { width: 100%; }
  .toolbar .spacer { margin-left: 0; }
  .action-bar .spacer { margin-left: 0; }
}
"""

# The favicon is the nav's brand mark: the same accent tile and letter, so the
# browser tab carries the product's identity rather than a platform default.
# Its colours are read back out of `_CSS` above instead of being restated, so
# re-theming the app re-themes the icon. web.py serves it; `layout` links it.
_FAVICON_LINK = '<link rel="icon" type="image/svg+xml" href="/favicon.svg">'
_ROOT_BLOCK_RE = re.compile(r":root\s*\{(.*?)\}", re.S)
_DARK_ROOT_BLOCK_RE = re.compile(r"prefers-color-scheme:\s*dark\)\s*\{\s*:root\s*\{(.*?)\}", re.S)
_DECL_RE = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")


def _theme_tokens(block: str) -> dict[str, str]:
    """The custom properties declared in one `:root` block of the stylesheet."""
    return {name: value.strip() for name, value in _DECL_RE.findall(block)}


def favicon_svg() -> str:
    """The site icon: the brand mark as a self-contained SVG.

    `--accent` fills the rounded tile and `--accent-fg` the letter, taken from
    the stylesheet's own light and dark `:root` blocks, so the icon is the design
    system's own colour and not a hand-picked one. The base colours are plain
    attributes (they show even if `<style>` is dropped) and the dark-mode rule
    mirrors the token override the stylesheet already uses.
    """
    light = _theme_tokens(_ROOT_BLOCK_RE.search(_CSS).group(1))
    dark_match = _DARK_ROOT_BLOCK_RE.search(_CSS)
    dark = _theme_tokens(dark_match.group(1)) if dark_match else {}
    accent, fg = light["--accent"], light["--accent-fg"]
    dark_accent = dark.get("--accent", accent)
    dark_fg = dark.get("--accent-fg", fg)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" role="img" '
        f'aria-label="{html.escape(BRAND_EYEBROW)}">'
        f"<style>@media (prefers-color-scheme:dark){{rect{{fill:{dark_accent}}}"
        f"text{{fill:{dark_fg}}}}}</style>"
        f'<rect width="32" height="32" rx="7" fill="{accent}"/>'
        f'<text x="16" y="16" fill="{fg}" text-anchor="middle" '
        'dominant-baseline="central" font-family="system-ui, sans-serif" '
        f'font-size="18" font-weight="800">A</text>'
        "</svg>"
    )


def nav_html(active: str = "") -> str:
    """The top navigation bar, marking `active` as the current page."""
    links = []
    for key, href, label in NAV:
        current = ' aria-current="page"' if key == active else ""
        links.append(f'<a class="tab" href="{href}"{current}>{html.escape(label)}</a>')
    return (
        '<nav><a class="brand" href="/">'
        '<span class="brand-mark" aria-hidden="true">A</span>'
        f'<span class="brand-text"><span class="brand-eyebrow">{html.escape(BRAND_EYEBROW)}</span>'
        f'<span class="brand-name">{html.escape(BRAND)}</span></span></a>'
        f'<span class="links">{"".join(links)}</span>'
        "</nav>"
    )


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


def fmt_when(value: str) -> str:
    """An item timestamp as local 'YYYY-MM-DD HH:MM' ('' when there is none).

    Returns the raw text when it can't be parsed — sources date their items
    several ways (RSS pubDate is RFC 822, Atom is ISO 8601). Shared by every
    row that dates itself, so the review list, the post queue, and the feed
    show the same stamp for the same item.
    """
    parsed = parse_when(value)
    if parsed is None:
        return str(value or "").strip()
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


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
        f"{_FAVICON_LINK}\n"
        f"<title>{html.escape(title)}</title>\n{head}"
        f"<style>{_CSS}</style>\n</head>\n<body>\n"
        f"{nav_html(active)}\n{notice_html(message, private, kind)}\n{body}\n"
        "</body>\n</html>\n"
    )
