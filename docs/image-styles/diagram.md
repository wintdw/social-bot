# Diagram plate — the house style

The `diagram` image style is a **code-drawn isometric plate**: a small scene of
real objects that shows how a system works. It is not an illustration and not a
prompt for one — `src/social_bot/diagram.py` draws it deterministically from the
`src/social_bot/iso.py` kit, so every box, card and cable sits exactly where the
code puts it, and every Vietnamese string renders exactly (no diacritics lost,
no stray lettering).

**One style, every post.** A plate is not designed per post: a *system* gets a
renderer, and every renderer draws the same way. When you add a system you add a
renderer, not a look.

## What a plate looks like

- **Warm paper, one accent.** The ground is `#f6f3ed` with a faint dot grid and a
  thin rounded frame. Ink is near-black, a single petrol-teal `#0e6b64` marks the
  part that carries the idea, a rust `#b0503a` marks a hazard. At most two
  colours per scene.
- **Objects, not boxes-and-arrows.** The reader understands the idea because they
  recognise the thing: a console, cabinets with a bay, a chest of drawers, a
  plinth. Never a labelled rectangle, never a floating slab.
- **Isometric solids.** Every part is a solid cuboid — three tone faces, the top
  lightest — painted back to front so nearer parts hide farther ones, each with a
  soft ground shadow. Nothing is a wireframe and nothing is see-through.
- **Words live in the margins.** The drawing carries no labels, arrows or
  captions. Up top: a kicker (the system), the title, and one line naming the
  question. Then for each row, a label and a ratio on the left and an icon with a
  verdict on the right.
- **Two rows, one reading.** The rows are the two settings being compared (e.g.
  `w:1` vs `w:majority`); the reader compares the *same* objects under each, so
  the difference is the only thing that moves.

## How a plate is built

- `iso.py` — the kit: `Iso.p` / `quad` / `box` / `shadow` / `line`, and
  `fit(bounds, rect)` to centre a known world box at whatever scale a row allows.
- `diagram.py` — one `render_<system>` per system, plus `diagram_kind(draft)`, the
  matcher that reads the draft's topic / title / excerpt and picks the renderer.
  A new system is a new renderer **plus a branch in `diagram_kind`**; a draft that
  matches no renderer renders **nothing** rather than borrowing a plate from
  another system — a wrong figure is worse than no figure.
- `diagram_html.py` — wraps that SVG in a bare page, and `browser_shot`
  screenshots it to the PNG the publisher uploads. There is one drawing, so the
  preview and the PNG cannot drift.

## Palette

| Token | Use |
|---|---|
| `_PAPER #f6f3ed` | the page |
| `_INK #171a19`, `_MUTED #616963` | text, frame, hairlines |
| `_ACCENT #0e6b64` | the part that carries the idea, and the good verdict |
| `iso.TEAL / CREAM / SHELL / WOOD / INK` | materials, as (top, right, left, edge) |
| `iso.RUST #b0503a` | a hazard — the failure the plate is about |

Keep any new material or plate inside this palette and this grammar.
