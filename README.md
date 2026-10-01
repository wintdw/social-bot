# social-bot

Graph API client for a **Facebook Page**: fetch the page feed and post status
or link updates. No browser, no login automation — everything goes through
Meta's official Graph API with a Page access token. The skeleton (cli/config/
tests/Docker layout) is forked from the voz-bot/otofun-bot family of
per-platform bots; the engine here is plain HTTPS + JSON via the standard
library.

Deeper docs live in [`docs/`](docs/README.md): the module map ("where to work"),
the [content pipeline](docs/content-pipeline.md), [operations](docs/operations.md),
and [development](docs/development.md).

## What works today

| Command | What it does |
|---|---|
| `social-bot whoami` | Check the token, list the pages it can manage (need `pages_show_list`). |
| `social-bot feed` | Fetch the page's own feed, newest first, as markdown. |
| `social-bot feed --json` | Same data as raw Graph API JSON. |
| `social-bot feed --limit 20` | Change how many posts are shown. |
| `social-bot post --message "..."` | Post a status update to the page. |
| `social-bot post --message "..." --link https://...` | Post with a link attachment. |
| `social-bot post --photo https://.../pic.jpg` | Publish a photo from a public image URL. |
| `social-bot post --message "..." --photo https://.../pic.jpg` | Photo post, `--message` becomes its caption. |
| `social-bot post --dry-run` | Print exactly what would be sent, send nothing. |
| `social-bot refresh` | Fetch the feed and cache it as HTML/JSON under `feed.dir`. |
| `social-bot blog scan` | Scan the configured source feeds and queue new drafts for review (never posts). |
| `social-bot blog publish` | Post the human-approved queue now (add `--dry-run` to preview). |
| `social-bot blog queue` | Show the approved post queue in the order it will post. |
| `social-bot blog move <id> up\|down\|top\|bottom` | Move one approved draft in the post queue. |
| `social-bot serve` | Long-lived operator UI (dashboard/review/published/status) + scheduled refresh/scan/posting (needs the `server` extra). |

Every command takes `--page-id` (overrides config) and `--token` (overrides
the environment). `serve` refreshes the cached feed and scans source feeds on a
schedule, and posts approved drafts at the `publish.post_at` slots. It **never
approves or rewrites anything**: a draft must first be approved on `/review`
("Approve & schedule", or "Post now" to send immediately). `publish.post_at: []`
disables timed posting, leaving approval as the only publish path, and
`publish.interval_days` enforces a minimum gap between public posts (e.g. `2` =
one post every other day).

Photos are published **by URL** (`POST /{page}/photos` with `url` + `caption`):
Graph fetches the image itself, so no file upload and no extra HTTP
dependency. The URL must be publicly reachable by Meta, the image should be a
JPEG/PNG, and `pages_manage_posts` covers it. Local files are not uploaded yet
— that would need a multipart body. `--link` and `--photo` are mutually
exclusive.

## Setup

1. **Create a Meta app** at developers.facebook.com (type: Business) and add
   the product *Facebook Login for Business* or open the Graph API Explorer.
2. **Get a Page access token** with these permissions:
   `pages_read_engagement`, `pages_manage_posts`, `pages_show_list`.
   The Graph API Explorer → *Get Page Access Token* is the quickest route;
   the token is scoped to a page you administer.
3. Put the token in `credentials.yaml` — it is git-ignored, so the secret never
   lands in the repo. Copy the template and fill it in:
   ```sh
   cp credentials.example.yaml credentials.yaml
   # edit credentials.yaml:  destinations:
   #                           facebook:
   #                             token: "EAA..."
   ```
   Alternatively export `SOCIAL_BOT_TOKEN='EAA...'` (or the destination-specific
   `SOCIAL_BOT_FACEBOOK_TOKEN`) — the environment overrides the file (handy for
   CI and Docker).
4. Find your page id, then put it in `config.yaml`:
   ```sh
   .venv/bin/social-bot whoami        # lists "Name (id 123456...) "
   .venv/bin/social-bot destinations  # which platforms are routed/configured
   # config.yaml:  destinations.facebook.account_id: "123456"
   ```

Local run:

```
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"          # add [server] for `serve`
.venv/bin/social-bot whoami                       # token + page list
.venv/bin/social-bot feed --limit 5               # read
.venv/bin/social-bot post --dry-run --message "Hello world"
.venv/bin/social-bot post --message "Hello world" # write
.venv/bin/social-bot post --dry-run --message "Caption" --photo https://example.com/pic.jpg
.venv/bin/social-bot post --message "Caption" --photo https://example.com/pic.jpg
.venv/bin/social-bot serve --port 8083 --boot-refresh   # dashboard + schedule
```

