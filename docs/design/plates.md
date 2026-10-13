# Plates: tokens and rules

A **plate** is the drawn image a post carries when it has no source cover: a
static HTML5 page (CSS plus inline SVG, no JavaScript) screenshotted to a
1080×1350 PNG. This page is the token set every plate draws from, so plates for
different posts look like one publication and no plate invents its own colours.

The tokens are the operator UI's own (`src/social_bot/ui.py`, `_CSS`, light
values). One palette for the whole project means a plate and the review page
that shows it agree. If Atento gets a separate brand palette later, change the
values here and in the plates, and say so in this file.

## Tokens

| Token | Hex | Use on a plate |
|---|---|---|
| `--bg` | `#f6f3ed` | Canvas. Every plate sits on it; no other background colour. |
| `--surface-2` | `#f1ece2` | A quiet area behind a group (for example the water, or the foundation band). |
| `--fg` | `#171a19` | Primary ink: headings, the main shape, key words. |
| `--ink-2` | `#39423e` | Secondary shapes and body-weight words. |
| `--muted` | `#616963` | Captions, node labels, small supporting words. |
| `--border-strong` | `#cbc2b1` | Outlines of empty or not-yet-true things. |
| `--accent` | `#0e6b64` | **Signal**: the one thing the post asks the reader to look at. |
| `--danger` | `#b03628` | **Loss / failure** only: what breaks, what gets lost. |

Rules:

1. Accent and danger are the only saturated colours. Accent marks the point of
   the image; danger marks a failure. Do not use them for decoration.
2. State is carried by shape or position as well as colour: a filled shape is
   "has it", an outlined shape is "does not". Colour alone never carries meaning.
3. Ink on paper for text. Text colour is `--fg` or `--muted`, never accent
   unless the word *is* the signal.
4. No gradients, shadows, or rounded cards. Flat fills and 3–4px strokes.

## Type

One family, the app's own stack, so the plate matches the UI:

```
font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
```

On the host the fallback is FreeSans / DejaVu Sans. Bold (700) is for the
headline and the one key line; regular for labels. No all-caps labels, no
italic accents.

Sizes on a 1080px canvas: headline ~100px, key line ~46px, label ~36–40px.
Nothing below 34px; the plate is read on a phone.

## Layout

- Content sits inside a 90px side margin.
- Words are minimal: a headline, one line per band, node or part labels. A
  plate that needs a paragraph is a caption's job, not the image's.
- Structure must encode the post's content (a sequence, a stack, a comparison),
  not decorate it. Before adding a number, a rule, or a label, check it says
  something the caption says.

## Making a plate

1. Read the caption; find the one idea the image must show.
2. Pick the shape that carries it (a stack, a comparison, a flow). Draw it in
   inline SVG with the tokens above.
3. Add the fewest words that name the parts.
4. Render with `browser_shot.html_to_png(html, dest, width=1080, height=1350)`
   and look at the PNG before the draft points at it.

Plate sources live in `data/review/plates/<draft-id>.html`; the PNGs in
`data/review/images/`. Both are git-ignored.
