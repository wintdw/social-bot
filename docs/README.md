# social-bot docs

Operator and contributor documentation. Start here, then follow the link for
your task.

- **[content-pipeline.md](content-pipeline.md)** — the source → rewrite → review
  → publish workflow, its state machine, endpoints, and how to extend it.
- **[operations.md](operations.md)** — running, deploying, schedules, data
  layout, troubleshooting.
- **[development.md](development.md)** — setup, tests, conventions, and how to
  add a command / config key / source / destination / UI component.
- **[design/design-system.md](design/design-system.md)** — the operator UI's
  tokens, components, and rules; read before changing markup or the stylesheet.
  The generated visual preview is `design/styleframe.html`.
- **[atento-dna.md](atento-dna.md)** — the Atento brand-voice playbook the
  rewriter agent applies (referenced by `publish.dna_file`).
- **[atento-image-style.md](atento-image-style.md)** — the shared palette/finish
  floor prepended to every generated image prompt (`image_gen.style_file`). The
  per-post **treatments** it composes with live in
  **[image-styles/](image-styles/)** (`image_gen.styles`, chosen by the rewriter
  like the masthead, DNA §9.2).

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
| Change the AI-tell checks shown on /review (advisory lint) | `src/social_bot/caption_lint.py`, `tests/test_caption_lint.py` |
| Change AI image generation (prompt, endpoint, provider) | `src/social_bot/image_gen.py`, `tests/test_image_gen.py` |
| Change the image look / brand style | `docs/atento-image-style.md` (shared floor) + `docs/image-styles/*.md` (per-post treatments), then `image_gen.style_file` / `image_gen.styles` in `config.yaml` |
| Add a social destination (LinkedIn, …) | new package under `src/social_bot/destinations/`, register it in `destinations/registry.py`, then `tests/test_destinations.py` / `tests/test_publishers.py` |
| Change one platform's publishing / transport / feed | `src/social_bot/destinations/<name>/` (facebook: `api.py`, `publisher.py`, `reader.py`, `feed.py`, `feed_html.py`) |
| Change the review UI (HTML) | `src/social_bot/draft_html.py`, `tests/test_draft_html.py` |
| Change the dashboard / published / status pages | `src/social_bot/dashboard_html.py`, `tests/test_dashboard_html.py` |
| Change the shared nav, layout, or stylesheet | `src/social_bot/ui.py`, then `docs/design/design-system.md` |
| Change the design preview / styleguide | `src/social_bot/styleframe.py`, then `scripts/build_styleframe.py` |
| Change the Atento brand voice / rewrite brief | `docs/atento-dna.md`, then `publish.dna_file` in `config.yaml` |
| Change the web routes / JSON API / schedule loops | `src/social_bot/web.py` |
| Change the page-feed dashboard | `src/social_bot/destinations/facebook/feed.py`, `feed_html.py`, `reader.py` |
| Change how a caption's row title is derived (the hook under the masthead) | `src/social_bot/caption.py`, `tests/test_caption.py` |
| Change Graph API calls | `src/social_bot/destinations/facebook/api.py` |
| Change the deploy image / container | `Dockerfile`, `docker-compose.yml` |
| Update the guide agents read first | `AGENTS.md` |

## Design spine (read before editing)

1. **Pure logic never touches the network.** Parsing/model code (`caption.py`,
   `source.py`, `drafts.py`, `draft_html.py`, the facebook `feed.py`, and the
   time helpers in `web.py`) is unit-testable with no sockets and no fastapi.
   Only the destination packages (`destinations/facebook/api.py`,
   `publisher.py`, `reader.py`) and `source_api.py` do I/O.
2. **Platform logic is isolated.** Everything that talks to a platform lives in
   `destinations/<name>/`; the core (pipeline, CLI, web, UI) reaches it only
   through `destinations/registry.py`. Adding LinkedIn means a new package, not
   edits to the pipeline.
3. **Orchestration is thin and explicit.** `draft_pipeline.py` and the facebook
   reader wire pure code + I/O together and are the only places that read/write
   the `data/` files.
4. **Nothing posts without a human approval.** The `serve` scheduler refreshes
   the feed and scans sources into drafts; its posting loop (`--publish-at` /
   `publish.post_at`) only ever posts drafts a person already approved on
   `/review/{id}`. It never approves, rewrites, or touches `extracted`/`ai_draft`
   drafts. `publish.post_at: []` disables timed posting entirely.
5. **No new runtime dependency without cause.** Runtime is PyYAML only;
   HTTP is stdlib `urllib`; XML/HTML use `xml.etree` / `html.parser`.
   fastapi/uvicorn/python-multipart are the optional `[server]` extra.
6. **The operator UI is one system.** `ui.py` owns the stylesheet, the nav, and
   the `layout`/`badge`/`notice_html` primitives; page modules return fragments
   only. The tokens, components, and rules are in
   [design/design-system.md](design/design-system.md), enforced by
   `tests/test_design_system.py`; regenerate the preview with
   `scripts/build_styleframe.py`.
