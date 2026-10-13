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
  written captions as `recent`; paged — pass
  `limit`/`offset` and follow
  `next_offset`) and
  `POST /api/drafts/{id}/rewrite` with
  `{caption, hashtags, cta, commentary, voice}`.
- `recent` (capped by `publish.recent_captions`, 0 = off) exists so the rewriter
  can see what it just wrote and not reopen the same way twice — the "mọi bài
  một màu" failure is invisible in one draft and obvious across several (DNA §12).
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
- Images need nothing from the rewriter (DNA §9): a post uses its source
  article's own cover, or the operator renders a code-drawn diagram (§2b).
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
- Drafts queued **before** LinkedIn joined the default route carry
  `destinations: ["facebook"]`; `social-bot blog backfill-destinations` unions
  them onto `publish.destinations` (idempotent, never removes, never touches
  the caption/image/state). Re-target one draft on `/review/{id}` or `/queue`.

### 2a. Rewriter worker (`scripts/rewrite_worker.py`, optional)
- The rewrite is normally run by hand (an agent calls `GET /api/drafts` and POSTs
  the result). When `rewrite.enabled` is on, `/review/{id}` also offers a
  **Rewrite with Command Code** button — but it only *marks* the draft
  (`Draft.rewrite_requested_at`); the app never runs the agent itself.
- A host-side worker polls `GET /api/rewrite-queue` (the marked drafts plus the
  DNA, the voice menu, the masthead choices and `recent` captions), attaches the operator's own
  voice itself (§2c — the app neither sends it nor needs to know about it), runs the
  Command Code CLI headlessly per draft (`commandcode -p --output-format json
  --skip-onboarding --max-turns N`, with the whole brief in the prompt so the run
  needs no tools), parses the JSON from the final `result` frame, and POSTs it to
  `POST /api/drafts/{id}/rewrite` — which clears the request. A failure goes to
  `POST /api/drafts/{id}/rewrite-error`, which stores `Draft.rewrite_error` and
  closes the request, so the page shows why nothing came back instead of a request
  that waits forever.
- **Two kinds of request ride that one queue, told apart by `Draft.rewrite_mode`.**
  `caption` is the button above — the whole rewrite, the agent choosing the
  register. `caption-voice` is **Rewrite in this voice**, beside it: the same full
  rewrite with the register pinned to the one picked in the compose form's Voice
  select, for when you want the same idea in a specific voice instead of the one
  the rewriter judges. That button **submits the compose form** (unlike `caption`'s
  field-less form), so the pick is saved with the request.
  `rewrite_worker.build_prompt(..., voice_locked=True)` names
  that key in the output contract and adds a hard rule against substituting
  another, and `draft_pipeline.receive_rewrite` keeps the draft's own voice when
  the pending request was this kind, so a run that ignored the instruction cannot
  relabel the post. The DNA, the voice menu and the mastheads all ride along as
  usual.
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

### 2b. Images (source cover, code-drawn diagram, or a drawn illustration)

- A post uses its **source article's own cover**, captured at scan time
  (enrichment reads the post page for `title`/`excerpt`/`image`). No AI
  generation: nothing is invented, and a post without a cover simply publishes
  without an image (a link post) unless the operator draws one.
- For a **mechanism** post — many parts exchanging with each other — the
  operator renders a **code-drawn plate**: the **Render diagram** button on
  `/review/{id}` (`POST /review/{id}/diagram`), or `social-bot blog diagram`
  for a batch. A plate is a small isometric scene of real objects (a console,
  cabinets, a chest of drawers) drawn from the `iso.py` kit, with every word in
  the margins so nothing has to be scraped or guessed; `diagram.py` is the
  vector source and `diagram_html.py` only **wraps** that SVG in a bare page,
  which `browser_shot` screenshots to PNG through the host's Chromium — the
  draft points at the PNG because Graph only accepts raster, and the PNG and the
  preview cannot drift because they are the same SVG. A missing/failing browser
  never blocks the render: the draft keeps pointing at the SVG preview.
  **The plate is matched to the draft, not fixed**: `diagram_kind` reads the
  draft's topic/title/excerpt and picks a renderer — `write_concern` for MongoDB
  (`w:1` vs `w:majority`), `sparse_index` for ClickHouse — and a draft that
  matches no renderer renders **nothing** rather than borrowing another system's
  plate. A new system is a new renderer plus a branch, in the one house style.
  Rendering fills the gap by default and never replaces an existing image
  without `overwrite` (`blog diagram --overwrite`).
