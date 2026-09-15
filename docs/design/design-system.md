# Design system

How the operator UI looks and how to change it without breaking it. The visual
language is **"editorial factory floor"**: warm paper surfaces, near-black ink,
one deep petrol-teal signal colour reserved for the primary action and the
pipeline stage that needs a human, and strictly semantic green/amber/red for
state. Neutrals are warm (tinted toward the accent hue) so surfaces read as
authored rather than empty.

## The single source of truth

Everything the browser gets comes from **`src/social_bot/ui.py`**:

| Export | What it is |
|---|---|
| `_CSS` | The entire stylesheet. There is no other CSS in the app. |
| `layout(title, body, …)` | The document shell: `<head>`, `<style>`, nav, notices. Every page returns through it. |
| `nav_html(active)` | The top navigation. `active` is a `NAV` key. |
| `badge(state)` | A state chip; the label is slugified into a `badge-*` class. |
| `notice_html(message, private, kind)` | Flash messages and the private-mode banner. |
| `favicon_svg()` | The site icon: the brand mark as an SVG, its colours read back out of `_CSS`'s `--accent` / `--accent-fg` (light and dark). `web.py` serves it at `/favicon.svg`; `layout()` links it. |
| `NAV`, `BRAND`, `BRAND_EYEBROW` | Navigation entries and the wordmark. |

Page modules render **fragments only** and hand them to `layout()`:
`dashboard_html.py` (Factory, Post queue, Published, Status), `draft_html.py` (Review queue,
Draft), `destinations/facebook/feed_html.py` (Feed). No page defines its own CSS,
and no page writes an inline `style="…"` (a test enforces this). Core page
modules never import a platform module: the dashboard takes a pre-rendered
`feed_section` from `web.py`, which builds it from the destination reader.

**Rules for a new page or component**

1. Compose from the shared classes below. If a page needs markup, reuse
   `.panel` / `.stack` / `.cols` / `.cmdbar` etc.
2. If you need a new look, add a class to `ui._CSS` — never put CSS in a page
   module. Use the existing tokens; don't hard-code colours or sizes.
3. Run the design tests (below). They fail on a class with no rule, a token
   that isn't defined, or a badge state with no colour.

## Tokens

All colour and shape comes from CSS custom properties on `:root`, overridden
for dark mode inside `@media (prefers-color-scheme: dark)`. Referencing the
variable (not its value) is what makes dark mode and re-theming work.

| Token | Role |
|---|---|
| `--bg` | App background (with a faint accent radial). |
| `--surface`, `--surface-2` | Panel/card surface, and the inset/hover surface. |
| `--border`, `--border-strong` | Hairline dividers; control edges and emphasis. |
| `--fg`, `--ink-2`, `--muted` | Primary ink, secondary ink, muted captions. |
| `--accent`, `--accent-2`, `--accent-soft`, `--accent-fg` | The signal: primary action, focus, the focused pipeline stage; hover; tint surface; text on the signal. |
| `--ok`, `--warn`, `--danger` | Success, warning, danger — state only, never decoration. |
| `--radius`, `--radius-sm`, `--radius-lg` | 7px controls, 4px thumbs, 12px panels. |
| `--shadow` | The one soft elevation (dropped in dark mode). |
| `--badge-ink-base`, `--badge-ink-mix` | How a badge mixes its hue toward ink for contrast. |

Spacing follows a **1-4-9 rhythm**: 4px micro steps, 24px macro breaks. Counts,
times, and character counts use **tabular figures** so columns line up.

## Semantic rules (do not weaken)

- **The accent is reserved.** Teal marks the primary action and the pipeline
  stage that needs a human; it is not a generic highlight. Green/amber/red mean
  state and nothing else.
- **State is carried three ways.** Every badge shows colour **and** a dot **and**
  a text label — never colour alone.
- **The primary action is singular.** One `btn-primary` per view.
- **Destructive actions are quiet.** `btn-danger` is an outline, not a filled red.
- **Panels are the unit of layout.** `_panel(label, body)` with an uppercase
  label head; the whole surface shares one radius and border.

## Component inventory

