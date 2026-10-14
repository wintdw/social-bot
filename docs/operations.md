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
.venv/bin/.venv/bin/social-bot blog publish --dry-run       # post the approved queue (needs a token)
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

Ordering changes only *which* approved draft goes next. It never approves or
posts, and `publish.post_per_slot` / `publish.interval_days` still
gate every send.

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
```

`/live` answers as long as the process is up; `/ready` returns **503** when the
instance should take no traffic — while it is draining on shutdown, if a
scheduler task has died, or if a state directory is not writable. Point a
load-balancer/healthcheck at `/live` for restarts and `/ready` for routing.

## Lifecycle

On `SIGTERM` (e.g. `docker compose down`, a redeploy), `serve` marks itself
not-ready, stops accepting new publishes/scans/refreshes (503), waits up to 30s
for an in-flight publish to finish, then cancels the refresh/scan/posting/token
loops. Keep uvicorn's `--timeout-graceful-shutdown`
above that window so a slow post is not killed mid-flight.

## Data layout

| Path | What |
|---|---|
| `data/feed/latest.{json,html}` | Cached page feed (written by `refresh`/`serve`). |
| `data/review/queue.json` | The review queue. |
| `data/review/seen.json` | Dedupe ledger (`source:slug`). |
| `data/publish/published.jsonl` | Publish audit log. |
| `data/state.json` | Last refresh/scan run, whether posting is paused, and each destination's last-run posting slot (so a restart neither resumes a pause nor re-fires a slot that already ran). |

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
| Approved drafts never post on schedule | The poster is **paused** (dashboard **Pause posting** / `POST /publish/pause`; the **Post schedule** row reads `paused` and **Next post** shows `—`), `publish.post_at` is empty (timed posting off), `publish.enabled: false`, or `publish.interval_days` hasn't elapsed (a `2` means it skips until two days after the last *scheduled* public post — a manual **Post now** / `/queue` send is never counted, so it can't hold the queue back). The dashboard **Next post** card and the `/status` **Post schedule** line both name the draft (`publish.next_draft`; `publish.interval_remaining` counts the days still to wait), and the **Next post** card's time is the first slot that can actually send — so `in 1 day(s)` means today's wake will be skipped, not that it posts later today. |
| Draft approved by mistake, or queued too early | **Unapprove** on `/review/{id}` (`POST /review/{id}/unapprove`) returns it to `ai_draft`: it leaves the post queue (the poster skips it) but stays on `/review` for another pass, with no caption change. It is refused once a destination has a *public* post (a send cannot be undone); a private test send still un-approves. `reject` is the other exit but throws the draft away. |
| Hashtags missing from a post | Ensure the image includes the `Draft.post_text` fix (rebuild). Hashtags are appended to the caption at publish time. |
| Draft stuck `extracted` | No caption yet. Write it in Claude, paste it on `/review/{id}`, and save: saving moves the draft to `ai_draft`, ready to approve. |
| Draft has no image | Expected unless the source post published a cover: use the source cover as-is, or draw an HTML5 plate in `data/review/plates/` and screenshot it to a PNG. |
| A plate replaced a post's own cover | **Restore source image** on `/review/{id}` puts the source post's picture back (the caption is untouched); the source image is kept on the draft from scan time, and read back from the source page if the draft predates that. Only `blog diagram --overwrite` replaces a cover, deliberately. |

## Security

The web endpoints are **unauthenticated**. Anyone who can reach `/review` can
read drafts, and anyone who can `POST /review/{id}/publish` can post to the
Page. Before exposing `serve` publicly, put it behind auth (reverse proxy, VPN,
or a shared-secret middleware you add in `web.py`).

## Guardrails recap

- The scan/refresh loops only refresh and scan, and the posting loop only posts.
  Posting only happens for drafts a human approved: the posting loop posts
  `approved` drafts at the `publish.post_at` slots (or on demand via **Post
  approved now** / `blog publish`). It never approves anything.
  `publish.post_at: []` disables timed posting.
- `publish.enabled: false` disables publishing; `publish.interval_days`
  enforces a minimum gap between *scheduled* public posts (`1` = at most one per
  day). A manual send — a draft's **Post now**, a `/queue` platform button — is
  both exempt from the gate and left out of the count, so a person can always
  post and their post never holds the poster back.
- Posting can be **paused** without changing config: **Pause posting** on the
  dashboard / `POST /publish/pause` (resume with `POST /publish/resume`). It stops
  only the scheduler — an explicit **Post approved now** / `blog publish` still
  sends, and the pause persists across restarts (it lives in `data/state.json`).
- `publish.private: true` sends every post **unpublished** (page admins only).
  It is a real Graph write, not a dry run — but it never goes public, it leaves
  the draft in the queue, and it doesn't count toward `interval_days`. This is
  the safe way to exercise the publish path end to end.
- A **manual** send (a draft's **Post now**, a `/queue` platform button) is the
  other kind outside `interval_days`: audited as `"manual": true`, never refused
  by the gate and never counted toward it. Unlike a private send it does consume
  the destination. The drain paths (`Post approved now` / `blog publish`) stay
  paced — they are the machine the interval exists for.
- Keep `--dry-run` working on every publish path.
