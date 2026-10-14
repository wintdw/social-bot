# Content pipeline

Turns items from external source feeds into **human-approved** Facebook Page
posts. The captions are written by the operator in Claude.

## Flow

```
 source feeds                 drafts/                       review                   publish
 ────────────                 ──────                       ──────                   ───────
 index|sitemap|rss  ─scan─▶  extracted  ─caption saved─▶  ai_draft ──human "Post now"──▶ posted
 (source.py)      (draft_pipeline)      (edit_draft)          │                        (publishers)
                                                              │ human "Approve & schedule"
                                                              ▼
                                                          approved ─post_at slot / POST /publish/run─▶ posted
                                                          (publish_scheduled)
```

The caption is written by hand in **Claude** and pasted
on `/review/{id}`; the app runs no model, no worker, and no retrieval. The scan
and refresh loops never publish. Publishing only ever happens for drafts a human
approved: the posting scheduler (`publish.post_at`) picks *when* an approved
draft goes out — it never approves anything itself.

## State machine (`drafts.py`)

| State | Meaning |
|---|---|
| `extracted` | Scanned from a source, or queued as an idea; awaiting a caption. |
| `ai_draft` | A caption has been saved; awaiting human approval. |
| `approved` | Human-approved. Queued for the next posting slot (`publish.post_at`) — or posted immediately if approved with "Post now". Reversible with **Unapprove** until it posts. |
| `posted` | Published; `post_id`/`permalink`/`posted_at` set and audited. |
| `rejected` | Dismissed; not published. |

Transitions: `extracted → ai_draft` (`edit_draft` saving a non-empty caption), `ai_draft|approved
→ posted` (`Draft.mark_posted`), `ai_draft → approved` (`Draft.approve`),
`approved → ai_draft` (`Draft.unapprove`), any
`→ rejected` (`Draft.reject`).
`can_publish()` = `ai_draft|approved`.
`unapprove()` refuses a draft that already has a public post (a send cannot be
undone) and drops its manual queue position, so a later re-approval lands at the
end of the queue.

## Steps and where they live

### 1. Scan (`draft_pipeline.scan_sources`)
- Fetches each `sources[]` entry via `source_api.SourceClient` (retries +
  backoff; host is flaky).
- Parses by `source.type` via `source.parse_source`:
  - `index` — the listing page's JSON-LD `ItemList` (`source.parse_index`),
    with an `<a href>` fallback. Used because atento.vn has no feed and its
    sitemap omits posts.
  - `sitemap` — `<loc>` entries under `path_prefix` (`source.parse_sitemap`).
  - `rss` — RSS 2.0 / Atom (`source.parse_rss`).
- **Enriches** each new item from its post page (`source.parse_blog_posting`:
  JSON-LD `BlogPosting` → `og:*` meta fallback) for `title`/`excerpt`/`image`.
  Controlled by `blog.enrich`.
- Dedupes by `"<source>:<slug>"` against `seen.json`; queues new items as
  `extracted` drafts in `queue.json`. A slug is marked seen only after it is
  queued.
