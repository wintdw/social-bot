# AGENTS.md — social-bot

Guidance for agents and humans working on this project. Read before touching
code or running anything.

## What this project is

A Python CLI that reads and writes a **Facebook Page through the official
Graph API** — no browser anywhere. `whoami` validates the access token and
lists manageable pages, `feed` fetches the page's own feed, `post` creates a
status/link/photo post, `refresh` caches the feed, `blog scan` queues new items
from source feeds as drafts, `blog image` generates AI images for queued
drafts, and `serve` runs a long-lived feed dashboard + a draft review UI +
scheduled refresh/scan. Skeleton cloned from the voz-bot/otofun-bot family
(cli/config/tests/Docker layout); the crawl engine is replaced by `api.py`, a
~150-line urllib Graph client.

**Detailed docs live in `docs/`** — read `docs/README.md` first (module map +
"where to work"), then `content-pipeline.md`, `operations.md`, `development.md`.

## Architecture

```
src/social_bot/
├── cli.py            # entry point (social-bot): whoami, feed, post, refresh, blog scan/image, serve
├── config.py         # DEFAULTS + config.yaml + credentials.yaml; token resolution
├── api.py            # urllib Graph client: GET/POST + ApiError from FB payloads
├── feed.py           # pure parse/render of /{page}/feed JSON -> markdown
├── feed_html.py      # pure render of feed items -> HTML (section + standalone page)
├── refresh.py        # fetch feed -> data/feed/latest.{json,html}; cache reader (refresh/serve)
├── source.py         # pure parse of sitemap / RSS / Atom -> Item (no network)
├── source_api.py     # urllib source fetcher: retries + SourceError
├── drafts.py         # Draft model + state machine + atomic persistence
├── draft_pipeline.py # scan sources -> drafts; generate images; receive rewrite; publish
├── image_gen.py      # urllib Pollinations client: prompt build + image generation
├── publishers.py     # destination adapters: Facebook (real), LinkedIn (stub)
├── ui.py             # shared operator-UI chrome: stylesheet, nav, layout
├── draft_html.py     # pure render of the /review queue + a draft detail page
├── dashboard_html.py # pure render of / (dashboard), /publish, /status
├── web.py            # FastAPI operator UI + JSON API + scan/refresh schedulers
└── __init__.py
```

Flow: `load_config` merges `config.yaml` and `credentials.yaml` over `DEFAULTS`
→ token resolves (`--token` > `SOCIAL_BOT_TOKEN` > `credentials.yaml`) → `GraphApi` talks to
`https://graph.facebook.com/<version>/<path>` → `feed` renders through
`feed.py`; `post` sends `message` (+ optional `link`) to `/{page}/feed`, or
`url` + `caption` to `/{page}/photos` when `--photo` is given.

`serve` flow: the FastAPI `lifespan` starts two asyncio schedulers; the refresh
loop calls `refresh.py:refresh_feed` (via `asyncio.to_thread`) at the
`--refresh-at` slots and on `POST /refresh`, writing
`data/feed/latest.{json,html}`, while the scan loop calls
`draft_pipeline.py:scan_sources` at the `--scan-at` slots. The operator UI is
four HTML pages sharing the `ui.py` nav: `/` (dashboard — controls, counts,
scheduler state, and the cached feed rendered live from `latest.json`), `/review`
(the queue + a detail page), `/publish` (the audit log), and `/status`.
web.py's time helpers are pure so tests need no fastapi/uvicorn.

Content pipeline flow: `scan_sources` fetches each `sources[]` feed
(`source_api.py`), parses it (`source.py`), and queues unseen items as
`EXTRACTED` drafts under `data/review/` (dedupe via `seen.json`); it runs on the
`--scan-at` schedule, on `POST /scan`, or via `blog scan`. When
`image_gen.enabled` is on, a rewrite landing (`POST /api/drafts/{id}/rewrite`)
makes `serve` fill that draft's image **in the background** (only if it has
none, so a re-submitted rewrite never regenerates); `blog image` regenerates on
demand for drafts already queued. An external
rewriter — Command Code, applying the Atento DNA (`docs/atento-dna.md`, wired
via `publish.dna_file`) — reads `GET /api/drafts` and
POSTs the caption back to `/api/drafts/{id}/rewrite` (`AI_DRAFT`). A human
approves on `/review/{id}`, which calls `publish_draft` and posts through a
`publishers.py` adapter. **The scheduler only refreshes and scans; publishing
happens solely on that explicit human approval — `serve` never auto-posts.**

## Hard-won facts

- **Graph API v26.0** is current as of Sept 2026 (introduced 2026-07-29).
  Meta supports the current version plus two previous majors; `graph.api_version`
  is configurable and pinned in `config.yaml`.
