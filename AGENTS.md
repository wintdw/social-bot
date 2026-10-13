# AGENTS.md — social-bot

Guidance for agents and humans working on this project. Read before touching
code or running anything.

## What this project is

A Python CLI that reads and writes a **Facebook Page through the official
Graph API** — no browser anywhere. `whoami` validates the access token and
lists manageable pages, `feed` fetches the page's own feed, `post` creates a
status/link/photo post, `refresh` caches the feed, `blog scan` queues new items
from source feeds as drafts, `blog masthead` backfills the series masthead onto existing captions,
`blog backfill-destinations` unions old drafts onto the configured destinations,
`blog publish` posts the human-approved queue on demand, and `serve` runs a
long-lived feed dashboard + a draft review UI + scheduled
refresh/scan/posting. Skeleton cloned from the voz-bot/otofun-bot family
(cli/config/tests/Docker layout); the crawl engine is replaced by
`destinations/facebook/api.py`, a ~150-line urllib Graph client.

**Detailed docs live in `docs/`** — read `docs/README.md` first (module map +
"where to work"), then `content-pipeline.md`, `operations.md`, `development.md`.

## Architecture

```
src/social_bot/
├── cli.py            # entry point (social-bot): whoami, destinations, feed, post, refresh, blog scan/localize-images/masthead/backfill-destinations/publish/topics/add-idea, serve
├── config.py         # DEFAULTS + config.yaml + credentials.yaml; per-destination token resolution
├── caption.py        # pure caption text rule: series masthead + hook row title
├── caption_lint.py   # advisory AI-tell checks on a caption (no auto-edit)
├── source.py         # pure parse of sitemap / RSS / Atom -> Item (no network)
├── source_api.py     # urllib source fetcher: retries + SourceError
├── ideas.py          # pure parse of the idea-topics file + slugify an idea title (systems, not feeds)
├── drafts.py         # Draft model + state machine + per-destination post records + atomic persistence
├── draft_pipeline.py # scan sources -> drafts; caption edits; publish (on demand + scheduled)
├── media.py          # local image store (served at /images/) + the bytes a post uploads
├── ui.py             # shared operator-UI chrome: stylesheet, nav, favicon, layout
├── styleframe.py     # generated design-system preview (docs/design/styleframe.html)
├── draft_html.py     # pure render of the /review queue + a draft detail page
├── dashboard_html.py # pure render of / (dashboard), /publish, /status (feed_section passed in)
├── web.py            # FastAPI operator UI + JSON API + refresh/scan/posting schedulers
├── destinations/     # ONE PACKAGE PER PLATFORM — the only platform-coupled code
│   ├── base.py       #   Publisher / AccountReader contracts, PublishResult, DestinationError
│   ├── registry.py   #   PUBLISHERS / READERS, publisher_for(), reader_for(), describe_all()
│   ├── facebook/     #   api.py (urllib Graph client), publisher.py, reader.py, feed.py, feed_html.py
│   └── linkedin/     #   publisher.py (posts via linkin-bot's POST /post gateway; text + image)
└── __init__.py
```

Flow: `load_config` merges `config.yaml` and `credentials.yaml` over `DEFAULTS`
→ each destination's token resolves (`--token` > `SOCIAL_BOT_<NAME>_TOKEN` >
`SOCIAL_BOT_TOKEN` > `credentials.yaml`) → the facebook `GraphApi` talks to
`https://graph.facebook.com/<version>/<path>` → `feed` renders through
`destinations/facebook/feed.py`; `post` sends `message` (+ optional `link`) to
`/{page}/feed`, or downloads the `--photo` image and uploads it as a multipart
`source` to `/{page}/photos`.
The core (pipeline, CLI, web, UI) reaches a platform only through
`destinations/registry.py` — no `facebook`/`linkedin` import outside `destinations/`.