- Drops items published more than `blog.max_age_days` days ago (`0` = no limit;
  the project `config.yaml` sets `90`). Applied **before** `blog.max_scan`, so
  old entries can't consume the batch and a feed that exposes more entries than
  one scan takes (martinfowler's Atom: a 30-entry window against a cap of 12)
  stops being walked back at the cutoff instead of queueing another batch every
  scan. An item with no date is kept: an `index` listing carries none until
  enrichment, and an undated post can't be shown to be old.

### 2. Caption (`draft_pipeline.edit_draft`)

The caption is written by the operator in Claude. The voice briefs in
`docs/voices/*.md` are optional register references; the app does not read them.

Paste the result into the Caption field on `/review/{id}` and save. `edit_draft`
stores the caption and hashtags, re-lints the caption (`caption_lint.py`, advisory
only), and moves an `extracted` draft to `ai_draft`, which is what makes it
approvable. Image prompt, image style and destinations are saved with it. The app
never calls a model.

### 2b. Images (source cover, drawn HTML5 plate, or a drawn illustration)

- A post uses its **source article's own cover**, captured at scan time
  (enrichment reads the post page for `title`/`excerpt`/`image`). No AI
  generation: nothing is invented, and a post without a cover simply publishes
  without an image (a link post) unless the operator draws one.
- For a **mechanism** post the operator writes a **plate** in HTML5: one static
  page (CSS, plus inline SVG where a shape needs it), drawn for this post's own
  content and kept in `data/review/plates/` (git-ignored). No JavaScript: the
  screenshot is taken as the page loads. `browser_shot.html_to_png` screenshots
  it to a PNG through the host's Chromium, and the draft points at that PNG
  because Graph only accepts raster. A missing browser never blocks anything;
  the draft keeps its existing image. Each plate is laid out from its own post,
  so nothing is reused between posts.
- **Selectively**, an **illustration** may be drawn for a post with the
  `anatomy` skill: a crafted isometric SVG figure, screenshotted to a PNG on the
  same served `/images/` store a plate uses, that the draft then points at. It
  is for the post whose *idea* needs a drawn picture — a mechanism, a structure,
  an inventory of parts, a before/after — where a figure earns the reader better
  than the source cover or the code plate. It is **not a default and never every
  post**: the source cover stays the norm and the HTML plate still owns plain
  wiring. It is a drawn figure (operator-made, via the host-side `anatomy`
  skill), never a generated or photographic image, and it goes through the same
  human gate as any other image. See
  [image-styles/illustration.md](image-styles/illustration.md).
- **The source post's own image is kept on the draft** as `source_image`, written
  at scan time and never touched by drawing. **Restore source image** on
  `/review/{id}` (`POST /review/{id}/restore-image`) always puts the original
  picture back without touching the caption. The draft page offers it whenever
  the current image is a drawn plate — decided by comparing against `source_image`,
  or, for a draft scanned before that was recorded, by recognising a locally
  stored `/images/...` file — and since a pre-existing draft has no
  `source_image` stored, the restore reads the source page once (as scan
  enrichment does) to recover it and keeps it for next time. Nothing to recover
  (no source URL, no image on the page, an unreachable page) returns a warning,
  never a broken page.
- `blog localize-images` copies a still-remote non-source image into the local
  store (a migration for legacy AI-image drafts; it never renders anything).

### 2d. Idea seeds — original posts, not reposts (`draft_pipeline.queue_ideas`)

`ideas.topics_file` lists the systems original posts are about (one per line,
optional `| <docs url>`; `social-bot blog topics` prints them). The operator writes
an angle in Claude and queues it:

```
social-bot blog add-idea "B+ tree trong MySQL" --topic "MySQL" --excerpt "outline"
```

Each idea is an `EXTRACTED` draft with `source: atento-original`, no URL and no
source image, deduped by title slug against `data/ideas/seen.json`. Nothing is
fetched and nothing is generated. From there it follows the normal caption and
human approval.

### 3. Review queue (human)
- `/review` lists open drafts (`extracted`/`ai_draft` plus `approved` ones still
  waiting for a slot) **newest first by the item's own date**
  (`published`, falling back to when it was queued — a whole scan is queued
  within seconds, so `created_at` alone orders a batch arbitrarily), with
  **Status** as a segmented control and **Source** as filter chips
  (`?source=<name>&status=<state>`, plain links, no JS). A row shows a
  thumbnail, the state badge, the source, the series masthead, the date it is
  sorted by (`published`, or `queued` when the source gave none), and a one-line
  caption preview — titled by the caption's hook (or the source's title while
  the draft is still unwritten).
  A **Search** box matches the title, excerpt, or caption (`?q=<text>`,
  case-insensitive)
  and **Sort** switches between newest first (the default) and oldest first
  (`?sort=oldest`) — a plain GET form so they work without JS; the search and
  sort are carried through every filter link and the pager. Rows are plain
  links: the posting order is set on the Post queue tab, not here.
  `/review/{id}` shows the extracted info, the
  editable caption + hashtags, and the actions. Rendered by
  `draft_html.render_draft_html`.
