# Content pipeline

Turns items from external source feeds into **human-approved** Facebook Page
posts, with an external AI doing the rewrite.

## Flow

```
 source feeds                 drafts/                       review                   publish
 ────────────                 ──────                       ──────                   ───────
 index|sitemap|rss  ─scan─▶  extracted  ─rewrite API─▶  ai_draft ──human "Post now"──▶ posted
 (source.py)      (draft_pipeline)      (draft_pipeline)      │                        (publishers)
                                                              │ human "Approve & schedule"
                                                              ▼
                                                          approved ─post_at slot / POST /publish/run─▶ posted
                                                          (publish_scheduled)
```

The rewrite is done by an **external agent** (Command Code applying the Atento
DNA), not by this codebase. The bot only exposes the drafts and accepts the
result back. The scan and refresh loops never publish. Publishing only ever
happens for drafts a human approved: the posting scheduler (`publish.post_at`)
picks *when* an approved draft goes out — it never approves anything itself.

## State machine (`drafts.py`)

| State | Meaning |
|---|---|
| `extracted` | Scanned from a source; awaiting a rewrite. |
| `ai_draft` | A rewrite has been stored; awaiting human review. |
| `approved` | Human-approved. Queued for the next posting slot (`publish.post_at`) — or posted immediately if approved with "Post now". |
| `posted` | Published; `post_id`/`permalink`/`posted_at` set and audited. |
| `rejected` | Dismissed; not published. |

Transitions: `extracted → ai_draft` (`Draft.apply_rewrite`), `ai_draft|approved
→ posted` (`Draft.mark_posted`), `ai_draft → approved` (`Draft.approve`), any
`→ rejected` (`Draft.reject`).
`can_receive_rewrite()` = `extracted|ai_draft`; `can_publish()` = `ai_draft|approved`.

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

### 2. Rewrite (`draft_pipeline.receive_rewrite`)
- The agent calls `GET /api/drafts` (open drafts + `publish.dna_file` contents
  as `dna`; paged — pass `limit`/`offset` and follow `next_offset`) and
  `POST /api/drafts/{id}/rewrite` with
  `{caption, hashtags, cta, commentary, image_prompt}`.
- Stored via `Draft.apply_rewrite`; the draft becomes `ai_draft`.
- `publish.mastheads` (config.yaml) sets the series masthead on line 1 of every
  caption. The label is a **content judgment, not a source default**: the
  rewriter picks one of `mastheads.choices` per post (DNA §4.5 — knowledge worth
  learning → Học, merely informational → Đọc báo, a one-idea nugget → Mỗi ngày).
  `mastheads.default` is only the fallback the pipeline prepends when the
  rewriter omits one. It lands in `caption`, so the review preview, the
  character count, and the posted text all include it.
- A Facebook post has no title field, so a post's title can only be the caption's
  leading line — the **hook under the series masthead** (the masthead is a
  standing label, not a title). `caption.split_title` promotes that line for
  every feed row and review row, falling back to the caption's own first line
  when there is no masthead; `caption.display_title` falls back to the source's
  title while a draft is still unwritten. The masthead rides along as a pill, and
  `/review/{id}` keeps the source title in its Source rail. The Graph API can't
  edit an already-published post, so consistency has to come from the renderer.
- Captions written **before** the mastheads were configured lack one;
  `social-bot blog masthead` fills the default in (idempotent, never replaces a
  chosen label, never touches the image). Re-label a misjudged post on
  `/review/{id}`.

### 2b. Images (`image_gen.py`, optional)
- Images are generated **after** the rewrite, on demand via
  `social-bot blog image`, the **Generate image** button on `/review/{id}`, or
  `POST /api/drafts/{id}/image`. The rewriter supplies `image_prompt` — a
  concrete English visual concept for that post — and that is what gets
  illustrated. It is also the image's alt text (there is no separate Vietnamese
  alt), and it is **editable on `/review/{id}`** (saved with the caption); edit
  it before hitting **Regenerate image**. The button only appears when
  `image_gen.enabled` is true.