## Configuration (config.yaml)

```yaml
destinations:
  facebook:
    base_url: https://graph.facebook.com # override for tests/proxies
    api_version: v26.0                   # pin the version; bump deliberately
    timeout_seconds: 30.0
    account_id: ""                       # the Page id, set from `whoami`
  linkedin:                              # stubbed until the adapter is wired
    base_url: https://api.linkedin.com
    api_version: ""                      # LinkedIn-Version header
    author_urn: ""                       # urn:li:organization:<id>
feed:
  limit: 10                              # default posts shown by `feed`
  dir: data/feed                         # cache written by `refresh`, served by `serve`
```

`destinations` holds one connection block per platform; `publish.destinations`
selects which of them a new draft is routed to. `social-bot destinations` prints
each one's routed/configured state.

The tokens are secrets and live in `credentials.yaml` (git-ignored), never in
`config.yaml`:

```yaml
destinations:
  facebook:
    token: "EAA..."                      # or export SOCIAL_BOT_TOKEN
  linkedin:
    token: ""                            # unused until LinkedIn is implemented
```

Resolution order, per destination: `--token` > `SOCIAL_BOT_<NAME>_TOKEN` >
`SOCIAL_BOT_TOKEN` (global fallback) > `credentials.yaml`. A `credentials.yaml`
is read from next to whichever `config.yaml` is in use, so
`--config /path/to/config.yaml` looks for `/path/to/credentials.yaml`.

Meta supports a rolling window of Graph API versions (current and two
previous majors), so `destinations.facebook.api_version` should be bumped
consciously rather than left to rot.

## Run with Docker (service mode)

The default deployment is a long-lived container: one operator UI on `:8083`,
plus built-in refresh/scan **and posting** schedules — **no host cron**. The
scan loop only queues drafts; the posting loop only posts drafts a human
approved on `/review` (it never approves). `publish.post_at: []` disables timed
posting.

```sh
docker compose up -d --build          # build + start
open http://localhost:8083/           # dashboard: controls + feed + counts
curl localhost:8083/health            # state as JSON
curl -X POST localhost:8083/refresh   # refresh now
open http://localhost:8083/review     # review + approve drafts
docker compose logs -f                # follow refresh/scan runs
```

| Page | What it shows |
|---|---|
| `GET /` | **Dashboard** — refresh/scan controls, open-draft and published counts, scheduler state, the next post (time + which draft), and the cached feed. |
| `GET /review` | **Review queue** — open drafts, newest first (with a **Scan sources now** button). Paged (`?page=`, `?per_page=`, default 20). |
| `GET /review/{id}` | One draft: editable caption + hashtags + English image prompt, Save / Post now / Reject, Approve & schedule when `publish.post_at` is set (and **Unapprove** on a draft already approved), a **Rewrite with Command Code** button when `rewrite.enabled` is set, and **Regenerate image prompt** (a fresh prompt from the agent, which you then render with **Regenerate image** — also on an approved draft), the DNA brief. |
| `GET /queue` | **Post queue** — the approved drafts in the order they will post, the one going out next marked, with drag / Top-Up-Down reorder controls and a **Post approved now** button. |
| `GET /publish` | **Published** — the audit log (public and private sends, with permalinks). |
| `GET /status` | **Status** — sources, drafts by state, publish settings (min interval, days remaining, next up), and scheduler runs. |
| `GET /health` | JSON: busy, last refresh/scan result, schedules, next runs, open drafts, lifecycle. |
| `GET /live` | Liveness probe — always `{"status": "alive"}` while the process runs. |
| `GET /ready` | Readiness probe — 200 when serving, 503 while draining or unhealthy. |
| `POST /refresh` | `{"started": true}`, or `409` if a refresh is already running. |
| `POST /scan` | Scan the sources now; new drafts appear at `/review`. |
| `POST /publish/run` | Post the approved queue now, without waiting for a slot. |
| `POST /review/{id}/save` | Save the compose edits (caption, hashtags, image prompt); never posts. |
| `POST /review/{id}/publish` | Publish on approval (form field `dry_run=1` to preview only; `approve=1` queues the draft for the next slot instead). |
| `POST /review/{id}/unapprove` | Pull an approved draft back out of the queue (back to `ai_draft`); never posts. |
| `POST /review/{id}/reject` | Mark the draft rejected. |
| `POST /review/{id}/restore-image` | Put the source post's own image back, replacing a generated one. |
| `POST /review/{id}/request-rewrite` | Mark the draft for the host-side rewriter worker (needs `rewrite.enabled`); never rewrites itself. |
| `POST /review/{id}/request-image-prompt` | Mark the draft for a *prompt-only* rewrite (a fresh image prompt, then a new image); never rewrites itself. Works on an approved draft too. |
| `POST /review/{id}/cancel-rewrite` | Drop a pending rewrite request (either kind). |