- **Destinations**: a chip per registered platform sets *this* draft's targets —
  `publish.destinations` only seeds new drafts. The action bar then carries one
  **Post to &lt;Platform&gt;** button per platform still pending (the plain
  **Post publicly** when only one is left), so Facebook and LinkedIn are
  independent sends: a draft can go to either, or to both, in any order.
- Actions: **Save** (persist the caption, hashtags, and image prompt without
  posting) and **Post now** (publish immediately) always; **Reject**. A draft
  whose image is a diagram also offers **Restore source image**, which
  swaps the source post's own picture back in and leaves the caption alone.
  
  When `publish.post_at` is non-empty, **Approve & schedule** also appears — it
  saves the caption edits and queues the draft as `approved` for the next slot.
  An already-`approved` draft shows "waiting for the next slot" instead, and
  offers **Unapprove**: it pulls the draft back to `ai_draft`, so the poster skips
  it while it stays on `/review` for another pass. Unapprove is a bare state
  change (it submits no compose fields), never posts, and is refused once any
  destination has a public post.
- `/queue` is the **Post queue**: the approved drafts in posting order, with the
  ordering controls (§4b) and a **Post approved now** button (`POST /publish/run`)
  to drain them on demand. `/publish` lists the audit log (what has actually been
  posted); `/status` shows the token's validity and expiry, sources, drafts by
  state, and publish settings. `/` is the Factory dashboard — the refresh/scan
  controls, the counts, the schedulers, and the cached feed. All five share
  the nav from `ui.py`.

