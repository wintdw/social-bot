# Plate — the house style

A plate is a **static HTML5 page** drawn by hand for one post. It is laid out
from that post's own content, screenshotted to a 1080×1350 PNG, and the draft
points at the PNG (Graph only accepts raster). No JavaScript: the screenshot is
taken as the page loads.

## Where it lives

- `data/review/plates/<draft-id>.html` — the source. Git-ignored with the rest of
  `data/`.
- `src/social_bot/browser_shot.py` — `html_to_png(page, dest, width, height)`
  runs the host's Chromium headless. It never runs in the container.
- The PNG lands in `data/review/images/<draft-id>.png`, served at `/images/`.

## Look

- Paper `#f5f5f5`, ink `#2d3142`, one accent `#bf4520` for the idea the post
  turns on, muted `#4f5d75` / `#5a6580` for secondary text, rules at 14% ink.
- Sans-serif system stack (`FreeSans`, `DejaVu Sans`), text sized to read on a
  phone. Keep every label inside its box; check the PNG before attaching it.
- Text carries the argument. A plate is a diagram of the post's idea, not a
  decoration, and it should not invent parts the caption does not name.

Each post gets its own layout. Do not copy another post's plate.