- **Selectively**, an **illustration** may be drawn for a post with the
  `anatomy` skill: a crafted isometric SVG figure, screenshotted to a PNG on the
  same served `/images/` store a diagram uses, that the draft then points at. It
  is for the post whose *idea* needs a drawn picture — a mechanism, a structure,
  an inventory of parts, a before/after — where a figure earns the reader better
  than the source cover or the code plate. It is **not a default and never every
  post**: the source cover stays the norm and the code diagram still owns plain
  wiring. It is a drawn figure (operator-made, via the host-side `anatomy`
  skill), never a generated or photographic image, and it goes through the same
  human gate as any other image. See
  [image-styles/illustration.md](image-styles/illustration.md).
- **The source post's own image is kept on the draft** as `source_image`, written
  at scan time and never touched by rendering. **Restore source image** on
  `/review/{id}` (`POST /review/{id}/restore-image`) always puts the original
  picture back without touching the caption. The draft page offers it whenever
  the current image is a diagram — decided by comparing against `source_image`,
  or, for a draft scanned before that was recorded, by recognising a locally
  stored `/images/...` file — and since a pre-existing draft has no
  `source_image` stored, the restore reads the source page once (as scan
  enrichment does) to recover it and keeps it for next time. Nothing to recover
  (no source URL, no image on the page, an unreachable page) returns a warning,
  never a broken page.
- `blog localize-images` copies a still-remote non-source image into the local
  store (a migration for legacy AI-image drafts; it never renders anything).

### 2c. The operator's own voice (`voice.py`, optional)
- The DNA and the voice menu are **brand** voices; `voice.py` adds the operator's
  **real** one. When `voice.enabled` is on, the rewriter worker retrieves the
  operator's own messages closest to the draft from a local corpus and hands them
  to the agent as `=== MY VOICE ===`, together with the learned `profile.md`.
- The corpus is a directory of normalized JSONL under `voice.corpus_dir`
  (default `data/voice/normalized`), one record per line
  (`{id, chat, source, author, is_me, timestamp, text, …}`) — the shape the twin
  project's ingest writes. It is **migrated into this project**, not imported:
  nothing here imports or calls the twin at runtime. `voice.profile_file` is the
  learned profile that `twin profile` produced.
- Retrieval has three backends (`voice.backend`): `keyword` (pure-Python BM25 over
  the JSONL — no extra dependency, diacritic-folded so `"sinh vien"` matches
  `"sinh viên"`), `vector` (the LanceDB index at `voice.index_dir`, built by
  `social-bot voice index`), and `hybrid` (both, RRF-fused — the default, because
  this corpus is dominated by very short fragments where each ranker misses what
  the other finds). Embeddings come from `voice.embedding.provider`: `local`
  (fastembed) or `openai` (an HTTP `/embeddings` endpoint; its key lives in
  `credentials.yaml` or `SOCIAL_BOT_VOICE_EMBEDDING_API_KEY`). The model must match
  the one that built the index, and a **multilingual** one matters: it is what lets
  an English source excerpt pull Vietnamese lines about the same idea.
- **The hits are style, not substance.** The prompt says so in as many words:
  match the diction, rhythm, teencode level and address terms — never reuse a fact,
  never copy a line verbatim. The division of labour is DNA = structure, voice menu
  = register, `MY VOICE` = how the sentences sound, draft = the facts. This is the
  same rule the twin holds (*retrieval feeds voice, not answers*) — do not restate
  the examples as a source of truth.