`serve` flow: the FastAPI `lifespan` starts the schedulers; the refresh
loop calls `destinations.facebook:refresh_feed` (via `asyncio.to_thread`) at the
`--refresh-at` slots and on `POST /refresh`, writing
`data/feed/latest.{json,html}`, the scan loop calls
`draft_pipeline.py:scan_sources` at the `--scan-at` slots, and the posting loop
calls `draft_pipeline.py:publish_scheduled` at the `--publish-at` slots (from
`publish.post_at`; empty disables it), following any slot that actually posted
with a feed refresh so the new post shows up without waiting for the next
`--refresh-at`. The operator UI is
five HTML pages sharing the `ui.py` nav: `/` (dashboard — controls, counts,
scheduler state, and the cached feed rendered live from `latest.json`), `/review`
(the review queue list + a detail page), `/queue` (the post queue, its ordering
controls, and **Post approved now**), `/publish` (the audit log), and `/status`, plus the
generated brand icon at `/favicon.svg` (`/favicon.ico` redirects there).
web.py's time helpers are pure so tests need no fastapi/uvicorn.

Content pipeline flow: `scan_sources` fetches each `sources[]` feed
(`source_api.py`), parses it (`source.py`), and queues unseen items as
`EXTRACTED` drafts under `data/review/` (dedupe via `seen.json`); it runs on the
`--scan-at` schedule, on `POST /scan`, or via `blog scan`. Images need
nothing from the pipeline: a post uses its source article's own cover, or the
operator draws one — an HTML5 plate screenshotted to PNG (see **Drawn plates** below), or, selectively, an illustration with the `anatomy` skill.
Captions are written **by the operator in Claude**. The operator pastes the caption on `/review/{id}`; saving a non-empty caption moves the draft `extracted -> ai_draft`, and a human approves it there, which either posts immediately through a `destinations/` publisher adapter or — when `publish.post_at` slots are configured — queues the draft as `APPROVED` for the posting scheduler. **The app runs no LLM, no rewriter worker, and no retrieval (RAG).** The scan and refresh loops never post, and the posting loop never approves: it only posts drafts a human already approved. `publish.post_at: []` disables timed posting entirely, leaving approval as the only publish path.

**Caption writing uses the `humanizer-vi` skill** (`.claude/skills/humanizer-vi/SKILL.md`, project-scoped). Load it for any caption task, to strip AI-sounding patterns before the caption is pasted on `/review/{id}`. It rewrites wording only: facts, numbers, names and the series masthead stay unchanged, and no engagement bait is added. The operator still reads, approves and posts. The skill has not yet been tested on real captions.

**Idea seeds (`ideas`, not `sources[]`) are the other input.** A `sources[]` entry is a feed to repost; an `ideas.topics_file` line is a *system* (Elasticsearch, ClickHouse, Loki, MySQL, …) the operator writes an **original** Atento post about. The app never fetches docs and never generates ideas: the operator drafts an angle in Claude and queues it with `blog add-idea`, which lands as an `EXTRACTED` draft with `source: atento-original`, no URL and no source image — then follows the ordinary caption + human approval.

## Hard-won facts

- **Graph API v26.0** is current as of Sept 2026 (introduced 2026-07-29).
  Meta supports the current version plus two previous majors; `destinations.facebook.api_version`
  is configurable and pinned in `config.yaml`.
- The token is the whole auth story. It is **never in code or committed
  config**: passed via `SOCIAL_BOT_TOKEN` (global) / `SOCIAL_BOT_<NAME>_TOKEN`,
  `--token`, or `credentials.yaml` under `destinations.<name>.token`
  (git-ignored; template `credentials.example.yaml`). Required
  permissions: `pages_read_engagement` (feed), `pages_manage_posts` (post),
  `pages_show_list` (`whoami` page list). It expires — OAuth errors mean
  "mint a fresh one".
- The feed's `type` field is **deprecated** — asking for it returns
  `(#12) deprecate_post_aggregated_fields_for_attachement ... v3.3 and higher`.
  `FEED_FIELDS` requests `status_type` instead (e.g. `added_photos`,
  `mobile_status_update`); don't add `type` back.
- Feed `created_time` uses ISO-8601 with a **colon-less** offset (`+0000`);
  `parse_fb_datetime` inserts the colon before `fromisoformat`. `Z` is also
  accepted. Never "fix" this by naive string slicing.