- The token is the whole auth story. It is **never in code or committed
  config**: passed via `SOCIAL_BOT_TOKEN`, `--token`, or `credentials.yaml`
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
- urllib, not `requests`: keeps the dependency footprint at PyYAML only, like
  the parent bots. Photo posts are **by URL** (`POST /{page}/photos` with `url`
  + `caption`, Graph fetches the image) precisely to avoid multipart. Uploading
  a local file would need multipart and may justify adding `requests` —
  revisit then, not before.
- Pollinations has **two image endpoints and they are not interchangeable**.
  `https://gen.pollinations.ai/image` (the default, `image_gen.base_url`) is the
  live gateway: real model choice, no watermark, but it **requires** a valid
  `image_gen.api_key` (401 otherwise) and the model names are
  provider-qualified (list them from `GET gen.pollinations.ai/models`). The
  legacy `https://image.pollinations.ai/prompt` needs no key but silently
  serves the older `sana` model (it ignores `model=`) and watermarks every
  image (`x-auth-status: unauthenticated`). Don't "simplify" to the legacy URL.
- The image model matters more than the prompt. `flux.1-schnell` barely obeys
  negatives — it renders literal buildings and stray lettering and ignores "no
  text". **`openai/gpt-image-1-mini` is the default** because it follows the
  style brief's negatives, and it is cheap. Verify a new model on a real draft
  before switching.
- **Image variety comes from `image_prompt`, not from the style brief.** The
  rewriter supplies a concrete English visual concept per post (rewrite
  contract §9.1). Illustrating a raw `title`/excerpt — an abstraction, and in
  Vietnamese — made every image look the same: the model cannot picture
  "Consumer Group", so it fell back to whatever composition the style brief
  suggested, every time. Never build the subject from the title; ask for it.
  Two related traps: translating the title to English alone is *worse* (it
  yields literal cloud-and-arrow flowcharts and people), and the style brief
  must not prescribe one composition.
- Every post is a photo post, so images are generated **after** the rewrite,
  never during scan — at scan time there is no `image_prompt` yet, which is the
  whole problem. `serve` fills a draft's image in the background as its rewrite
  arrives (only if missing); `blog image` is the on-demand catch-up.
- **An existing image is never replaced by default** — only drafts with no image
  get one, so a source post's own cover survives the rewrite job, `blog image`,
  and the API. Replacement is opt-in: `blog image --overwrite`,
  `?overwrite=true` on `POST /api/drafts/{id}/image`, the **Regenerate image**
  button on `/review/{id}`, or `image_gen.overwrite: true`.
- The API key must ride in the `Authorization` header, **never the URL**: the
  URL is stored on the draft, shown in page HTML, and sent to Graph as the
  photo `url`. The old `?token=` form leaked it into all three.
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
  the draft in the review queue, and are excluded from `publish.max_per_day`;
  only a *public* send calls `mark_posted`. Flip it to `false` to post publicly.
- API posts must stay within Facebook platform policies (no engagement bait,
  spam, inauthentic behavior). The content pipeline keeps its human review
  step: `scan_sources` only queues drafts, the AI rewrite only suggests a
  caption, and nothing publishes except an explicit human approval on
  `/review/{id}` (`publish_draft`). Never wire an approval into the scheduler.
- Source scanning fetches only the configured official feeds (sitemap / RSS) —
  no HTML scraping. Stay within each site's robots.txt and rate limits; fetch
  politely (timeouts + bounded retries).
- Image generation is an **enhancement, never a gate**: a failure is recorded
  in the scan/summary `errors` and the draft keeps its existing image. It must
  never block queueing or publishing, and it never publishes on its own.
- Exit codes: 0 success, 1 Graph/network failure, 2 usage/config error.
  `_page_id` and token resolution raise `ValueError` (→ 2) and are caught
  inside each `_cmd_*`, never allowed to traceback.

## Testing

```
.venv/bin/python -m pytest     # pure logic, no network
```

Tests cover config defaults/deep-merge/validation, token precedence,
Graph URL/error-payload handling, feed timestamp parsing, markdown + HTML
rendering, the refresh cache writer, source parsing (sitemap/RSS/Atom/JSON-LD
index), the draft model/persistence, the publisher adapters, the
scan/rewrite/publish pipeline (stubbed clients), image prompt building and
URL construction (`image_gen.py`, stubbed `urlopen`), the operator pages
(`ui.py` / `draft_html.py` / `dashboard_html.py`), and serve's pure scheduling
helpers (no fastapi import needed). Live calls are manual: `whoami` first, then
`feed --limit 3`, then `blog scan` (queues drafts, no token needed), then
`blog image --limit 1` to verify the provider/key, then `post --dry-run` before
the first real post.
