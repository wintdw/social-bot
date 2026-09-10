# social-bot docs

Operator and contributor documentation. Start here, then follow the link for
your task.

- **[content-pipeline.md](content-pipeline.md)** — the source → rewrite → review
  → publish workflow, its state machine, endpoints, and how to extend it.
- **[operations.md](operations.md)** — running, deploying, schedules, data
  layout, troubleshooting.
- **[development.md](development.md)** — setup, tests, conventions, and how to
  add a command / config key / source / destination.
- **[atento-dna.md](atento-dna.md)** — the Atento brand-voice playbook the
  rewriter agent applies (referenced by `publish.dna_file`).

`AGENTS.md` (repo root) is the short brief; these docs are the detail.

## Where to work

| You want to… | Work in |
|---|---|
| Add or change a CLI command / flag | `src/social_bot/cli.py` |
| Add a config key (default + validation) | `src/social_bot/config.py`, `config.yaml`, `tests/test_config.py` |
| Add a source type / feed parser | `src/social_bot/source.py` (parse + `parse_source`), `src/social_bot/draft_pipeline.py:scan_sources`, `tests/test_source.py` |
| Change how a source is fetched (HTTP/retries) | `src/social_bot/source_api.py` |
| Change the Draft model, states, or persistence | `src/social_bot/drafts.py`, `tests/test_drafts.py` |
| Change scan / rewrite / publish orchestration | `src/social_bot/draft_pipeline.py`, `tests/test_draft_pipeline.py` |
| Add a social destination (LinkedIn, …) | `src/social_bot/publishers.py`, `tests/test_publishers.py` |
| Change the review UI (HTML) | `src/social_bot/draft_html.py`, `tests/test_draft_html.py` |
| Change the dashboard / published / status pages | `src/social_bot/dashboard_html.py`, `tests/test_dashboard_html.py` |
| Change the shared nav, layout, or stylesheet | `src/social_bot/ui.py` |
| Change the Atento brand voice / rewrite brief | `docs/atento-dna.md`, then `publish.dna_file` in `config.yaml` |
| Change the web routes / JSON API / schedule loops | `src/social_bot/web.py` |
| Change the page-feed dashboard | `src/social_bot/feed.py`, `feed_html.py`, `refresh.py` |
| Change Graph API calls | `src/social_bot/api.py` |
| Change the deploy image / container | `Dockerfile`, `docker-compose.yml` |
| Update the guide agents read first | `AGENTS.md` |

## Design spine (read before editing)

1. **Pure logic never touches the network.** Parsing/model code (`feed.py`,
   `source.py`, `drafts.py`, `draft_html.py`, and the time helpers in `web.py`)
   is unit-testable with no sockets and no fastapi. Only `api.py`,
   `source_api.py`, and `publishers.py` do I/O.
2. **Orchestration is thin and explicit.** `refresh.py` and
   `draft_pipeline.py` wire pure code + I/O together and are the only places
   that read/write the `data/` files.
3. **Nothing posts on a timer.** The `serve` scheduler only refreshes the feed
   and scans sources into drafts. Publishing is always a human action on
   `/review/{id}`. Do not wire `publish_draft` into a scheduler.
4. **No new runtime dependency without cause.** Runtime is PyYAML only;
   HTTP is stdlib `urllib`; XML/HTML use `xml.etree` / `html.parser`.
   fastapi/uvicorn/python-multipart are the optional `[server]` extra.