- The Atento blog (`atento.vn/blog`) is Next.js and publishes **no RSS/Atom
  feed and no WordPress API**, and its `sitemap.xml` currently omits the blog
  posts entirely. The default source is therefore type `index`: it reads the
  listing page's JSON-LD `ItemList` (structured data, not CSS scraping) and
  dedupes on the **slug** — the site's dates are inconsistent, so never
  order/dedupe by date. `sitemap` and `rss` source types exist for other
  feeds. The host is intermittently flaky (504s), hence the retry/backoff in
  `source_api.py`.
- **A scan has no date window of its own — only `blog.max_scan`.** It queues the
  newest unseen items, so a feed exposing more entries than one scan takes
  (martinfowler's Atom is a 30-entry window against a cap of 12) is walked back
  another batch every scan: the draft count climbs daily long after the first
  run. `blog.max_age_days` (90 in `config.yaml`, `0` = off) is the window,
  applied **before** the cap so old entries can't consume the batch. A
  `published` date the scanner can't parse is kept, not dropped — an `index`
  item has none until enrichment, and an undated post can't be shown old.
- **Idea seeds are a separate input from `sources[]`.** A source is a feed to *repost* (URL, fetch, author credit); an idea is a *system to write about* (`ideas.topics_file`), and the post is **original**. Nothing is fetched and nothing generates ideas: the operator writes each one in Claude and queues it by hand with `blog add-idea`. Ideas dedupe by title slug against `data/ideas/seen.json`, carry no `url` and no source image, so no source-credit line and no "đọc đầy đủ tại comment" CTA apply.
- **Photo posts upload the image bytes** (a multipart `source` part); they are
  never a `url` for Graph to fetch — a remote host may not serve the file to
  Graph at all. Images live locally under the served `/images/` dir
  (`media.save`), and a remote source cover is downloaded *here* (`media.load`)
  before upload. See `media.py`.
- `blog localize-images` copies a still-remote non-source image into the store
  (`media.load` → `media.save`) and repoints the draft, so `/review` shows it
  again. It never renders, and it leaves a source's own cover alone (its remote
  URL is what keeps `image_is_generated` unambiguous). Idempotent — local images
  are skipped.
- **Drawn plates are HTML5, screenshotted to PNG.** A plate is a static HTML
  page (CSS, and inline SVG where a shape needs it), written by hand for one
  post and kept in `data/review/plates/` (git-ignored, like the rest of `data/`).
  No JavaScript: the screenshot is taken as the page loads, so a script could
  be captured half-drawn. `browser_shot.html_to_png` screenshots it to the PNG
  the draft points at (Graph only accepts raster), through the host's Chromium
  (`SOCIAL_BOT_CHROMIUM`, else the Playwright cache, else `chromium` on PATH).
  The renderer runs on the **host**, never in the container. A missing browser
  never blocks anything; the draft just keeps its existing image.
  Nothing is shared between plates: each post gets its own layout drawn from its
  own content.
- **The source image is kept as `Draft.source_image`** (written at scan, never
  written by drawing), so a replaced image can always be undone:
  `draft_pipeline.restore_source_image` puts the post's own picture back and the
  **Restore source image** button on `/review/{id}` (`POST
  /review/{id}/restore-image`) offers it whenever `image_is_generated` is true —
  exact via `source_image`, and for a draft scanned before it was recorded, by
  recognising a locally stored path (`/images/...`). A draft with no
  stored original gets one by re-reading the source page once (as scan
  enrichment does) and keeping it. The restore never touches the caption.
- **Every caption opens with a series masthead** from `publish.mastheads` (config.yaml: `[Học cùng Atento]`, `[Đọc báo cùng Atento]`, `[Mỗi ngày 1 kiến thức mới]`) on its own line, before the hook — the recognition cue a new reader learns. The label is a **content judgment, not a source default**, so the operator picks it when writing the caption. `blog masthead` backfills `publish.mastheads.default` onto captions that have none and never replaces a chosen label. It lives in `caption`, so the review preview, the character count, and the posted text all agree (a human can still edit it out on `/review/{id}`).
- **A Facebook post has no title field**, so a post's title can only be the
  caption's leading line: the **hook under the series masthead** (the masthead is
  a standing label, not a title). Every feed row and every review row is titled
  that way, falling back to the caption's own first line when there is no
  masthead, to the source's title while a draft is still unwritten, and to a
  neutral `(no text — … post)` placeholder for a bare photo — so rows read
  consistently whatever the post's provenance. Since the Graph API cannot edit an
  already-published post, consistency comes from the renderer, including for
  posts already live. That one rule lives in `caption.py` (`split_title` /
  `display_title` / `leading_masthead`); the masthead itself rides along as a
  pill in the row, and `/review/{id}` keeps the source's own title in its Source
  rail as provenance.