- **It is an enhancement, never a gate.** A missing corpus, a missing `[voice]`
  extra, a failed embedding call or simply no matches all degrade to *no block at
  all*: `voice.examples_block` never raises, the worker only warns, and the rewrite
  proceeds with the voice menu alone. Never let voice retrieval fail a rewrite.
- `voice.only_me` (default true) keeps examples to the operator's own writing;
  `voice.top_k` caps how many ride along and `voice.max_examples_chars` caps the
  rendered block.
- **Every candidate must clear a relevance gate before it reaches the prompt**
  (`voice._is_example`): `has_voice` (a bare link teaches no voice),
  `voice.min_example_words` (default 3 — a shared URL and a two-word ack are not
  style), and the one that matters, an **absolute cosine floor**
  `voice.min_similarity` (default 0.55). Measured on this corpus, unrelated chat
  sits at 0.46–0.50 while a genuine topical match reaches 0.55+, so the floor
  separates them cleanly. **BM25 cannot make that call** — its scores for junk
  (8.8–10.6) overlap a good match's (8.9–16.8) — so under `hybrid` only rows the
  semantic ranker vetted may pass; a lexical-only row is dropped even if BM25
  ranked it first. The consequence is deliberate: a draft whose topic this corpus
  does not really cover (an English article, typically) yields **no examples at
  all**, and the block is the profile alone. That beats handing the model
  `in CZ we trust` for a piece on long-context recall. Lower `min_similarity` to
  `0` to disable the floor; `0` for `min_example_words` disables the length gate.
- The `[voice]` extra (`lancedb`, `pyarrow`, `fastembed`) is needed **wherever the
  worker runs**, not by the serve container — which is why it is an extra rather
  than a core dependency.
- CLI: `social-bot voice index` (rebuild after the corpus changes),
  `voice search "<topic>" [--show]` (what would be retrieved, and the exact block
  the worker would attach), `voice status` (paths and corpus counts).
- Image tasks never get the block: an image prompt is an English visual concept,
  where a chat register is beside the point.

### 2d. Idea seeds — original posts, not reposts (`draft_pipeline.queue_ideas`)
- `sources[]` are feeds to **repost**: each has a URL, is fetched, and the caption
  credits an external author. The `ideas` block is a different input on purpose — a
  plain list of **systems** to write *original* posts about.
  `ideas.topics_file` is a markdown file, one theme per line with an optional
  `| <docs url>` (Elasticsearch, ClickHouse, Loki, Grafana, MySQL, MongoDB,
  Kafka, System Design, …); the operator edits it live, no restart needed.
  **Nothing is fetched, nothing is reposted** — the agent draws on its own
  knowledge of each system. Keep the entries at the level of the **system**
  (*Kafka*, *ClickHouse architecture*, *System design*) and let each post go
  deep in **one** aspect, grounded in a real problem — approachable for a reader
  who knows the basics, not an internals tour.
- The app never generates the ideas itself (the same rule as the rewriter). A
  human asks for a batch from `/review` (**Generate ideas**,
  `POST /review/request-ideas`) or `blog ideas --request`; that only *marks* the
  request (`data/ideas/state.json`). The same host-side worker
  (`scripts/rewrite_worker.py`) polls `GET /api/ideas`, and when `requested` is set
  it proposes a batch — `build_ideas_prompt` carries the themes, the DNA, the
  titles already queued and the recent captions so nothing repeats — and POSTs
  `{"ideas": [{"title", "topic", "excerpt"}, …]}` to `/api/ideas`.
- `queue_ideas` turns each idea into an `EXTRACTED` draft: `source:
  ideas.source_name` (`atento-original`), the specific angle as `title`, the system
  as the new `Draft.topic`, a short outline as `excerpt`, and **no `url` and no
  source image** — an original post has no article to link. A slug of the title is
  the id, deduped against the queue and `data/ideas/seen.json`, so re-running a
  batch is safe. A successful batch closes the request; a failed run goes to
  `POST /api/ideas/error`.
