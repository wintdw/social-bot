# Operations

How to run, deploy, and debug social-bot.

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"          # CLI + tests
.venv/bin/pip install -e ".[server]"       # + fastapi/uvicorn/python-multipart for `serve`
cp credentials.example.yaml credentials.yaml   # put the Page token in it (git-ignored)
```

Token resolution, per destination: `--token` > `SOCIAL_BOT_<NAME>_TOKEN` >
`SOCIAL_BOT_TOKEN` (global fallback) > `credentials.yaml`
(`destinations.<name>.token`). It is never in code or committed config. Config
resolution: `config.yaml` at the project root (or `--config`), with a
`credentials.yaml` next to it merged last.

## Run locally

```sh
.venv/bin/social-bot whoami                       # token + manageable pages
.venv/bin/social-bot feed --limit 5
.venv/bin/social-bot blog scan                    # queue new drafts (no token needed)
.venv/bin/social-bot blog image --limit 1         # generate AI images for drafts (needs image_gen.api_key)
.venv/bin/social-bot blog publish --dry-run       # post the approved queue (needs a token)
.venv/bin/social-bot serve --port 8083            # dashboard + review UI + schedulers
.venv/bin/social-bot post --dry-run --message "…" # then drop --dry-run to post
```

`serve` flags: `--refresh-at HH:MM …` (feed refresh, default `07:00 19:00`),
`--scan-at HH:MM …` (source scan, default from `blog.scan_at`),
`--publish-at HH:MM …` (post approved drafts, default from `publish.post_at`; a
slot may also be a window `HH:MM-HH:MM`), `--boot-refresh`, `--boot-scan`. There
is deliberately no `--boot-publish`: posting never starts on boot. A posting run
that actually sent something also refreshes the feed cache, so the new post is
on the dashboard without waiting for the next `--refresh-at`.

Timed posting can be paused from the dashboard (**Pause posting**) or
`POST /publish/pause`, and resumed the same way. The pause is persisted, so a
redeploy keeps the hold; it only stops the *scheduler* — **Post approved now**
and `blog publish` still send.

## Order the post queue

The queue drains **oldest first** by default (`publish_scheduled`), but an
operator can override the order. In `serve`, open the **Post queue** tab
(`/queue`) and use its queue panel: it lists the approved drafts in posting order,
marks the one that goes out next (**Next to post**), and lets you reorder any row
by dragging it or using its **Top / Up / Down** buttons. **Reset order** clears
every manual position.

From the CLI:

```sh
social-bot blog queue                    # the approved queue, in posting order
social-bot blog move <draft-id> top      # up | down | top | bottom
social-bot blog queue --reset            # back to the default oldest-first order
```

Ordering changes only *which* approved draft goes next. It never approves,
rewrites, or posts, and `publish.post_per_slot` / `publish.interval_days` still
gate every send.

## Run the rewriter worker

The **Rewrite with Command Code** button on `/review/{id}` does not run an AI
itself — it marks the draft. A host-side worker does the rewrite with the Command
Code CLI and posts the result back (nothing here approves or posts). The same
worker also serves **Regenerate image prompt**, which asks only for a fresh image
prompt for the style you picked (the caption is left as approved) and renders
nothing — the prompt lands on the page for you to read (or edit), and **Regenerate
image** is what renders it. The request's own kind (`Draft.rewrite_mode`) tells the
two apart.

```sh
.venv/bin/python scripts/rewrite_worker.py             # poll forever
.venv/bin/python scripts/rewrite_worker.py --once       # drain the queue and exit
.venv/bin/python scripts/rewrite_worker.py --draft <id>
.venv/bin/python scripts/rewrite_worker.py --dry-run    # print the prompt, call nothing
```

It needs Command Code installed and logged in on the host (`cmd login`), and
`rewrite.enabled: true` in `config.yaml` for the button to appear.
`rewrite.api_base` defaults to `http://127.0.0.1:8083` (this app as the worker
sees it); from another machine point it at the deployed URL — `site.user` /
`site.password` in `credentials.yaml` are sent as HTTP basic auth.

**Keep it running — a request only waits otherwise.** `deploy/social-bot-rewriter.service`
is a ready `systemd --user` unit (the poll loop, restarts on failure):

```sh
mkdir -p ~/.config/systemd/user
ln -sf ~/social-bot/deploy/social-bot-rewriter.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now social-bot-rewriter
sudo loginctl enable-linger $USER        # survive logout/reboot (root, once)
journalctl --user -u social-bot-rewriter -f
```

Exit codes: 0 ok, 1 a run/HTTP failure, 2 usage/config error.

## Deploy (Docker)