- The review/API paths run synchronously (the request waits for the provider,
  which can take minutes with `gpt-image` models); `blog image` batches.
- **Every post is a photo post**, so `serve` also fills the image
  automatically: when a rewrite lands (`POST /api/drafts/{id}/rewrite`) it
  generates that draft's image **in the background**, only if the draft has
  none, and returns the rewrite response immediately. A restart before the
  background job finishes is caught by `blog image`.
- **Knowing whether it worked** (the job is async, so the draft's `image` field
  alone only says "present or not"):
  - `GET /api/status` → `images` lists each job with `status`
    (`running` / `ok` / `unchanged` / `skipped` / `error`), `error`, and
    timestamps, plus `running` / `failed` counts. In-memory: a `serve` restart
    clears the job list (the draft's `image` is still the durable truth).
  - The **`/status`** page and the **dashboard (`/`)** both render an
    **Image jobs** section from that payload.
  - `/review/{id}` shows it in the UI: "Generating…" while running, the error
    text on failure, and "No image yet" otherwise.
  - Failures are also logged to the container (`docker logs social-bot`).
- **Scanning does not generate images.** At scan time no rewrite exists, so the
  only available subject would be the raw `title`; illustrating an abstract
  Vietnamese title produced a near-identical picture for every draft. Generate
  after the rewrite instead.
- **An existing image is never replaced by default.** Generation only fills
  drafts that have none, so a source post's own cover (e.g. the blog's image)
  survives every trigger — the rewrite background job, `blog image`, and the
  API. To deliberately replace one, opt in: `blog image --overwrite`,
  `POST /api/drafts/{id}/image?overwrite=true`, the **Regenerate image** button
  on `/review/{id}`, or `image_gen.overwrite: true` in config.
- The prompt (`image_gen.build_prompt`) is the `image_gen.style_file` brand
  look (palette/mood only) + `image_prompt` (subject + composition) + hard
  negatives (no people, no text). `image_gen.base_url` selects the endpoint
  (`gen.pollinations.ai/image` — clean output, needs `api_key`;
  `image.pollinations.ai/prompt` — keyless but watermarked and `sana`-only).
- A failure is recorded in the summary `errors` and the draft keeps its
  existing image: image generation never blocks the pipeline.

### 3. Review (human)
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
  and **Sort** switches between newest and oldest first (`?sort=oldest`), both a
  plain GET form so they work without JS; the search and sort are carried
  through every filter link and the pager.
  `/review/{id}` shows the extracted info, the
  editable caption + hashtags, and the actions. Rendered by
  `draft_html.render_draft_html`.
- Actions: **Save** (persist the caption, hashtags, and image prompt without
  posting) and **Post now** (publish immediately) always; **Reject**.
  When `publish.post_at` is non-empty, **Approve & schedule** also appears — it
  saves the caption edits and queues the draft as `approved` for the next slot
  (an already-`approved` draft shows "waiting for the next slot" instead). The
  review page also carries a **Post approved now** button (`POST /publish/run`).
- `/publish` lists the audit log (what has actually been posted); `/status`
  shows the token's validity and expiry, sources, drafts by state, and publish
  settings. `/` is the dashboard with the refresh/scan controls. All four share
  the nav from `ui.py`.