### 4. Publish (`draft_pipeline.publish_draft`)
- Triggered by `POST /review/{id}/publish` (the review page's **Post now**), by
  a `/queue` per-platform button, or — for approved drafts — by the posting
  scheduler / `POST /publish/run` / `blog publish`. Parsed in `web.py`.
  Validates `can_publish()`, then resolves a
  publisher per destination through `destinations.publisher_for` (the registry).
  The two operator buttons pass `manual=True` (see the interval note below); the
  drain paths do not.
- Each destination posts independently: one already posted publicly is skipped,
  so a re-run after a partial failure only fills the gaps. The draft turns
  `posted` only once every target has a public record; each result is stored
  under `Draft.posts[destination]`.
- `FacebookPublisher` posts `Draft.post_text` (**caption + hashtags**) — a photo
  post via `create_photo_post` when `image` is set, else a link post via
  `create_post`. The photo is an **upload** (multipart `source`), never a `url`
  for Graph to fetch: `media.load` reads the stored file, or downloads a remote
  URL first (with the generator's key when it is the generator's host).
- `dry_run=True` prints the request and mutates nothing.
- With `publish.private: true` every destination sends **unpublished**
  (`published=false` on the Graph call, visible to page admins only). The call
  is real — it just doesn't go public — so the draft stays in the queue and the
  record in `published.jsonl` gets `"private": true`. Private sends don't count
  toward `publish.interval_days`.
- A **manual** send (a draft's **Post now**, a `/queue` platform button) is
  audited with `"manual": true` and sits outside `publish.interval_days` in both
  directions — the gate never refuses it and it never paces the gap (so the
  poster isn't held back by a post a person made by hand). Unlike a private send
  it consumes the destination normally.
- On a public success: `mark_posted`, append to `published.jsonl`, save.

### 4b. Scheduled posting (`draft_pipeline.publish_scheduled`)
- `serve` runs a posting loop at the `publish.post_at` slots (override with
  `serve --publish-at HH:MM …`; `[]` disables it). A slot is a fixed `HH:MM` or
  a window `HH:MM-HH:MM` — inside a window the loop fires once that day at a
  random time (seeded by date+slot, so it is stable across restarts). At each
  slot it drains the `approved` queue **in posting order** — drafts an operator
  has moved (their `queue_order`, see below) first, then the rest **oldest
  first** (FIFO) — up to `publish.post_per_slot` per slot, calling
  `publish_draft` per draft — so
  the kill-switch, interval and destination adapters are shared with the
  on-demand path. It never approves or touches `extracted`/`ai_draft`
  drafts.
- **Ordering the queue.** The Post queue tab's queue panel
  (`dashboard_html.render_queue_html` / `_queue_panel`) renders
  `draft_pipeline.scheduled_queue` — the poster's own list — so its first row is
  exactly the draft that posts next, and that row is marked **Next to post**.
  `scheduled_queue` sorts by `_queue_key`: a draft with a manual `queue_order`
  (≥ 1) comes first, ranked ascending; drafts with none (`0`) keep the default
  oldest-first order and follow the ranked block. So nothing changes until an
  operator reorders something, and a draft approved later (unranked) lands after
  the ranked block.
  `draft_pipeline.set_queue_order` renumbers the whole queue `1..N` after a move
  (a subset is enough — a drag leaves the rows it did not touch put);
  `move_in_queue` implements up / down / top / bottom on top of it, and
  `reset_queue_order` clears every rank back to the default. None of them
  approve or post: a draft only enters the queue by human approval.
  The panel's controls are progressive — native drag and drop when JS is
  available, and each row's own **Top / Up / Down** buttons (plain forms to
  `/queue/{id}/move`) when it is not.
- On demand: `POST /publish/run` (the dashboard/queue "Post approved now"
  button, content-negotiated like `/scan`) and `social-bot blog publish
  [--limit N] [--dry-run]`. The queue itself has a CLI too — `social-bot blog
  queue [--reset] [--json]` lists it in posting order and `social-bot blog move
  <id> up|down|top|bottom` reorders one draft, the same operations as the
  Post queue tab's queue panel.
- The poster can be **paused** at runtime (`POST /publish/pause`, resumed with
  `POST /publish/resume`; the dashboard shows one button or the other). A paused
  loop still wakes at its slots but skips them — it consumes each slot's marker,
  so resuming posts from the *next* slot rather than firing a backlog. The pause
  is persisted (`data/state.json`) so a restart keeps the hold. Only the
  scheduler is paused: "Post approved now", a draft's Post now, and
  `blog publish` still send, because those are explicit human actions. (The
  *interval* draws its line elsewhere: the drain paths — **Post approved now**,
  `blog publish` — obey it, the two per-draft buttons don't.)
- A slot fires **once, on its own day**. The loop wakes on the union of every
  destination's slots, so it fires a destination only when that destination's
  occurrence is *today* (`web.due_slot`) and differs from its marker in
  `state["post_slot"]`. The markers are seeded at startup and persisted in
  `data/state.json` (`post.slot`), so a restart can't re-fire a slot that already
  ran today, and a destination whose slot is still ahead never fires at another
  destination's wake. (Before this, a 14:25 wake for one destination could fire
  another's *previous-day* slot, hours late.)
- After a run that actually posted, `serve` also refreshes the feed cache
  (`refresh_feed`), so the new post shows on the dashboard immediately instead
  of waiting for the next `--refresh-at` slot. A run that posted nothing
  refreshes nothing.
- `publish.interval_days` sets a minimum gap between **scheduled** public posts
  (e.g. `2`
  = one post every other day, `1` = at most one per day); enforced in
  `publish_draft` for the poster's own sends — the `post_at` slots, `POST
  /publish/run` and `blog publish`. Private sends don't count, and **manual**
  sends (a draft's **Post now**, a `/queue` platform button) are outside the
  interval in both directions: never refused by it, never counted toward it, so
  a hand-made post can't hold the queue back (`publish_draft(..., manual=True)`,
  audited as `"manual": true`). The built-in default is `0` (no minimum).
- The next send is knowable ahead of time: `status()` sets
  `publish.next_draft` (the first draft in posting order — exactly what
  `publish_scheduled` drains first), plus `publish.approved` and
  `publish.interval_remaining`. The
  dashboard's **Next post** card and the `/status` **Post schedule** line render
  that as time + which draft; `GET /api/status` exposes the same fields. A wake
  is not a post: the card's time is the first slot that can actually send
  (`web.next_post_at`, honoring `interval_remaining`), while the **Post schedule**
  row shows the scheduler's next wake.
- An interval `ValueError` stops the batch; a publisher/API error is
  recorded
  and the batch continues. Because a private send leaves the draft in the queue,
  a draft already sent **privately** that day is skipped, so `publish.private`
  can't re-post it at every slot.

## Data files (`review.dir` + `publish.dir`)

| File | Contents |
|---|---|
| `data/review/queue.json` | The queue (list of drafts). Each carries `queue_order` (0 = the default oldest-first position). Written atomically (tmp + rename), and every slow writer (a scan) re-reads it right before saving so a post recorded meanwhile isn't dropped. |
| `data/review/seen.json` | `"source:slug"` dedupe ledger. |
| `data/publish/published.jsonl` | Append-only publish audit (one JSON record per post; `"private": true` marks an unpublished test send, `"manual": true` a send a person made by hand — both are left out of the `interval_days` count). |

The idea seeds (§2d) keep their own state under `ideas.dir`:

| File | Contents |
|---|---|
| `data/ideas/topics.md` | The systems/themes original posts are drawn from — `ideas.topics_file`, edited live by the operator. |
| `data/ideas/seen.json` | Title slugs of ideas already queued (dedupe). |

## HTTP surface (`web.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Factory dashboard: controls, counts, scheduler state, cached feed. |
| GET | `/queue` | Post queue: the approved drafts in posting order, with the reorder controls and the **Post approved now** button (when `publish.post_at` is set). |
| GET | `/review` | Review queue list, newest first (has the **Scan sources now** button). Optional `?source=<name>&status=<state>` filters, `?q=<text>` title/excerpt search, and `?sort=oldest`; paged with `?page=<n>&per_page=<n>` (default 20, max 200). |
| GET | `/review/{id}` | Review detail: editable caption and hashtags; the destination picker (per-platform chips) and one **Post to &lt;Platform&gt;** button per pending destination; Save / Reject, plus Approve & schedule when `publish.post_at` is set (+ Unapprove on an approved draft, + + Restore source image when the image is a diagram). |
| GET | `/publish` | Publish audit log (public + private sends). |
| GET | `/status` | Human-readable snapshot: token validity/expiry, schedules, sources. |
| GET | `/drafts` | Redirect (307) to `/review` for old links. |
| GET | `/health` | Liveness + last run info (JSON). |
| GET | `/live` | Liveness probe: `{"status": "alive"}`, never touches state. |
| GET | `/ready` | Readiness probe: 200 when serving, 503 while draining or if a scheduler died / state dir is unwritable. |
| GET | `/api/status` | Full pipeline snapshot (JSON); `publish.next_draft` is the first approved draft in posting order the poster will send next. |
| POST | `/refresh` | Refresh the feed now. |
| POST | `/scan` | Scan sources now (JSON, or a 303 back to `/review` for browsers). |
| POST | `/publish/run` | Drain the approved queue now (JSON, or a 303 back to the submitting page — `/review` by default). Still works while paused. |
| POST | `/publish/pause` | Pause the posting scheduler — it skips its slots until resumed (JSON, or a 303 back to `/`); persisted across restarts. |
| POST | `/publish/resume` | Resume the posting scheduler (JSON, or a 303 back to `/`). |
| POST | `/review/{id}/save` | Save the compose edits (caption, hashtags, image prompt); never posts. |
| POST | `/review/{id}/unapprove` | Pull an approved draft out of the post queue: back to `ai_draft`, so the poster skips it, while it stays on `/review`. The inverse of `approve=1`; never posts. |
| POST | `/review/{id}/publish` | Publish (form; `dry_run=1` to preview). With `approve=1` it saves the edits and queues the draft as `approved` instead of posting. |
| POST | `/review/{id}/reject` | Reject. |
| POST | `/review/{id}/restore-image` | Put the source post's own image back, replacing a generated one (reads the source page once when the draft has no stored original). |
| POST | `/queue/{id}/move` | Move an approved draft in the post queue (`direction=up\|down\|top\|bottom`, plus a `next` return path — the queue page sends `/queue#post-queue`); never posts. |
| POST | `/queue/order` | Persist a drag-and-drop reorder: JSON `{"ids": [...]}` (a subset is fine), returns `{"ok": true, "order": [...]}`. |
| POST | `/queue/reset` | Clear every manual position, restoring the default oldest-first order. |

## Extending

**A new source.** Add an entry to `sources` in `config.yaml` (and the
`DEFAULTS["sources"]` example). For a new *format*, add a
`parse_<type>(...) -> list[Item]` in `source.py`, dispatch it in
`parse_source`, allow the type in `config.validate`, and cover it in
`tests/test_source.py`. Fetching itself rarely changes — `source_api` returns
text.

**A new idea theme.** Just add a line to `ideas.topics_file`
(`data/ideas/topics.md` by default) — no code and no restart. A theme is a
*system* (a name, optional `| <docs url>`), never a feed. To change the
*mechanism* (how themes are parsed, how ideas are queued), it is
`src/social_bot/ideas.py` (pure parse + slug) and `draft_pipeline.queue_ideas`,
tested in `tests/test_ideas.py` / `tests/test_draft_pipeline.py`.

**A new destination.** Add a package under `src/social_bot/destinations/` with a
`Publisher` subclass (`name`, `label`, `describe`, `publish -> PublishResult`),
register it in `destinations/registry.py`, and add its
`DEFAULTS["destinations"]["<name>"]` block + credentials entry.
`config.validate` accepts any registered name. Its `posts[destination]` records
and audit rows flow through unchanged. `linkedin/publisher.py` shows the shape of
a destination that **delegates to another local service**: it calls linkin-bot's
`POST /post` gateway (text + the image bytes as base64 + the source URL, which the
gateway comments on the new post) instead of talking to the platform API, so no
token/OAuth lives here.

**Changing the caption text.** The published text is `Draft.post_text`
(caption + hashtags). Keep hashtags in the `hashtags` field, not the caption.
The series masthead is `publish.mastheads` (clear `choices` to disable).

**Changing the voice.** Edit the briefs in `docs/voices/` (reference files for
choosing a register when you write); the app does not read them.

**Changing the image look.** Plates are plain HTML5 files in `data/review/plates/`.
Write or edit one per post, then screenshot it with `browser_shot.html_to_png`
(1080×1350). Keep to the house palette in `docs/image-styles/diagram.md`.

**Changing what a draft stores.** Edit the `Draft` dataclass in `drafts.py`;
`from_dict` ignores unknown keys, so old `queue.json` files still load.

## Guardrails (do not weaken)

- Scanning/refreshing runs on the scheduler; **posting never happens without a
  human approval**. The posting scheduler only posts drafts already in state
  `approved`; it must never approve or touch `extracted`/`ai_draft`.
- `publish_draft` is reached from the explicit **Post now** action, the scheduled
  drain, `POST /publish/run`, and `blog publish`. `publish.post_at: []` disables
  timed posting entirely. Only **Post now** and the `/queue` platform buttons
  pass `manual=True`; the drain paths are the machine and stay paced.
- `publish.enabled: false` is a global kill-switch; `publish.interval_days`
  enforces a minimum gap between scheduled public posts (enforced in
  `publish_draft`; manual and private sends are neither gated nor counted).
- `--dry-run` is available on every publish path (`post` command, `blog publish`,
  and `dry_run=1` on `POST /review/{id}/publish`).
- Only the configured official feeds are fetched — no HTML scraping of
  facebook.com, and stay within each site's robots.txt.
- Endpoints are currently **unauthenticated**; do not expose them publicly
  without adding auth.
