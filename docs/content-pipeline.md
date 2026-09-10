# Content pipeline

Turns items from external source feeds into **human-approved** Facebook Page
posts, with an external AI doing the rewrite.

## Flow

```
 source feeds                 drafts/                       review                publish
 ────────────                 ──────                       ──────                ───────
 index|sitemap|rss  ─scan─▶  extracted  ─rewrite API─▶  ai_draft  ─human OK─▶  posted
 (source.py)      (draft_pipeline)      (draft_pipeline)           (publishers)
```

The rewrite is done by an **external agent** (Command Code applying the Atento
DNA), not by this codebase. The bot only exposes the drafts and accepts the
result back. The scheduler never publishes; only a human approve does.

## State machine (`drafts.py`)

| State | Meaning |
|---|---|
| `extracted` | Scanned from a source; awaiting a rewrite. |
| `ai_draft` | A rewrite has been stored; awaiting human review. |
| `approved` | Explicitly approved (optional — publishing is allowed from `ai_draft` too). |
| `posted` | Published; `post_id`/`permalink`/`posted_at` set and audited. |
| `rejected` | Dismissed; not published. |

Transitions: `extracted → ai_draft` (`Draft.apply_rewrite`), `ai_draft|approved
→ posted` (`Draft.mark_posted`), any `→ rejected` (`Draft.reject`).
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

### 2. Rewrite (`draft_pipeline.receive_rewrite`)
- The agent calls `GET /api/drafts` (returns open drafts + `publish.dna_file`
  contents as `dna`) and `POST /api/drafts/{id}/rewrite` with
  `{caption, hashtags, cta, alt_text, commentary}`.
- Stored via `Draft.apply_rewrite`; the draft becomes `ai_draft`.

### 3. Review (human)
- `/review` lists open drafts; `/review/{id}` shows the extracted info, the
  editable caption + hashtags, and Approve / Reject. Rendered by
  `draft_html.render_draft_html`.
- `/publish` lists the audit log (what has actually been posted); `/status`
  shows sources, drafts by state, and publish settings. `/` is the dashboard
  with the refresh/scan controls. All four share the nav from `ui.py`.

### 4. Publish (`draft_pipeline.publish_draft`)
- Triggered only by `POST /review/{id}/publish` (the review page), parsed in
  `web.py`. Validates `can_publish()`, then selects a publisher per destination
  from `publishers.PUBLISHERS`.
- `FacebookPublisher` posts `Draft.post_text` (**caption + hashtags**) — a photo
  post via `create_photo_post` when `image` is set, else a link post via
  `create_post`.
- `dry_run=True` prints the request and mutates nothing.
- With `publish.private: true` every destination sends **unpublished**
  (`published=false` on the Graph call, visible to page admins only). The call
  is real — it just doesn't go public — so the draft stays in the queue and the
  record in `published.jsonl` gets `"private": true`. Private sends don't count
  toward `publish.max_per_day`.
- On a public success: `mark_posted`, append to `published.jsonl`, save.

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
| GET | `/review` | Review list (has the **Scan sources now** button). |
| GET | `/review/{id}` | Review detail: editable caption, Dry run / Approve / Reject. |
| GET | `/publish` | Publish audit log (public + private sends). |
| GET | `/status` | Human-readable pipeline snapshot. |
| GET | `/drafts` | Redirect (307) to `/review` for old links. |
| GET | `/health` | Liveness + last run info. |
| GET | `/api/status` | Full pipeline snapshot (JSON). |
| POST | `/refresh` | Refresh the feed now. |
| POST | `/scan` | Scan sources now (JSON, or a 303 back to `/review` for browsers). |
| POST | `/review/{id}/publish` | Publish (form; `dry_run=1` to preview). |
| POST | `/review/{id}/reject` | Reject. |
| GET | `/api/drafts` | Open drafts + DNA, for the rewriter. |
| POST | `/api/drafts/{id}/rewrite` | Store the rewrite. |

## Extending

**A new source.** Add an entry to `sources` in `config.yaml` (and the
`DEFAULTS["sources"]` example). For a new *format*, add a
`parse_<type>(...) -> list[Item]` in `source.py`, dispatch it in
`parse_source`, allow the type in `config.validate`, and cover it in
`tests/test_source.py`. Fetching itself rarely changes — `source_api` returns
text.

**A new destination.** Add a class in `publishers.py` with `name`, `describe`,
and `publish(draft) -> {destination, post_id, permalink}`, register it in
`PUBLISHERS`, and add the name to the allowed set in `config.validate`.
`LinkedInPublisher` is a stub showing the shape; company-page posting needs
LinkedIn Community Management API approval.

**Changing the caption text.** The published text is `Draft.post_text`
(caption + hashtags). Keep hashtags in the `hashtags` field, not the caption.

**Changing the brand voice.** Edit `docs/atento-dna.md` (the brief the rewriter
reads) and keep `publish.dna_file` pointed at it; the contents ride along in
`GET /api/drafts`.

**Changing what a draft stores.** Edit the `Draft` dataclass in `drafts.py`;
`from_dict` ignores unknown keys, so old `queue.json` files still load.

## Guardrails (do not weaken)

- Scanning/refreshing runs on the scheduler; **publishing never does**.
- `publish_draft` is only reached from the explicit approve action.
- `publish.enabled: false` is a global kill-switch; `publish.max_per_day` caps
  posts/day (enforced in `publish_draft`).
- `--dry-run` is available on every publish path (`post` command and the review
  page).
- Only the configured official feeds are fetched — no HTML scraping of
  facebook.com, and stay within each site's robots.txt.
- Endpoints are currently **unauthenticated**; do not expose them publicly
  without adding auth.