- Feed error bodies are JSON `{"error": {code, message, type, ...}}`;
  `ApiError.from_payload` decodes them, including non-JSON/HTTP-only failures.
- Page post ids come back as `"<page_id>_<post_id>"`; the underscore form is
  the public permalink (`https://www.facebook.com/<page_id>_<post_id>`).
- Unpublished posts: `published=false` works on both `POST /{page}/feed` and
  `POST /{page}/photos` (verified live — the object exists for admins but is
  absent from the public `/feed` and `/photos` edges). An unpublished *photo*
  upload returns only the photo `id`, no `post_id`, because no feed story is
  created — so `permalink` is legitimately empty; don't treat that as an error.
  `publish.private: true` turns this on globally for testing the pipeline.
- **Timed posting posts only what a human approved.** `publish.post_at` is a list
  of container-local `HH:MM` slots (or window `HH:MM-HH:MM` entries — the
  scheduler then fires once that day at a random time inside the window, seeded
  by date+slot so it stays stable across restarts); `serve` runs a posting loop
  (`draft_pipeline.publish_scheduled`) that, at each slot, posts in-state
  `approved` drafts in **queue order** (see the next bullet), up to
  `publish.post_per_slot` per
  slot, and only if `publish.interval_days` (a minimum gap between *scheduled*
  public posts, 0 = off) has elapsed. It never approves, or touches `extracted`/`ai_draft` drafts. `publish.post_at: []` (the built-in
  default) disables the loop; the same drain is available on demand via
  `POST /publish/run` and `blog publish` — those two are still the *machine*
  draining the queue, so they obey the interval and count toward it. Because a
  private send deliberately
  leaves the draft in the queue, `publish_scheduled` also skips a draft already
  sent privately that day (otherwise it would re-post every slot).
- **The interval paces the machine, never a person.** `publish.interval_days` is
  about the unattended poster, so a **manual** send — a draft's **Post now** on
  `/review/{id}`, or a platform button on `/queue`; `web.py` passes
  `publish_draft(..., manual=True)` — is outside it in both directions: it is
  never refused by the gate and it never paces the gap (its audit record carries
  `"manual": true`, which `_last_public_post_date` skips exactly like
  `"private": true`). A hand-made post used to block the whole queue for the
  rest of the interval day, which read as "the bot refuses my own post". The
  drain (`publish_scheduled`) leaves `manual` false, so only it is paced; a
  `manual` default of `False` keeps any future caller on the paced side.
- **Approval is reversible until the send goes out.** `Draft.unapprove` /
  `draft_pipeline.unapprove_draft` / `POST /review/{id}/unapprove` (the
  **Unapprove** button on `/review/{id}`) return an `approved` draft to
  `ai_draft`, so `scheduled_queue` no longer lists it and the poster skips it,
  while it stays on `/review` for another pass. It is a bare state change —
  never posts, never touches the caption — and it drops the draft's manual
  `queue_order`, so a later re-approval lands at the end of the queue. It is
  refused once any destination has a *public* post (a send cannot be undone); a
  private send still un-approves. This is the escape hatch for a draft approved
  by mistake or queued too early — the alternative, `reject`, throws the draft
  away.
- **The "next up" shown to operators must be the draft that actually posts.**
  `draft_pipeline.scheduled_queue` (posting order) is the one ordering
  the poster drains; `status()` derives `publish.next_draft` from the same rule
  (and `publish.approved` / `publish.interval_remaining`). The dashboard
  **Next post** card, the `/status` **Post schedule** line, and `GET /api/status`
  all render that, so don't re-derive "next" anywhere else.