```sh
docker compose up -d --build
```

`./data` is bind-mounted (state survives rebuilds); `./config.yaml` and
`./credentials.yaml` are mounted read-only. Host port **8083**. The container
command is `serve --refresh-at 07:00 19:00 --scan-at 06:00`; the posting slots
come from `publish.post_at` in the mounted `config.yaml`.

The image runs as **uid/gid 1000** (matching a typical host user), so the
bind-mounted `./data` needs no chown. Different host uid? Rebuild with
`--build-arg UID=$(id -u) --build-arg GID=$(id -g)` and
`sudo chown -R $(id -u):$(id -g) data`.

**After any code change, the running container is stale — rebuild:**
```sh
docker compose up -d --build
```
Check what's actually deployed: `curl -s http://<host>/api/status`.

## Endpoints

See [content-pipeline.md](content-pipeline.md) for the full table. The ones an
operator uses most:

```sh
curl -s  https://<host>/api/status          # full pipeline snapshot
curl -s  https://<host>/health              # liveness + last run info
curl -s  https://<host>/live                # liveness probe (never touches state)
curl -s -o /dev/null -w '%{http_code}\n' https://<host>/ready   # readiness probe
curl -X POST https://<host>/scan            # scan sources now
curl -X POST https://<host>/publish/run     # post the approved queue now (even while paused)
curl -X POST https://<host>/publish/pause   # pause the posting scheduler (persisted)
curl -X POST https://<host>/publish/resume  # resume it
curl -s  https://<host>/api/drafts          # open drafts (paged; ?limit=&offset=)
curl -s  https://<host>/api/rewrite-queue   # drafts a human asked the worker to rewrite
```

`/live` answers as long as the process is up; `/ready` returns **503** when the
instance should take no traffic — while it is draining on shutdown, if a
scheduler task has died, or if a state directory is not writable. Point a
load-balancer/healthcheck at `/live` for restarts and `/ready` for routing.

## Lifecycle

On `SIGTERM` (e.g. `docker compose down`, a redeploy), `serve` marks itself
not-ready, stops accepting new publishes/scans/refreshes (503), waits up to 30s
for an in-flight publish to finish, then cancels the refresh/scan/posting/token
loops and any background image jobs. Keep uvicorn's `--timeout-graceful-shutdown`
above that window so a slow post is not killed mid-flight.

## Data layout

| Path | What |
|---|---|
| `data/feed/latest.{json,html}` | Cached page feed (written by `refresh`/`serve`). |
| `data/review/queue.json` | The review queue. |
| `data/review/seen.json` | Dedupe ledger (`source:slug`). |
| `data/publish/published.jsonl` | Publish audit log. |
| `data/state.json` | Last refresh/scan run and whether posting is paused (so the dashboard and the pause survive a restart). |

