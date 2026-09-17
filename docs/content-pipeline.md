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
DNA), not by this codebase — run by hand, or by the optional host-side worker
(§2a). The bot only exposes the drafts and accepts the result back. The scan and
refresh loops never publish. Publishing only ever happens for drafts a human
approved: the posting scheduler (`publish.post_at`) picks *when* an approved
draft goes out — it never approves anything itself.

## State machine (`drafts.py`)

| State | Meaning |
|---|---|
| `extracted` | Scanned from a source; awaiting a rewrite. |
| `ai_draft` | A rewrite has been stored; awaiting human review. |
| `approved` | Human-approved. Queued for the next posting slot (`publish.post_at`) — or posted immediately if approved with "Post now". Reversible with **Unapprove** until it posts. |
| `posted` | Published; `post_id`/`permalink`/`posted_at` set and audited. |
| `rejected` | Dismissed; not published. |

Transitions: `extracted → ai_draft` (`Draft.apply_rewrite`), `ai_draft|approved
→ posted` (`Draft.mark_posted`), `ai_draft → approved` (`Draft.approve`),
`approved → ai_draft` (`Draft.unapprove`), any
`→ rejected` (`Draft.reject`).
`can_receive_rewrite()` = `extracted|ai_draft`; `can_publish()` = `ai_draft|approved`.
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

### 2. Rewrite (`draft_pipeline.receive_rewrite`)
- The agent calls `GET /api/drafts` (open drafts + `publish.dna_file` contents
  as `dna` + the **voice menu** `publish.voices` as `voices` (`{key: brief +
  samples}`, with `voice_choices` and `default_voice`) + the most recently
  written captions as `recent` + the **treatment briefs** as `image_style_briefs`
  and the last few image prompts as `recent_images`; paged — pass
  `limit`/`offset` and follow
  `next_offset`) and
  `POST /api/drafts/{id}/rewrite` with
  `{caption, hashtags, cta, commentary, image_prompt, image_style, voice}`.
- `recent` (capped by `publish.recent_captions`, 0 = off) exists so the rewriter
  can see what it just wrote and not reopen the same way twice — the "mọi bài
  một màu" failure is invisible in one draft and obvious across several (DNA §12).
- `recent_images` (capped by `publish.recent_images`, same idea) does that job for
  the **image**: the last few `image_prompt`/`image_style` pairs, so a rewriter
  can see it has illustrated the same object five posts running and pick another.
  Nothing else tells it — which is why the DNA used to *mandate* "a different
  metaphor per post" instead, a rule that fought any treatment which is not a
  metaphor. `image_style_briefs` carries each configured treatment's text, so the
  rewriter writes a prompt that serves the style it picked rather than guessing
  from a key name.
- **The caption is linted, advisory only** (`caption_lint.lint_caption`, alongside
  `receive_rewrite`/`edit_draft`). It names the AI-writing tells — a repeated
  hook/closer versus `recent`, a stock opener, the "không phải X mà là Y" engine,
  a flat sentence rhythm, the rule of three ("nhanh, gọn, chính xác"), a cliché
  transition, empty hype — and stores them on the draft (`lint`), shown on
  `/review/{id}` and returned in the rewrite response. It **never edits the
  caption and never blocks** a rewrite or a post: rule-based auto-"humanizing"
  just swaps one tell for another. The fixes belong in `docs/atento-dna.md` §12.
- Stored via `Draft.apply_rewrite`; the draft becomes `ai_draft`.
- `publish.mastheads` (config.yaml) sets the series masthead on line 1 of every
  caption. The label is a **content judgment, not a source default**: the
  rewriter picks one of `mastheads.choices` per post (DNA §4.5 — knowledge worth
  learning → Học, merely informational → Đọc báo, a one-idea nugget → Mỗi ngày).
  `mastheads.default` is only the fallback the pipeline prepends when the
  rewriter omits one. It lands in `caption`, so the review preview, the
  character count, and the posted text all include it.
