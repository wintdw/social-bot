# Operations

How to run, deploy, and debug social-bot.

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"          # CLI + tests
.venv/bin/pip install -e ".[server]"       # + fastapi/uvicorn/python-multipart for `serve`
cp credentials.example.yaml credentials.yaml   # put the Page token in it (git-ignored)
```

Token resolution: `--token` > `SOCIAL_BOT_TOKEN` > `credentials.yaml`
(`graph.token`). It is never in code or committed config. Config resolution:
`config.yaml` at the project root (or `--config`), with a `credentials.yaml`
next to it merged last.

## Run locally

```sh
.venv/bin/social-bot whoami                       # token + manageable pages
.venv/bin/social-bot feed --limit 5
.venv/bin/social-bot blog scan                    # queue new drafts (no token needed)
.venv/bin/social-bot serve --port 8083            # dashboard + review UI + schedulers
.venv/bin/social-bot post --dry-run --message "…" # then drop --dry-run to post
```

`serve` flags: `--refresh-at HH:MM …` (feed refresh, default `07:00 19:00`),
`--scan-at HH:MM …` (source scan, default from `blog.scan_at`), `--boot-refresh`,
`--boot-scan`.

## Deploy (Docker)

```sh
docker compose up -d --build
```

`./data` is bind-mounted (state survives rebuilds); `./config.yaml` and
`./credentials.yaml` are mounted read-only. Host port **8083**. The container
command is `serve --refresh-at 07:00 19:00 --scan-at 06:00`.

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
curl -s  https://<host>/health              # liveness
curl -X POST https://<host>/scan            # scan sources now
curl -s  https://<host>/api/drafts          # open drafts (for the rewriter)
```

## Data layout

| Path | What |
|---|---|
| `data/feed/latest.{json,html}` | Cached page feed (written by `refresh`/`serve`). |
| `data/review/queue.json` | The review queue. |
| `data/review/seen.json` | Dedupe ledger (`source:slug`). |
| `data/publish/published.jsonl` | Publish audit log. |

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
| OAuth error on post | The Page token expired — mint a fresh one, update `credentials.yaml`, `whoami` to verify. |
| Approved but nothing shows on the Page | `publish.private: true` — the post is unpublished (page admins only). Set it to `false` to post publicly; a private send also leaves the draft in the queue, so re-approving later posts it publicly. |
| Hashtags missing from a post | Ensure the image includes the `Draft.post_text` fix (rebuild). Hashtags are appended to the caption at publish time. |
| Draft stuck `extracted` | No rewrite yet — the external agent must `POST /api/drafts/{id}/rewrite`. |

## Security

The web endpoints are **unauthenticated**. Anyone who can reach `/review` can
read drafts, and anyone who can `POST /review/{id}/publish` can post to the
Page. Before exposing `serve` publicly, put it behind auth (reverse proxy, VPN,
or a shared-secret middleware you add in `web.py`).

## Guardrails recap

- The scheduler only refreshes and scans. Publishing is human-only.
- `publish.enabled: false` disables publishing; `publish.max_per_day` caps it.
- `publish.private: true` sends every post **unpublished** (page admins only).
  It is a real Graph write, not a dry run — but it never goes public, it leaves
  the draft in the queue, and it doesn't count toward `max_per_day`. This is
  the safe way to exercise the publish path end to end.
- Keep `--dry-run` working on every publish path.