Ownership: the container writes as **uid 1000** by default — the same as a
typical host user — so `./data` needs no chown and the CLI run as your host user
can share it. If you rebuilt with a different `UID`, keep `./data` owned by that
same id.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `PermissionError: …/queue.json.tmp` | `./data` not writable by the process. Container: `sudo chown -R 1000:1000 data` (or your build-arg `UID:GID`). The CLI prints this hint instead of a traceback. |
| `blog scan` adds 0 items | Dedupe working — those slugs are in `seen.json`. Normal. To re-import: `sudo rm data/review/seen.json data/review/queue.json` (loses rewrites/approvals too). |
| Source errors (`scan_ok: false`) | The host is flaky (504s). `source_api` retries; re-run `/scan`. Use `curl …/scan` or the **Scan now** button. |
| `/api/status` 404 | Old image — rebuild (`docker compose up -d --build`). |
| OAuth error on post | The Page token expired — check `/status` (validity + expiry), mint a fresh one, update `credentials.yaml`, `whoami` to verify. |
| Approved but nothing shows on the Page | First, the posting schedule: an `approved` draft waits for the next `publish.post_at` slot. Drain it now with **Post approved now** / `POST /publish/run` / `blog publish`, or check `publish.private: true` — a private post is unpublished (page admins only) and stays in the queue. Set `private: false` to post publicly. |
| Approved drafts never post on schedule | The poster is **paused** (dashboard **Pause posting** / `POST /publish/pause`; the **Post schedule** row reads `paused` and **Next post** shows `—`), `publish.post_at` is empty (timed posting off), `publish.enabled: false`, or `publish.interval_days` hasn't elapsed (a `2` means it skips until two days after the last public post). The dashboard **Next post** card and the `/status` **Post schedule** line both name the draft (`publish.next_draft`; `publish.interval_remaining` counts the days still to wait), and the **Next post** card's time is the first slot that can actually send — so `in 1 day(s)` means today's wake will be skipped, not that it posts later today. |
| Draft approved by mistake, or queued too early | **Unapprove** on `/review/{id}` (`POST /review/{id}/unapprove`) returns it to `ai_draft`: it leaves the post queue (the poster skips it) but stays on `/review` for another pass, with no caption change. It is refused once a destination has a *public* post (a send cannot be undone); a private test send still un-approves. `reject` is the other exit but throws the draft away. |
| Hashtags missing from a post | Ensure the image includes the `Draft.post_text` fix (rebuild). Hashtags are appended to the caption at publish time. |
| Draft stuck `extracted` | No rewrite yet — the external agent must `POST /api/drafts/{id}/rewrite`, or the rewriter worker (next row) must pick up a requested rewrite. |
| **Rewrite with Command Code** does nothing | The host-side worker isn't running (or `rewrite.enabled` is off). The button only *marks* the draft; start `scripts/rewrite_worker.py`. `GET /api/status` → `rewrite.requested` lists what is waiting, and `/review/{id}` shows any worker error (a request never runs itself; a stuck one can be cancelled). |
| **Regenerate image prompt** does nothing | Same worker, same rules — it is a second kind of request on the same queue (`Draft.rewrite_mode: image`). One request per draft: asking for either cancels the other kind. |
| The new prompt landed but the picture did not change | By design: the prompt-only request never renders (a picture must not land from a prompt nobody has read). Press **Regenerate image** on `/review/{id}` to render it. |
| **Image style** changed but nothing used it | The picker governs both image buttons: **Regenerate image** renders that treatment, **Regenerate image prompt** has the agent write a subject for it. Both submit the compose form, so the pick is saved with the action — no separate **Save** needed. |
| Every image looks the same | The prompt, not the treatment, is usually the cause. Check `recent_images` in the worker's payload (`GET /api/rewrite-queue`) — the agent is told not to repeat those subjects, so a stale or empty list lets it loop. **Regenerate image prompt** on `/review/{id}` replaces one draft's prompt without touching its approved caption or the style you picked; render it with **Regenerate image**. |
| Draft has no image after a rewrite | `serve` generates it in the background; a restart (or a provider 5xx) can leave it empty. Check the **Image jobs** section on `/status` (or the dashboard, or `GET /api/status` → `images`), then run `social-bot blog image` or the **Generate image** button on `/review/{id}`. |
| Image generation fails (`HTTP 401`) | `image_gen.api_key` missing/invalid. The default `gen.pollinations.ai/image` endpoint requires a key (see `credentials.example.yaml`). |
| A generated image took a post's own cover | **Restore source image** on `/review/{id}` puts the source post's picture back (the caption is untouched); the source image is kept on the draft from scan time, and read back from the source page if the draft predates that. Generation never replaces a cover on its own — only the **Regenerate image** button / `--overwrite` does, deliberately. **Regenerate image prompt** is not a replacement at all: it changes only the prompt, and the picture is replaced when you go on to press **Regenerate image**. |

## Security

The web endpoints are **unauthenticated**. Anyone who can reach `/review` can
read drafts, and anyone who can `POST /review/{id}/publish` can post to the
Page. Before exposing `serve` publicly, put it behind auth (reverse proxy, VPN,
or a shared-secret middleware you add in `web.py`).

## Guardrails recap

- The scan/refresh loops only refresh and scan, and the posting loop only posts.
  Posting only happens for drafts a human approved: the posting loop posts
  `approved` drafts at the `publish.post_at` slots (or on demand via **Post
  approved now** / `blog publish`). It never approves or rewrites anything.
  `publish.post_at: []` disables timed posting.
- `publish.enabled: false` disables publishing; `publish.interval_days`
  enforces a minimum gap between public posts (`1` = at most one per day).
- The rewriter worker only *rewrites* (`POST /api/drafts/{id}/rewrite`); it never
  approves or posts to the Page. `rewrite.enabled` only controls whether the
  button appears; the human gate is unchanged.
- Posting can be **paused** without changing config: **Pause posting** on the
  dashboard / `POST /publish/pause` (resume with `POST /publish/resume`). It stops
  only the scheduler — an explicit **Post approved now** / `blog publish` still
  sends, and the pause persists across restarts (it lives in `data/state.json`).
- `publish.private: true` sends every post **unpublished** (page admins only).
  It is a real Graph write, not a dry run — but it never goes public, it leaves
  the draft in the queue, and it doesn't count toward `interval_days`. This is
  the safe way to exercise the publish path end to end.
- Keep `--dry-run` working on every publish path.