| Component | Classes | Built by |
|---|---|---|
| Panel with titled head | `.panel`, `.panel-head`, `.label`, `.panel-body` | local `_panel` |
| Two-column page | `.cols`, `.stack`, `.detail` | pages |
| Pipeline strip | `.pipeline`, `.stage`, `.is-focus` | `dashboard_html._pipeline` |
| Attention list | `.attn`, `.attn-row`, `.attn-ico`, `.attn-text` | `dashboard_html._attention` |
| Scheduler rows | `.sched`, `.sched-row`, `.sched-name`, `.sched-when` | `dashboard_html._run_line` |
| Key/value list | `.kv`, `.kv-row` | `dashboard_html._kv_rows` |
| Stat cards | `.cards`, `.card`, `.num`, `.sub` | `dashboard_html._card` |
| Buttons | `.btn`, `.btn-primary`, `.btn-quiet`, `.btn-danger`, `.btn-sm` | pages |
| State badge | `.badge`, `badge-*` | `ui.badge` |
| Dot + pill | `.dot`, `.dot-ok/warn/danger`, `.pill` | pages |
| Notices | `.notice`, `.notice-ok/warn/error` | `ui.notice_html` |
| Segmented filter | `.seg`, `.seg-item`, `.count` | `draft_html._segment` |
| Source chips | `.chip`, `.chip-active` | `draft_html._chip` |
| Review row | `.qrow`, `.qthumb`, `.qbody`, `.qtitle`, `.qmeta`, `.qpreview` | `draft_html._draft_card` |
| Post queue (`/queue`) | `.qrow-manage`, `.qrow-main`, `.qmove`, `.qgrip`, `.qrow-dragging`, `.qfoot`, `.pill.is-next` | `dashboard_html.render_queue_html` / `_queue_panel` |
| Pagination | `.pager` | `draft_html._pagination_bar` |
| Stepper | `.stepper`, `.step`, `.is-done`, `.is-now` | `draft_html._stepper` |
| Facebook preview | `.fb-preview`, `.head`, `.avatar`, `.meta`, `.name`, `.when`, `.body`, `.tags`, `.media` | `draft_html` |
| Sticky action bar | `.action-bar`, `.spacer`, `.hint` | `draft_html` |
| Feed rows | reuse the review row (`.qlist`, `.qrow`, `.qthumb`, …) | `feed_html.render_feed_section` (title from `caption.split_title`) |
| Table | element `table`, `th`, `td` | `dashboard_html._table` |

## Accessibility

- Every interactive control is at least 44px tall (`.chip` and `.bar` included).
- `:focus-visible` draws a 2px accent outline everywhere.
- Decorative dots and marks are `aria-hidden`; notices carry `role="status"`.
- Dark mode is a token override, not a second stylesheet; the token *names* are
  identical in both themes (a test asserts no dark-only token).
- Links that are the only affordance (`.permalink`, `.crumbs`, `.next`) are real
  anchors, and the review list is plain links so it works without JavaScript.
- The queue reorder controls are progressive: a managed row's drag-and-drop is a
  script, but each row also carries **Top / Up / Down** submit buttons (plain
  forms, disabled at the ends), so the feature works with no JavaScript at all.
  The controls sit outside the row's link — an interactive control can't nest in
  an `<a>` — and the `.qmove` wrapper is a `div`, because a `<form>` is not
  phrasing content.
- The queue's **Next to post** pill (`.pill.is-next`) is the one place the accent
  tints a row: it marks the draft that actually posts next, the same way
  `.stage.is-focus` marks the stage being worked on. It is a tint, never a
  second accent button.

## The styleframe (generated preview)

`docs/design/styleframe.html` is a single-file styleguide: every operator page
rendered by the app's own render functions, plus a **Foundations** tab showing
the tokens and components. It is **generated, never hand-edited**:

```sh
.venv/bin/python scripts/build_styleframe.py
```

`src/social_bot/styleframe.py:render_styleframe()` calls the real renderers and
embeds `ui._CSS`, so it cannot show a look the app doesn't have. A test asserts
the committed file matches the generator byte for byte — if you change a page or
the stylesheet and forget to regenerate, the suite fails and tells you the
command.

## Tests that hold it together

`tests/test_design_system.py`:

- every CSS custom property referenced in `_CSS` is defined;
- no dark-only tokens;
- every class emitted by a rendered page has a rule in `_CSS`;
- no page writes an inline `style="…"` and no page module contains a styling
  literal (`<style>`, `style=`, a hex colour, `rgb()`/`hsl()`);
- every page embeds exactly one stylesheet — `ui._CSS`;
- every rendered page and the styleframe are well-formed HTML;
- every draft state and every labelled badge has a `badge-*` colour rule;
- the committed styleframe is current and embeds the live stylesheet;
- the styleframe contains no unstyled classes.