All five pages share the same top navigation, so you can move between them
without editing URLs; `/drafts` redirects to `/review` for old bookmarks.

Refreshes fire at `07:00` and `19:00`, the source scan at `06:00`, and approved
drafts post in the `19:30-21:00` window (`publish.post_at` in `config.yaml`; use
`--publish-at` on `serve` to override) — all **container-local** (compose sets
`TZ=Asia/Ho_Chi_Minh`). A slot may be a fixed `HH:MM` or a window `HH:MM-HH:MM`:
inside a window the scheduler fires once that day at a random time (stable per
day, so restarts don't double-post). `publish.interval_days: 2` then skips the
following day's slot, pacing the page to one post every two days. Edit
`command:` in `docker-compose.yml` to change the
refresh/scan times, or add `--boot-refresh`/`--boot-scan` to populate on the
first deploy. Runs are single-flight (scheduled and manual runs never overlap)
and each slot fires at most once. There is no `--boot-publish`, so nothing posts
at startup.

State lives on the host: `./data` (the feed cache) survives rebuilds, and
`./config.yaml` + `./credentials.yaml` are bind-mounted read-only. The image
runs as **uid/gid 1000** by default (matching a typical host user), so the
bind-mounted `./data` needs no chown. Different host uid? Rebuild with
`--build-arg UID=$(id -u) --build-arg GID=$(id -g)` and
`sudo chown -R $(id -u):$(id -g) data`.

## Run with Docker (one-shot CLI)

The same image runs any CLI command with `docker compose run`:

```sh
docker compose run --rm social-bot whoami
docker compose run --rm social-bot feed --limit 5
docker compose run --rm social-bot post --dry-run --message "Hi!"
docker compose run --rm social-bot post --message "Hi!"     # real, public post
docker compose run --rm social-bot post --photo https://example.com/pic.jpg
```

`config.yaml` and `credentials.yaml` are mounted read-only, so the token never
enters the image and `destinations.facebook.account_id` edits need no rebuild.
`SOCIAL_BOT_TOKEN` overrides the mounted credentials file when set.

## Content pipeline (source feeds → human-approved posts)

Beyond the page feed, `serve` hosts a draft review workflow. Nothing is ever
auto-posted: the AI rewrite is a suggestion, and only a human approval publishes
— immediately ("Post now") or via the posting schedule ("Approve & schedule").
An approval stays reversible (**Unapprove** on `/review/{id}`) until the post
actually goes out, so a draft queued by mistake can be pulled back.

```
source feeds ── blog scan ──▶ drafts (extracted)
                                  │  GET  /api/drafts   ──▶ you run Command Code
                                  │  POST /api/drafts/{id}/rewrite  (Atento DNA)
                                  │  — or click "Rewrite with Command Code": the host
                                  │    worker (scripts/rewrite_worker.py) polls
                                  │    GET /api/rewrite-queue and posts the rewrite back
                                   ▼  drafts (ai_draft)
                            GET /review/{id}  ── edit caption ──▶ Post now  ──▶ Facebook Page
                                   │                                (destinations in config)
                                   └─ Approve & schedule ──▶ approved ──post_at slot / blog publish──▶
```

Scan for new items (also runs on the `serve` schedule):

```sh
.venv/bin/social-bot blog scan              # queue new drafts from every source
.venv/bin/social-bot blog scan --json       # machine-readable summary
.venv/bin/social-bot blog scan --source atento-blog --limit 5
```

Sources live under `sources:` in `config.yaml`; each is `type: index | sitemap |
rss` (`index` reads a listing page's JSON-LD `ItemList` — Atento's blog publishes
no feed and its sitemap omits posts). New items are enriched from their post
page (title/excerpt/featured image) before landing in the queue, and that image
is kept on the draft as the post's own: a generated image only ever fills a
draft that has none, and **Restore source image** on `/review/{id}` puts the
original back (re-reading the source page if it was never kept).

Then, with `serve` running, hand the drafts to your rewriter and approve:

```sh
curl localhost:8083/api/drafts                          # drafts + your DNA text
curl -X POST localhost:8083/api/drafts/post-one/rewrite \
     -H 'content-type: application/json' \
     -d '{"caption":"...","hashtags":["#Atento"],"image_prompt":"a lone tree by a river","image_style":"editorial"}'
open http://localhost:8083/review                       # edit + Post now / Approve & schedule
```

Or let a host-side worker do it: click **Rewrite with Command Code** on
`/review/{id}` (needs `rewrite.enabled: true`), and run
`.venv/bin/python scripts/rewrite_worker.py` beside the service. The app only
*marks* the draft; the worker polls `GET /api/rewrite-queue`, runs the Command
Code CLI headlessly on the host, and POSTs the result back to
`/api/drafts/{id}/rewrite` — the app never runs the agent itself (the container
has no Node). See [operations](docs/operations.md) for running it as a service.

**In your own voice.** On top of the brand DNA and the voice menu, the worker can
also hand the agent *your* voice: the messages you actually wrote that are closest
to the draft, plus a learned `profile.md`, as a `MY VOICE` section — style only,
never a fact. Drop the corpus under `data/voice/` and install the extra
(`pip install -e ".[voice]"`); see what a topic retrieves with
`social-bot voice search "System Design là gì" --show`. With no corpus the worker
writes from the DNA and the voice menu exactly as before — voice is an
enhancement, never a gate. See
[content-pipeline §2c](docs/content-pipeline.md).

Same worker, second kind of request: **Regenerate image prompt** on
`/review/{id}` asks for a new *image prompt* only — the caption is left exactly as
approved, and the image style on the page is the one the agent writes for — and
renders nothing: the prompt lands on the page to be read (or edited), and
**Regenerate image** is the separate move that renders it. The worker
tells the two apart from the request's own kind (`Draft.rewrite_mode`) and posts a
prompt-only result to `/api/drafts/{id}/image-prompt`.

State lives under `data/review/`: `queue.json` (the queue) and `seen.json`
(dedupe); the publish audit is `data/publish/published.jsonl`. Set
`publish.enabled: false` for a global kill-switch, `publish.interval_days` for a
minimum gap between public posts (`1` = at most one per day), and
`publish.post_at` to the daily slots at which approved drafts post (a slot is
`HH:MM`, or a window `HH:MM-HH:MM`; `[]` disables timed posting). Drain the
approved queue on demand with `blog publish` or `POST /publish/run`.

The queue posts **oldest first** by default, but you can override the order on the
**Post queue** tab (`/queue`): its queue panel lists the approved drafts in
posting order, with the one that goes out next marked, and you reorder by
dragging a row or using its Top / Up / Down buttons. `blog queue` lists the order
and `blog move <id> <direction>` reorders from the CLI. Ordering only changes
*which* approved draft goes next — it never approves, rewrites, or posts.

**Private mode (testing).** `publish.private: true` makes every approval an
**unpublished** post — a real Graph call (`published=false`) that only page
admins can see. Use it to exercise the whole pipeline without going public:
private sends leave the draft in the queue (so you can post it publicly later)
and are recorded in `published.jsonl` with `"private": true`, and they don't count
toward `publish.interval_days`. Set it back to `false`
to post publicly. This is
not a dry run — it does create a post object, just an unpublished one.

| Endpoint | Returns |
|---|---|
| `GET /` | Dashboard: controls + counts + scheduler state + cached feed. |
| `GET /review` | HTML review list of open drafts (with a **Scan sources now** button). |
| `GET /review/{id}` | HTML detail with an editable caption, hashtags, image prompt, and image style + Approve/Reject (and Unapprove on an approved draft). |
| `GET /publish` | HTML audit log of what has been posted (public and private). |
| `GET /status` | HTML status page (sources, drafts by state, publish settings, runs). |
| `POST /scan` | Trigger a source scan now (`{"started": true}`, or `409` if one is running). |
| `POST /review/{id}/publish` | Publish on approval (form field `dry_run=1` to preview only). |
| `POST /review/{id}/unapprove` | Pull an approved draft back out of the queue (back to `ai_draft`); never posts. |
| `POST /review/{id}/reject` | Mark the draft rejected. |
| `POST /review/{id}/restore-image` | Put the source post's own image back, replacing a generated one. |
| `POST /review/{id}/request-rewrite` | Mark the draft for the host-side rewriter worker (`rewrite.enabled`); never rewrites itself. |
| `POST /review/{id}/request-image-prompt` | Mark the draft for a *prompt-only* rewrite; works on an approved draft too. |
| `POST /review/{id}/cancel-rewrite` | Drop a pending rewrite request (either kind). |
| `GET /api/drafts` | JSON: open drafts + your `publish.dna_file` contents (`dna`) + the voice menu `publish.voices` (`voices` = `{key: brief+samples}`, with `voice_choices`/`default_voice`) + the image treatment briefs (`image_style_briefs`) + `recent` captions and `recent_images` prompts, for the rewriter. Paged (`?limit=`, `?offset=`, default 100; body has `total`/`has_more`/`next_offset`). |
| `GET /api/rewrite-queue` | JSON: the drafts a human asked to rewrite + the brand context (DNA, voices, mastheads, image styles **and their briefs**, `recent` captions, `recent_images`), polled by the host-side rewriter worker. Each draft carries `rewrite_mode` (what the request asks for). |
| `GET /api/status` | JSON: full pipeline snapshot — sources, drafts by state, seen, published, schedules, lifecycle. `publish.next_draft` names the oldest approved draft the poster will send next (`publish.approved` counts them, `publish.interval_remaining` is the days still to wait). |
| `POST /api/drafts/{id}/rewrite` | JSON: store the rewrite (`caption`, `hashtags`, `cta`, `commentary`, `image_prompt`, `image_style`, `voice`). |
| `POST /api/drafts/{id}/image-prompt` | JSON: store a *prompt-only* rewrite (`image_prompt`, `image_style`) and re-render the image. The caption and the draft's state are untouched. |
| `POST /api/drafts/{id}/rewrite-error` | JSON: record the rewriter worker's failure and close the request (shown on `/review/{id}`). |

**Destinations** are pluggable: each platform is a package under
`src/social_bot/destinations/` and is registered in `destinations/registry.py`.
LinkedIn is wired as a destination adapter but not implemented — the
company-page path needs LinkedIn's Community Management API approval. Add a
token + `author_urn` and implement `LinkedInPublisher.publish` to switch it on;
no pipeline, CLI, or UI changes required.

## Tests

```
.venv/bin/python -m pytest      # pure logic, no network
.venv/bin/ruff check src tests scripts   # lint
.venv/bin/ruff format src tests scripts  # format in place
```

Ruff is the linter and formatter; its pinned config lives in `pyproject.toml`
(`[tool.ruff]`).

The tests never import fastapi/uvicorn — `serve`'s scheduling helpers are pure,
so `[dev]` is enough to run them.

## Notes / hard-won facts (verified Sept 2026)

- Graph API **v26.0** is the current version (introduced July 29, 2026).
  `GET /{page}/feed` and `POST /{page}/feed` behave as documented at
  developers.facebook.com.
- Feed timestamps come back as ISO-8601 with a colon-less offset (`+0000`);
  `feed.py` normalizes that before parsing.
- The feed's `type` field is deprecated on modern Graph versions (error `#12`);
  the client requests `status_type` instead.
- Status posts on pages are immediate. There is no editing/deleting command
  yet — deleted posts stay deleted, so use `--dry-run` first.
- Photo posts go through `POST /{page}/photos` with `url` + `caption`; Graph
  downloads the image, so the URL must be public and the token needs
  `pages_manage_posts`. The response returns the photo id in `id` and the feed
  post id in `post_id` — the permalink comes from `post_id`.
- Page tokens expire; when a call fails with an OAuth error, mint a fresh one
  in the Explorer and re-export it. `whoami` is the fastest sanity check.
- Unpublished ("private") posts use `published=false` on both `POST
  /{page}/feed` and `POST /{page}/photos`, and are visible to page admins
  only (verified: absent from the public `/feed` and `/photos` edges). The
  photos response for an unpublished upload returns only the photo `id` — no
  `post_id` — because no feed story is created, so there is no public
  permalink.
- Be a good citizen: Facebook platform policies apply to API posts too — no
  engagement bait, spam, or inauthentic content. Posting through the official
  API on pages you administer is the compliant way to run this bot.
# social-bot