- `publish.voices` (config.yaml) is the same keyed-menu pattern for the caption's
  **voice/register**: a menu of `key → docs/voices/<key>.md`, of which the
  rewriter picks one per post by content (DNA §3), stored on the draft as `voice`.
  Each file is the register's brief **plus** a growing `Samples` corpus of verbatim
  human writing — that corpus is how a voice improves over time. A valid key is
  kept, an unknown or omitted one falls back to `publish.default_voice`, and it is
  **overridable on `/review/{id}`**, where the select's hint is each voice file's
  own opening "when to use" paragraph (`draft_pipeline.voice_hints`) and the
  register the caption was actually rewritten in is labelled **`<key> (current)`**
  (and is the default selection), so any other option reads as the next one. The
  whole menu (brief + samples) rides along
  as `GET /api/drafts` `voices`. Overriding it and pressing **Rewrite in this
  voice** (§2a) is what makes the pick the *instruction* rather than a note: the
  other rewrite button lets the rewriter choose.
- `image_gen.styles` (config.yaml) is the same pattern for the image's **visual
  treatment**: a menu of `key → docs/image-styles/<key>.md`, of which the
  rewriter picks one per post by content and tone (DNA §9.2). The key is stored
  on the draft as `image_style`; `image_gen.default_style` is the fallback when
  the rewriter omits one. At prompt time (`draft_pipeline.image_style_text`) the
  chosen treatment **leads** and the shared `style_file` palette follows, so the
  medium, the composition and what to avoid all vary per post while the palette
  stays constant. That is the whole rule: a treatment file carries its own
  prohibitions — people, lettering, the clichés — and nothing outside it forbids
  anything, so no look can be fought by a rule written somewhere else. `diagram`
  is the one treatment that writes: it carries a title and labelled parts, which
  its file states and the DNA §9.2 tells the rewriter how to feed. A valid
  key is kept, an unknown one falls back to the default — and it is
  **overridable on `/review/{id}`** before regenerating, where the select's hint
  is each style file's own opening paragraph (`draft_pipeline.image_style_hints`)
  so the operator reads the same "when to use" guidance as the docs. Clearing
  `styles` restores the single `style_file` look.
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

### 2a. Rewriter worker (`scripts/rewrite_worker.py`, optional)
- The rewrite is normally run by hand (an agent calls `GET /api/drafts` and POSTs
  the result). When `rewrite.enabled` is on, `/review/{id}` also offers a
  **Rewrite with Command Code** button — but it only *marks* the draft
  (`Draft.rewrite_requested_at`); the app never runs the agent itself.
- A host-side worker polls `GET /api/rewrite-queue` (the marked drafts plus the
  DNA, the voice menu, the masthead/`image_style` choices, the treatment briefs
  themselves, `recent` captions and `recent_images`), runs the
  Command Code CLI headlessly per draft (`commandcode -p --output-format json
  --skip-onboarding --max-turns N`, with the whole brief in the prompt so the run
  needs no tools), parses the JSON from the final `result` frame, and POSTs it to
  `POST /api/drafts/{id}/rewrite` — which clears the request. A failure goes to
  `POST /api/drafts/{id}/rewrite-error`, which stores `Draft.rewrite_error` and
  closes the request, so the page shows why nothing came back instead of a request
  that waits forever.