- **Posting order is `_queue_key`, not a plain FIFO.** A draft with a manual
  `Draft.queue_order` (≥ 1) sorts first, ranked ascending; drafts with none
  (`0`) keep the default oldest-source-first order and follow the ranked block —
  so with nothing ranked it is exactly the old FIFO, and this is the *only*
  ordering the poster uses. Operators set it on the **Post queue** tab's queue
  panel (drag a row, or its Top / Up / Down buttons) or via `blog queue` /
  `blog move`. `set_queue_order` renumbers the whole queue `1..N`; a subset is
  accepted (a drag leaves the rows it did not touch put); `reset_queue_order`
  clears it. Reordering is **approved-only**, never approves/posts, and
  `publish.post_per_slot` / `interval_days` still gate sends — order changes
  *which* draft goes next, never *whether* a slot fires. Don't add a second
  ordering rule, and don't put ordering controls back on `/review`;
  `list_drafts`/`sort_drafts` are display-only.
- **The post queue lives on its own tab, `/queue` (nav: Post queue, after
  Review queue).** It renders `draft_pipeline.scheduled_queue` — the poster's own list
  — so row #1 is exactly the draft that posts next, and it is marked **Next to
  post**. The reorder routes are `POST /queue/order` (drag, JSON),
  `/queue/reset`, and `/queue/{id}/move`; a move redirects back to
  `/queue#post-queue` through `web.message_url`. `/review/{id}` shows no queue
  panel and `/review` has no queue-order sort — `/queue` is the only place the
  order is set. The Factory dashboard does not render the queue at all.
- **A scheduled wake is not a post.** The posting loop wakes at every
  `publish.post_at` slot, but the interval gate makes it skip the ones before the
  gap elapses — so the next *wake* is usually **not** the next *post*. The post
  runtime's `next` is the wake; its `next_post` (`web.next_post_at`) is the first
  slot that can actually send. The dashboard **Next post** card and `/review`
  render `next_post`; the **Post schedule** row keeps the raw wake. Never show a
  wake as if it were a post time.
- `serve` needs the `[server]` extra (fastapi/uvicorn) and stays web-free
  otherwise. Docker: host port **8083** (voz-bot 8080, otofun-bot 8081,
  linkin-bot 8082), `./data` bind-mounted for the feed cache, and
  `./credentials.yaml` mounted read-only so the token never enters the image.

## Guardrails (do not silently weaken)

- **Official API only.** Do not add browser/login automation or HTML scraping
  of facebook.com to reach personal accounts, groups, or other people's data —
  it violates Meta ToS and defeats the point of this fork.
- `post` never sends anything without either an explicit `--dry-run` pass or
  real content (`--message` and/or `--photo`). Keep `--dry-run` available and
  documented.
- `publish.private: true` (config.yaml) makes every approval a **real but
  unpublished** Graph post (`published=false`) — visible to page admins only.
  It is not a dry run. Private sends are audited with `"private": true`, leave
  the draft in the review queue, and are excluded from `publish.interval_days`;
  only a *public* send records a `posts[<destination>]` entry, and the draft
  turns `posted` only once **every** target has one. Flip it to `false` to post
  publicly. A **manual** send (a draft's **Post now**, a `/queue` platform
  button) is the other kind outside the interval — audited with `"manual": true`
  and neither gated nor counted by it — but unlike a private send it *does*
  consume the destination, exactly like a scheduled one.
- API posts must stay within Facebook platform policies (no engagement bait,
  spam, inauthentic behavior). The content pipeline keeps its human review
  step: `scan_sources` only queues drafts, a caption is only written by hand, and nothing publishes except what a human approved on
  `/review/{id}` — either immediately ("Post now") or by queueing it for a
  scheduled slot ("Approve & schedule"). The posting scheduler may only post
  drafts already in state `approved`; never wire an approval or an `ai_draft` into it.
- Source scanning fetches only the configured official feeds (sitemap / RSS) —
  no HTML scraping. Stay within each site's robots.txt and rate limits; fetch
  politely (timeouts + bounded retries).
- **Idea seeds never fetch and never post.** The `ideas` block lists *systems* (not feeds). `blog add-idea` queues the operator's own idea as an `EXTRACTED` draft; the app never scrapes the systems' docs. Like a scan, an idea only ever reaches `EXTRACTED`, and only a human approval moves it on.
## UI design system (do not weaken)