### 4. Publish (`draft_pipeline.publish_draft`)
- Triggered by `POST /review/{id}/publish` (the review page's **Post now**) or,
  for approved drafts, by the posting scheduler / `POST /publish/run` /
  `blog publish`. Parsed in `web.py`. Validates `can_publish()`, then resolves a
  publisher per destination through `destinations.publisher_for` (the registry).
- Each destination posts independently: one already posted publicly is skipped,
  so a re-run after a partial failure only fills the gaps. The draft turns
  `posted` only once every target has a public record; each result is stored
  under `Draft.posts[destination]`.
- `FacebookPublisher` posts `Draft.post_text` (**caption + hashtags**) — a photo
  post via `create_photo_post` when `image` is set, else a link post via
  `create_post`.
- `dry_run=True` prints the request and mutates nothing.
- With `publish.private: true` every destination sends **unpublished**
  (`published=false` on the Graph call, visible to page admins only). The call
  is real — it just doesn't go public — so the draft stays in the queue and the
  record in `published.jsonl` gets `"private": true`. Private sends don't count
  toward `publish.interval_days`.
- On a public success: `mark_posted`, append to `published.jsonl`, save.

### 4b. Scheduled posting (`draft_pipeline.publish_scheduled`)
- `serve` runs a posting loop at the `publish.post_at` slots (override with
  `serve --publish-at HH:MM …`; `[]` disables it). A slot is a fixed `HH:MM` or
  a window `HH:MM-HH:MM` — inside a window the loop fires once that day at a
  random time (seeded by date+slot, so it is stable across restarts). At each
  slot it drains the
  **oldest** `approved` drafts first (FIFO), up to `publish.post_per_slot` per
  slot, calling `publish_draft` per draft — so
  the kill-switch, interval and destination adapters are shared with the
  on-demand path. It never approves, rewrites, or touches `extracted`/`ai_draft`
  drafts.
- On demand: `POST /publish/run` (the dashboard/review "Post approved now"
  button, content-negotiated like `/scan`) and `social-bot blog publish
  [--limit N] [--dry-run]`.
- The poster can be **paused** at runtime (`POST /publish/pause`, resumed with
  `POST /publish/resume`; the dashboard shows one button or the other). A paused
  loop still wakes at its slots but skips them — it consumes each slot's marker,
  so resuming posts from the *next* slot rather than firing a backlog. The pause
  is persisted (`data/state.json`) so a restart keeps the hold. Only the
  scheduler is paused: "Post approved now", a draft's Post now, and
  `blog publish` still send, because those are explicit human actions.
- After a run that actually posted, `serve` also refreshes the feed cache
  (`refresh_feed`), so the new post shows on the dashboard immediately instead
  of waiting for the next `--refresh-at` slot. A run that posted nothing
  refreshes nothing.
- `publish.interval_days` sets a minimum gap between **public** posts (e.g. `2`
  = one post every other day, `1` = at most one per day); enforced in
  `publish_draft`, so it paces both the scheduler and "Post now". Private sends
  don't count. The built-in default is `0` (no minimum).
- The next send is knowable ahead of time: `status()` sets
  `publish.next_draft` (the oldest `approved` — exactly what `publish_scheduled`
  drains first), plus `publish.approved` and `publish.interval_remaining`. The
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
| `data/review/queue.json` | The queue (list of drafts). Written atomically (tmp + rename). |
| `data/review/seen.json` | `"source:slug"` dedupe ledger. |
| `data/publish/published.jsonl` | Append-only publish audit (one JSON record per post; `"private": true` marks an unpublished test send). |

## HTTP surface (`web.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Dashboard: controls, counts, scheduler state, cached feed. |
| GET | `/review` | Review list, newest first (has the **Scan sources now** button). Optional `?source=<name>&status=<state>` filters, `?q=<text>` title/excerpt search, and `?sort=oldest`; paged with `?page=<n>&per_page=<n>` (default 20, max 200). |
| GET | `/review/{id}` | Review detail: editable caption, hashtags, and image prompt; Save / Post now / Reject, plus Approve & schedule when `publish.post_at` is set (+ Generate image when enabled). |
| GET | `/publish` | Publish audit log (public + private sends). |
| GET | `/status` | Human-readable snapshot: token validity/expiry, schedules, sources. |
| GET | `/drafts` | Redirect (307) to `/review` for old links. |
| GET | `/health` | Liveness + last run info (JSON). |
| GET | `/live` | Liveness probe: `{"status": "alive"}`, never touches state. |
| GET | `/ready` | Readiness probe: 200 when serving, 503 while draining or if a scheduler died / state dir is unwritable. |
| GET | `/api/status` | Full pipeline snapshot (JSON); `publish.next_draft` is the oldest approved draft the poster will send next. |
| POST | `/refresh` | Refresh the feed now. |
| POST | `/scan` | Scan sources now (JSON, or a 303 back to `/review` for browsers). |
| POST | `/publish/run` | Drain the approved queue now (JSON, or a 303 back to `/review`). Still works while paused. |
| POST | `/publish/pause` | Pause the posting scheduler — it skips its slots until resumed (JSON, or a 303 back to `/`); persisted across restarts. |
| POST | `/publish/resume` | Resume the posting scheduler (JSON, or a 303 back to `/`). |
| POST | `/review/{id}/save` | Save the compose edits (caption, hashtags, image prompt); never posts. |
| POST | `/review/{id}/publish` | Publish (form; `dry_run=1` to preview). With `approve=1` it saves the edits and queues the draft as `approved` instead of posting. |
| POST | `/review/{id}/reject` | Reject. |
| POST | `/review/{id}/image` | Generate/regenerate a draft's image (form; redirects back). |
| GET | `/api/drafts` | Open drafts + DNA, for the rewriter. Paged: `?limit=<n>&offset=<n>` (default 100, max 500); the body carries `total`/`has_more`/`next_offset`. |
| POST | `/api/drafts/{id}/rewrite` | Store the rewrite. |
| POST | `/api/drafts/{id}/image` | Generate an image for one draft (JSON), for the rewriter/operator. |

## Extending

**A new source.** Add an entry to `sources` in `config.yaml` (and the
`DEFAULTS["sources"]` example). For a new *format*, add a
`parse_<type>(...) -> list[Item]` in `source.py`, dispatch it in
`parse_source`, allow the type in `config.validate`, and cover it in
`tests/test_source.py`. Fetching itself rarely changes — `source_api` returns
text.

**A new destination.** Add a package under `src/social_bot/destinations/` with a
`Publisher` subclass (`name`, `label`, `describe`, `publish -> PublishResult`),
register it in `destinations/registry.py`, and add its
`DEFAULTS["destinations"]["<name>"]` block + credentials entry.
`config.validate` accepts any registered name. Its `posts[destination]` records
and audit rows flow through unchanged. `linkedin/publisher.py` is a stub showing
the shape; company-page posting needs LinkedIn Community Management API
approval.

**Changing the caption text.** The published text is `Draft.post_text`
(caption + hashtags). Keep hashtags in the `hashtags` field, not the caption.
The series masthead is `publish.mastheads` (clear `choices` to disable).

**Changing the brand voice.** Edit `docs/atento-dna.md` (the brief the rewriter
reads) and keep `publish.dna_file` pointed at it; the contents ride along in
`GET /api/drafts`.

**Changing the image look.** Edit `docs/atento-image-style.md` (the visual brief
prepended to every image prompt) and keep `image_gen.style_file` pointed at it.
Swap the image endpoint/provider with `image_gen.base_url` + `image_gen.model`.

**Changing what a draft stores.** Edit the `Draft` dataclass in `drafts.py`;
`from_dict` ignores unknown keys, so old `queue.json` files still load.

## Guardrails (do not weaken)

- Scanning/refreshing runs on the scheduler; **posting never happens without a
  human approval**. The posting scheduler only posts drafts already in state
  `approved`; it must never approve, rewrite, or touch `extracted`/`ai_draft`.
- `publish_draft` is reached from the explicit **Post now** action, the scheduled
  drain, `POST /publish/run`, and `blog publish`. `publish.post_at: []` disables
  timed posting entirely.
- `publish.enabled: false` is a global kill-switch; `publish.interval_days`
  enforces a minimum gap between public posts (enforced in `publish_draft`).
- `--dry-run` is available on every publish path (`post` command, `blog publish`,
  and `dry_run=1` on `POST /review/{id}/publish`).
- Only the configured official feeds are fetched — no HTML scraping of
  facebook.com, and stay within each site's robots.txt.
- Endpoints are currently **unauthenticated**; do not expose them publicly
  without adding auth.