- **Three kinds of request ride that one queue, told apart by `Draft.rewrite_mode`.**
  `caption` is the button above — the whole rewrite, the agent choosing the
  register. `caption-voice` is **Rewrite in this voice**, beside it: the same full
  rewrite with the register pinned to the one picked in the compose form's Voice
  select, for when you want the same idea in a specific voice instead of the one
  the rewriter judges. That button **submits the compose form** (like the two image
  tools, and unlike `caption`'s field-less form), so the pick is saved with the
  request — it used to be dropped here *and* at the worker, which then chose a
  register of its own. `rewrite_worker.build_prompt(..., voice_locked=True)` names
  that key in the output contract and adds a hard rule against substituting
  another, and `draft_pipeline.receive_rewrite` keeps the draft's own voice when
  the pending request was this kind, so a run that ignored the instruction cannot
  relabel the post. The DNA, the voice menu and the mastheads all ride along as
  usual. `image` is **Regenerate
  image prompt**: the caption is settled (often already approved) and only the
  picture is wrong, so the worker runs a much smaller task
  (`rewrite_worker.build_image_prompt` — the treatment briefs, the recent images,
  and the post's own caption; no DNA, no voice menu, no mastheads) and posts **one
  field, `image_prompt`** — the subject — to
  `POST /api/drafts/{id}/image-prompt`. That stores it through
  `Draft.apply_image_prompt` and **stops — the prompt is the whole delivery,
  nothing is rendered**. The style is the operator's pick, saved from the compose
  form with the request: the worker writes *for* it and never returns one of its
  own (`receive_image_prompt` ignores `image_style`). The new prompt lands on
  `/review/{id}` to be read (or edited), and **Regenerate image** is the separate
  move that spends it on a picture; the caption and the draft's state are
  untouched, so an approved post stays queued. One flag plus one kind means "a
  caption rewrite and an image rewrite are both pending" cannot exist — the
  operator's latest ask wins.
- It runs on the **host**, not in the app: the CLI and its auth live there (the
  container image is python-slim with no Node), and headless runs need no
  `--yolo` — the rewriter only reads its prompt and prints JSON, so file writes
  and shell stay blocked. Start it beside the service (see
  [operations.md](operations.md)).
- Only `extracted`/`ai_draft` drafts can be requested (`can_receive_rewrite`): an
  `approved` draft is already queued to post, so a rewrite would have to undo the
  approval. `/review/{id}` shows the pending state with **Cancel rewrite**, and
  the page reloads itself once the request clears (`GET /api/status` →
  `rewrite.requested`).
- It never approves or posts: the worker reaches the same `receive_rewrite` path a
  manual rewrite uses, and the human gate is untouched.

### 2b. Images (`image_gen.py`, optional)
- Images are generated **after** the rewrite, on demand via
  `social-bot blog image`, the **Generate image** button on `/review/{id}`, or
  `POST /api/drafts/{id}/image`. The rewriter supplies `image_prompt` — a
  concrete English visual concept for that post — and that is what gets
  illustrated. It is also the image's alt text (there is no separate Vietnamese
  alt), and it is **editable on `/review/{id}`** (saved with the caption), as is
  the draft's `image_style` treatment. That pick is the operator's dial and it
  governs **both** image buttons. The style picker names the treatment the current
  image was generated with: that option is labelled **`<key> (current)`** (and is
  the default selection), so any other option reads as the next one. The label is
  dropped while a regeneration is running, when the stored style is already the
  new one but the image on screen is not.
  **Regenerate image** submits the compose form to `/review/{id}/image`, so the
  edited prompt and style are saved and used for that generation (it also saves
  the caption/hashtags, like Save). The button only appears when
  `image_gen.enabled` is true.
  **Regenerate image prompt** beside it is the other direction: instead of
  rendering what the form says, it asks the worker (above) for a fresh prompt — and
  stops there. The two are deliberately separate moves, so the new prompt can be
  read (and edited) before **Regenerate image** spends it on a picture. It submits
  the compose form too, so the style you picked is saved with the request and the
  agent writes the subject *for* that treatment rather than choosing one of its own
  (a field-less button dropped the pick, and the worker fell back to the draft's old
  style). It is the path that repairs a draft whose prompt was written before the
  current image rules.
- `blog image` batches, and the **Regenerate image** button runs the provider
  call **in the background** (like the post-rewrite fill): the request returns
  at once and the page shows the job, instead of holding the connection open for
  the minutes a `gpt-image` model can take. The JSON API
  (`POST /api/drafts/{id}/image`) is still synchronous.
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
  - `/review/{id}` shows it in the UI: "Generating…" while running (the page
    polls `/api/status` and reloads when the job finishes — unless there are
    unsaved edits, when it says the image is ready instead), the error text on
    failure (even when a previous image is still in place), and "No image yet"
    otherwise.
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
- **The source post's own image is kept on the draft** as `source_image`, written
  at scan time and never touched by generation. A generation can therefore only
  ever *add* an image, and **Restore source image** on `/review/{id}`
  (`POST /review/{id}/restore-image`) always puts the original picture back
  without touching the caption. The draft page offers it whenever the current
  image came from `image_gen` — decided by comparing against `source_image`, or,
  for a draft scanned before that was recorded, by recognising the generator's
  own URL — and since a pre-existing draft has no `source_image` stored, the
  restore reads the source page once (as scan enrichment does) to recover it and
  keeps it for next time. Nothing to recover (no source URL, no image on the
  page, an unreachable page) returns a warning, never a broken page.
- The prompt (`image_gen.build_prompt`) leads with the draft's chosen
  `image_style` treatment (medium, composition and prohibitions —
  `docs/image-styles/<key>.md`), then the `image_gen.style_file` shared palette,
  then the subject (`image_prompt`, under a plain `Subject:` label). The builder
  adds no prohibitions of its own: every one of them belongs to the treatment,
  so a look is never fought by a rule written elsewhere.
  `image_gen.base_url` selects the endpoint
  (`gen.pollinations.ai/image` — clean output, needs `api_key`;
  `image.pollinations.ai/prompt` — keyless but watermarked and `sana`-only).
- A failure is recorded in the summary `errors` and the draft keeps its
  existing image: image generation never blocks the pipeline.

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
- Actions: **Save** (persist the caption, hashtags, and image prompt without
  posting) and **Post now** (publish immediately) always; **Reject**. A draft
  whose image came from `image_gen` also offers **Restore source image**, which
  swaps the source post's own picture back in and leaves the caption alone.
  With `rewrite.enabled` on, `extracted`/`ai_draft` drafts also offer the two
  rewriter buttons — **Rewrite with Command Code** (the agent picks the voice) and
  **Rewrite in this voice** (the Voice select above is the instruction) — see §2a.
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
  slot it drains the `approved` queue **in posting order** — drafts an operator
  has moved (their `queue_order`, see below) first, then the rest **oldest
  first** (FIFO) — up to `publish.post_per_slot` per slot, calling
  `publish_draft` per draft — so
  the kill-switch, interval and destination adapters are shared with the
  on-demand path. It never approves, rewrites, or touches `extracted`/`ai_draft`
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
  approve, rewrite, or post: a draft only enters the queue by human approval.
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
| `data/review/queue.json` | The queue (list of drafts). Each carries `queue_order` (0 = the default oldest-first position). Written atomically (tmp + rename). |
| `data/review/seen.json` | `"source:slug"` dedupe ledger. |
| `data/publish/published.jsonl` | Append-only publish audit (one JSON record per post; `"private": true` marks an unpublished test send). |

## HTTP surface (`web.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Factory dashboard: controls, counts, scheduler state, cached feed. |
| GET | `/queue` | Post queue: the approved drafts in posting order, with the reorder controls and the **Post approved now** button (when `publish.post_at` is set). |
| GET | `/review` | Review queue list, newest first (has the **Scan sources now** button). Optional `?source=<name>&status=<state>` filters, `?q=<text>` title/excerpt search, and `?sort=oldest`; paged with `?page=<n>&per_page=<n>` (default 20, max 200). |
| GET | `/review/{id}` | Review detail: editable caption, hashtags, and image prompt; Save / Post now / Reject, plus Approve & schedule when `publish.post_at` is set (+ Unapprove on an approved draft, + Generate image when enabled, + Restore source image when the image came from the generator). |
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
| POST | `/review/{id}/image` | Save the compose edits and regenerate the draft's image in the background (form; redirects back immediately; the page then shows the job). |
| POST | `/review/{id}/restore-image` | Put the source post's own image back, replacing a generated one (reads the source page once when the draft has no stored original). |
| POST | `/review/{id}/request-rewrite` | Mark the draft for the host-side rewriter worker (`rewrite.enabled`); never rewrites itself. |
| POST | `/review/{id}/request-image-prompt` | Mark the draft for a *prompt-only* rewrite: a fresh `image_prompt`/`image_style` from the worker, then a re-render. Allowed on an approved draft; never rewrites itself. |
| POST | `/review/{id}/request-voice-rewrite` | Mark the draft for a rewrite **in the voice picked on this page**: the compose form is saved first, so the Voice select reaches the worker and is re-asserted on the result. Same gate as `/request-rewrite`; never rewrites itself. |
| POST | `/review/{id}/cancel-rewrite` | Drop a pending rewrite request (any kind). |
| POST | `/queue/{id}/move` | Move an approved draft in the post queue (`direction=up\|down\|top\|bottom`, plus a `next` return path — the queue page sends `/queue#post-queue`); never posts. |
| POST | `/queue/order` | Persist a drag-and-drop reorder: JSON `{"ids": [...]}` (a subset is fine), returns `{"ok": true, "order": [...]}`. |
| POST | `/queue/reset` | Clear every manual position, restoring the default oldest-first order. |
| GET | `/api/drafts` | Open drafts + DNA (`dna`) + the voice menu (`voices`, `voice_choices`, `default_voice`) + `recent` captions + the image treatment briefs (`image_style_briefs`) + `recent_images` prompts, for the rewriter. Paged: `?limit=<n>&offset=<n>` (default 100, max 500); the body carries `total`/`has_more`/`next_offset`. |
| POST | `/api/drafts/{id}/rewrite` | Store the rewrite. |
| POST | `/api/drafts/{id}/image-prompt` | Store a prompt-only rewrite (`image_prompt`, `image_style`) and re-render the image with `overwrite`; the caption and the draft's state are untouched. |
| POST | `/api/drafts/{id}/image` | Generate an image for one draft (JSON), for the rewriter/operator. |
| GET | `/api/rewrite-queue` | The drafts a human asked the rewriter for, plus the brand context (DNA, voices, mastheads, image styles **and their briefs**, `recent` captions, `recent_images`) — polled by the host-side rewriter worker. Each draft carries `rewrite_mode` (`caption`, `caption-voice` or `image`), which decides the worker's prompt and the endpoint it posts back to. |
| POST | `/api/drafts/{id}/rewrite-error` | Record the rewriter worker's failure and close the request; shown on `/review/{id}`. |

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
`GET /api/drafts` as `dna`. The **per-post voices** are the same idea for one
register each: `publish.voices` → `docs/voices/<key>.md` with
`publish.default_voice`; add, edit, or remove a voice there (the DNA §3 index
documents the menu for the rewriter). Each voice file carries its brief **and** a
growing `Samples` corpus — add real human-written lines to it to sharpen that
voice. The DNA stays the structural contract (masthead, formats, hashtags/CTA,
output JSON); a voice file only refines how one register sounds.

**Changing the image look.** Edit `docs/atento-image-style.md` (the shared
palette prepended to every image prompt) and keep
`image_gen.style_file` pointed at it. The per-post **treatment** menu is
`image_gen.styles` → `docs/image-styles/<key>.md` with `image_gen.default_style`;
add, edit, or remove a treatment by writing its file and listing it there (the
DNA §9.2 table documents the menu for the rewriter). A treatment's file owns
everything else about its look — medium, composition, and what to avoid,
including whether the image may carry lettering, as `diagram` does. Nothing
outside the file forbids anything, so no config key or prompt rule has to be
told about a new treatment.
Swap the image endpoint/provider with `image_gen.base_url` +
`image_gen.model`.

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