The operator UI is one system, and `tests/test_design_system.py` enforces it.
Read `docs/design/design-system.md` before changing any markup or the stylesheet.

- All styling lives in `src/social_bot/ui.py` (`_CSS` plus the `layout` /
  `nav_html` / `badge` / `notice_html` / `favicon_svg` primitives). Page modules
  (`draft_html.py`, `dashboard_html.py`, `destinations/facebook/feed_html.py`)
  render **fragments only**: no `<style>`, no `style="…"` attribute, no colour
  or size literals.
  Add a class to `_CSS` instead of styling a page.
- Compose from the shared components and tokens (`.panel`, `.stack`, `.cols`,
  `.cmdbar`, `.btn`, `.badge`, `.pill`, `.qrow`, `.stepper`, `.dot`, …). Never
  invent a class without adding its rule to `_CSS`.
- Keep the semantics: the accent is reserved for the primary action and the
  focused stage; state is carried by colour **and** a dot **and** a label; every
  control stays at least 44px tall; every page returns through `layout()`.
- The favicon is generated, not drawn by hand: `ui.favicon_svg()` renders the
  nav's brand mark (accent tile + letter) and reads `--accent` / `--accent-fg`
  straight from `_CSS` — light and dark — so the tab icon can never drift from
  the tokens. `layout()` links it at `/favicon.svg`; `web.py` serves it (and
  redirects `/favicon.ico` there). Never hard-code the icon's colours.
- After any UI change, run `tests/test_design_system.py` and regenerate the
  preview with `.venv/bin/python scripts/build_styleframe.py`. The suite fails
  on an undefined token, a class with no rule, a badge state with no colour,
  malformed markup, or a stale styleframe — never weaken, skip, or delete those
  tests. `docs/design/styleframe.html` is generated; edit `styleframe.py`, not
  the HTML.

## Testing

```
.venv/bin/python -m pytest     # pure logic, no network
.venv/bin/ruff check src tests scripts   # lint
.venv/bin/ruff format src tests scripts  # format in place (--check to verify)
```

Ruff owns lint and formatting; its config lives in `pyproject.toml`
(`[tool.ruff]`). The ruleset is pinned there on purpose — ruff's built-in
defaults grow between releases, and the pinned `select` keeps the check
stable. `E501` is off because the formatter owns line length (long URLs,
HTML fragments, and the stylesheet must not be re-wrapped). `ruff format` is
the style source of truth, so land formatting changes as their own pass, not
mixed into a feature diff.

Tests cover config defaults/deep-merge/validation, token precedence,
Graph URL/error-payload handling, feed timestamp parsing, markdown + HTML
rendering, the refresh cache writer, source parsing (sitemap/RSS/Atom/JSON-LD
index), the draft model/persistence (incl. per-destination post records and the
legacy-field migration), the destination registry + publisher adapters, the
scan/caption/publish pipeline (stubbed clients), the scheduled drain
(`publish_scheduled`, `approve_draft`), the Chromium screenshot
(`browser_shot.py`), the operator pages
(`ui.py` / `draft_html.py` / `dashboard_html.py`), the design-system contracts
(undefined tokens, unstyled classes, badge coverage, and styleframe freshness in
`test_design_system.py`), and serve's pure scheduling
helpers (no fastapi import needed). Live calls are manual: `whoami` first, then
`feed --limit 3`, then `blog scan` (queues drafts, no token needed), then
`post --dry-run` before
the first real post.

The deployed UI (`https://social.atento.vn/`, nginx -> host port 8083) sits
behind HTTP basic auth. To poke it with agent-browser, run
`scripts/open_site.py [url]`: it reads `site.user` / `site.password` from the
git-ignored `credentials.yaml` via the core's own `load_config` — so the pair
stays out of the committed config, beside the page token — and hands them to
agent-browser with `set credentials` before navigating. (agent-browser's auth
vault is form-based: `auth login` waits for a login form and fails an HTTP
challenge, so `set credentials` is the supported path.) `src/` is baked into the
Docker image and only `data/`, `config.yaml`, `docs/` and `credentials.yaml` are
bind-mounted, so a UI change needs `docker compose up -d --build` to appear
there.