- From there it is an ordinary draft: the rewrite writes the caption from the idea,
  a human approves on `/review/{id}`, and the poster sends it. A generated idea
  only ever reaches `EXTRACTED`; the pipeline never posts one on its own.
- DNA: an original draft has no article to link, so §7.3's credit rule does not
  apply and the caption carries no "đọc đầy đủ tại comment" CTA (DNA §6.6); the
  masthead defaults to `[Học cùng Atento]` (it is Atento teaching). Image: none
  from a source — leave it text-only, or draw a code diagram / `anatomy` figure.
- CLI: `blog topics` (list the themes), `blog ideas [--request] [--json]` (the
  brief, and the optional request), `blog add-idea "<title>" [--topic …]
  [--excerpt …]` (seed one by hand, same dedupe).

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
  `blog publish` still send, because those are explicit human actions. (The
  *interval* draws its line elsewhere: the drain paths — **Post approved now**,
  `blog publish` — obey it, the two per-draft buttons don't.)
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

The operator's own voice (§2c) keeps its own state, outside the pipeline's
`review.dir`/`publish.dir`:

| File | Contents |
|---|---|
| `data/voice/normalized/*.jsonl` | The operator's own messages — the corpus `voice.py` searches. Migrated from the twin project; nothing here imports the twin. |
| `data/voice/index/` | The LanceDB vector index (`social-bot voice index`). Only valid for the embedding model that built it. |
| `data/voice/profile.md` | The learned voice profile, attached to every rewrite as part of `MY VOICE`. |

The idea seeds (§2d) keep their own state under `ideas.dir`:

| File | Contents |
|---|---|
| `data/ideas/topics.md` | The systems/themes original posts are drawn from — `ideas.topics_file`, edited live by the operator. |
| `data/ideas/seen.json` | Title slugs of ideas already queued (dedupe). |
| `data/ideas/state.json` | The pending "generate ideas" request (`requested_at`, `note`, `error`). |

## HTTP surface (`web.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Factory dashboard: controls, counts, scheduler state, cached feed. |
| GET | `/queue` | Post queue: the approved drafts in posting order, with the reorder controls and the **Post approved now** button (when `publish.post_at` is set). |
| GET | `/review` | Review queue list, newest first (has the **Scan sources now** button). Optional `?source=<name>&status=<state>` filters, `?q=<text>` title/excerpt search, and `?sort=oldest`; paged with `?page=<n>&per_page=<n>` (default 20, max 200). |
| GET | `/review/{id}` | Review detail: editable caption and hashtags; the destination picker (per-platform chips) and one **Post to &lt;Platform&gt;** button per pending destination; Save / Reject, plus Approve & schedule when `publish.post_at` is set (+ Unapprove on an approved draft, + Render diagram, + Restore source image when the image is a diagram). |
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
| POST | `/review/{id}/request-voice-rewrite` | Mark the draft for a rewrite **in the voice picked on this page**: the compose form is saved first, so the Voice select reaches the worker and is re-asserted on the result. Same gate as `/request-rewrite`; never rewrites itself. |
| POST | `/review/{id}/cancel-rewrite` | Drop a pending rewrite request (any kind). |
| POST | `/review/request-ideas` | Mark that a batch of original post ideas was asked for (`ideas.topics_file` systems); the host-side worker proposes it. Never generates, rewrites, or posts. |
| POST | `/queue/{id}/move` | Move an approved draft in the post queue (`direction=up\|down\|top\|bottom`, plus a `next` return path — the queue page sends `/queue#post-queue`); never posts. |
| POST | `/queue/order` | Persist a drag-and-drop reorder: JSON `{"ids": [...]}` (a subset is fine), returns `{"ok": true, "order": [...]}`. |
| POST | `/queue/reset` | Clear every manual position, restoring the default oldest-first order. |
| GET | `/api/drafts` | Open drafts + DNA (`dna`) + the voice menu (`voices`, `voice_choices`, `default_voice`) + `recent` captions, for the rewriter. Paged: `?limit=<n>&offset=<n>` (default 100, max 500); the body carries `total`/`has_more`/`next_offset`. |
| POST | `/api/drafts/{id}/rewrite` | Store the rewrite. |
| GET | `/api/rewrite-queue` | The drafts a human asked the rewriter for, plus the brand context (DNA, voices, mastheads, `recent` captions) — polled by the host-side rewriter worker. Each draft carries `rewrite_mode` (`caption` or `caption-voice`), which decides the worker's prompt. |
| POST | `/api/drafts/{id}/rewrite-error` | Record the rewriter worker's failure and close the request; shown on `/review/{id}`. |
| GET | `/api/ideas` | The idea brief for the rewriter agent: the theme systems (`topics`), the titles already queued (`existing`), the DNA and `recent` captions — plus whether a batch was requested (`requested`/`requested_at`). Polled by the worker. |
| POST | `/api/ideas` | Queue agent-proposed original-post ideas as `extracted` drafts (`source: ideas.source_name`, no URL); body `{"ideas": [{"title", "topic", "excerpt"}, …]}` (a single idea object is accepted too), deduped by title slug, closes the request. Never rewrites, approves, or posts. |
| POST | `/api/ideas/error` | Record the worker's idea-generation failure and close the request. |

## Extending

**A new source.** Add an entry to `sources` in `config.yaml` (and the
`DEFAULTS["sources"]` example). For a new *format*, add a
`parse_<type>(...) -> list[Item]` in `source.py`, dispatch it in
`parse_source`, allow the type in `config.validate`, and cover it in
`tests/test_source.py`. Fetching itself rarely changes — `source_api` returns
text.

**A new idea theme.** Just add a line to `ideas.topics_file`
(`data/ideas/topics.md` by default) — no code and no restart. A theme is a
*system* (a name, optional `| <docs url>`), never a feed; the agent does the rest.
To change the *mechanism* (where the themes live, how ideas are queued), it is
`src/social_bot/ideas.py` (pure parse + slug) and `draft_pipeline.idea_brief` /
`queue_ideas`, tested in `tests/test_ideas.py` / `tests/test_draft_pipeline.py`.

**A new destination.** Add a package under `src/social_bot/destinations/` with a
`Publisher` subclass (`name`, `label`, `describe`, `publish -> PublishResult`),
register it in `destinations/registry.py`, and add its
`DEFAULTS["destinations"]["<name>"]` block + credentials entry.
`config.validate` accepts any registered name. Its `posts[destination]` records
and audit rows flow through unchanged. `linkedin/publisher.py` shows the shape of
a destination that **delegates to another local service**: it calls linkin-bot's
`POST /post` gateway (text + the image bytes as base64) instead of talking to the
platform API, so no token/OAuth lives here.

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

**Changing what the agent sounds like.** The rewriter gets four inputs, and each
owns a different thing: the DNA (`publish.dna_file` — structure), the voice menu
(`publish.voices` — which register), `voice.py`'s `MY VOICE` block (§2c — the
operator's own retrieved lines + `profile.md`, i.e. how the sentences sound), and
the draft (the facts). To change the last of those, edit the corpus under
`voice.corpus_dir` and re-run `social-bot voice index`; to change how much of it
rides along, tune `voice.top_k` and `voice.max_examples_chars`.

**Changing the image look.** Diagrams are drawn by `diagram.py` (the SVG
source) with `diagram_html.py` porting the same plate to HTML for the PNG
screenshot — edit those two together so the preview and the upload never
disagree. A new diagram is a new renderer plus a branch in
`render_for_draft`/`render_for_draft_html`.

**Changing what a draft stores.** Edit the `Draft` dataclass in `drafts.py`;
`from_dict` ignores unknown keys, so old `queue.json` files still load.

## Guardrails (do not weaken)

- Scanning/refreshing runs on the scheduler; **posting never happens without a
  human approval**. The posting scheduler only posts drafts already in state
  `approved`; it must never approve, rewrite, or touch `extracted`/`ai_draft`.
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
