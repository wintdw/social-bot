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
- **[voices/](voices/)** — the per-post **voice menu** (`publish.voices`): one
  file per voice (`technical` / `essay` / `announcement` / `funny`), each the
  register's brief **and** a growing corpus of verbatim human **samples**. The
  rewriter picks one per post and returns it as `voice`, delivered in
  `GET /api/drafts` `voices`. Refines how a register sounds; the DNA still owns
  structure.
- **[image-styles/](image-styles/)** — how a post's image may be drawn:
  `diagram.md` (the code-drawn explainer plate) and `illustration.md` (a crafted
  `anatomy` isometric figure, used selectively).

`AGENTS.md` (repo root) is the short brief; these docs are the detail.

## Where to work

| You want to… | Work in |
|---|---|
| Add or change a CLI command / flag | `src/social_bot/cli.py` |
| Add a config key (default + validation) | `src/social_bot/config.py`, `config.yaml`, `tests/test_config.py` |
| Add a source type / feed parser | `src/social_bot/source.py` (parse + `parse_source`), `src/social_bot/draft_pipeline.py:scan_sources`, `tests/test_source.py` |
| Change how original posts are seeded (the idea themes) | `src/social_bot/ideas.py` (parse/slug) + `draft_pipeline.py` (`idea_brief`/`queue_ideas`/`request_ideas`) + the `ideas` block in `config.yaml`, `tests/test_ideas.py` / `tests/test_draft_pipeline.py` |
| Change how a source is fetched (HTTP/retries) | `src/social_bot/source_api.py` |
| Change the Draft model, states, or persistence | `src/social_bot/drafts.py`, `tests/test_drafts.py` |
| Change scan / rewrite / publish orchestration | `src/social_bot/draft_pipeline.py`, `tests/test_draft_pipeline.py` |
| Trigger a rewrite from the UI (the rewriter worker) | `scripts/rewrite_worker.py` + `Draft.rewrite_requested_at` (`drafts.py`) + `draft_pipeline.py` (`request_rewrite`/`rewrite_queue`) + `web.py` (`/api/rewrite-queue`), `tests/test_rewrite_worker.py` |
| Change the post queue order (manual ordering) | the **Post queue** tab's queue panel in `dashboard_html.py` (`render_queue_html`, `_queue_panel`, `_queue_row`) + `draft_pipeline.py` (`_queue_key`, `set_queue_order`, `move_in_queue`) + `Draft.queue_order` in `drafts.py`, `tests/test_dashboard_html.py` / `tests/test_draft_pipeline.py` |
| Change the AI-tell checks shown on /review (advisory lint) | `src/social_bot/caption_lint.py`, `tests/test_caption_lint.py` |
| Change a code-drawn plate (the isometric scene) | `src/social_bot/diagram.py` (the plates + `diagram_kind`), `src/social_bot/iso.py` (the kit), `src/social_bot/diagram_html.py` (wraps the SVG to a page), `docs/image-styles/diagram.md`, `tests/test_diagram.py` |
| Draw a post's illustration with the `anatomy` skill | `docs/image-styles/illustration.md` (operator/agent-drawn; the PNG lands in the served `/images/` store) |
| Add a social destination (LinkedIn, …) | new package under `src/social_bot/destinations/`, register it in `destinations/registry.py`, then `tests/test_destinations.py` / `tests/test_publishers.py` |
| Change one platform's publishing / transport / feed | `src/social_bot/destinations/<name>/` (facebook: `api.py`, `publisher.py`, `reader.py`, `feed.py`, `feed_html.py`) |
| Change the review UI (HTML) | `src/social_bot/draft_html.py`, `tests/test_draft_html.py` |
| Change the dashboard / published / status pages | `src/social_bot/dashboard_html.py`, `tests/test_dashboard_html.py` |
| Change the shared nav, layout, or stylesheet | `src/social_bot/ui.py`, then `docs/design/design-system.md` |
| Change the design preview / styleguide | `src/social_bot/styleframe.py`, then `scripts/build_styleframe.py` |
| Change the Atento brand voice / rewrite brief | `docs/atento-dna.md`, then `publish.dna_file` in `config.yaml` |
| Add or change a voice (a `voice` brief + samples) | `docs/voices/<key>.md`, then `publish.voices` in `config.yaml` |
| Change the rewriter's **own-voice** retrieval (the `MY VOICE` block, corpus, index) | `src/social_bot/voice.py`, the `voice` block in `config.yaml`, `tests/test_voice.py`, then [content-pipeline.md](content-pipeline.md) §2c |
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
   fastapi/uvicorn/python-multipart are the optional `[server]` extra, and
   lancedb/pyarrow/fastembed the optional `[voice]` extra (the rewriter's own-voice
   retrieval, §2c of [content-pipeline.md](content-pipeline.md) — needed where the
   worker runs, never by the serve container).
6. **The operator UI is one system.** `ui.py` owns the stylesheet, the nav, and
   the `layout`/`badge`/`notice_html` primitives; page modules return fragments
   only. The tokens, components, and rules are in
   [design/design-system.md](design/design-system.md), enforced by
   `tests/test_design_system.py`; regenerate the preview with
   `scripts/build_styleframe.py`.
