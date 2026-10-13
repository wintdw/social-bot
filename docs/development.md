# Development

Conventions and recipes for changing the code. See
[README.md](README.md) for the module map and design spine.

## Setup and tests

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest          # whole suite; no network
.venv/bin/ruff check src tests scripts   # lint
.venv/bin/ruff format src tests scripts  # format in place (--check to verify)
```

Ruff (config in `pyproject.toml`, `[tool.ruff]`) is the formatter and linter of
record. Its `select` is pinned on purpose so the check doesn't drift with ruff's
releases, and `E501` is off — the formatter owns line length, and long strings
(URLs, HTML fragments, the stylesheet) are not re-wrapped.

Tests never touch the network and never need the `[server]` extra. Conventions:

- Pure logic is tested directly against fixture strings (XML/HTML/JSON), e.g.
  `tests/test_source.py` parses sample sitemap/RSS/HTML with no I/O.
- I/O is stubbed: monkeypatch `destinations.facebook.api.api_from_config`,
  `destinations.facebook.publisher.api_from_config`, or
  `draft_pipeline.publisher_for`, and pass a fake `SourceClient` (`FakeClient`,
  `FakeApi` in the test files).
- Stateful code uses `tmp_path` and points `cfg["review"]["dir"]` (and
  `cfg["publish"]["dir"]`) at it.
- `web.py`'s scheduling helpers are pure and tested without fastapi
  (`tests/test_web.py`). Route handlers are not unit-tested — smoke-test them by
  running `serve`.

## Style

- No comments unless the logic isn't self-evident; match the surrounding style.
- Keep modules small and single-purpose; mirror the pure/network/orchestration
  split described in `docs/README.md`.
- Add to `DEFAULTS` in `config.py` and validate in `validate()`; document new
  keys in `config.yaml` with a comment.
- Prefix modules with the domain (`source_*`, `draft_*`) to keep related files
  grouped.

## UI and the design system

The operator UI is one system, not per-page styling. `ui.py` owns the
stylesheet, the nav, and the `layout`/`badge`/`notice_html` primitives; page
modules return fragments only and hand them to `layout()`. Read
[design/design-system.md](design/design-system.md) before changing any markup.

- Never put CSS in a page module or an inline `style="…"` in markup — add a
  class to `ui._CSS` and reuse the existing tokens.
- Compose from the shared components (`.panel`, `.stack`, `.cols`, `.cmdbar`,
  `.btn`, `.badge`, `.pill`, `.qrow`, `.stepper`, …).
- Keep the semantics: the accent is reserved for the primary action and the
  focused stage, state is carried by colour **and** a dot **and** a label, and
  every control stays at least 44px tall.

## Recipe: change the UI

1. Change `ui._CSS`, `ui.py`'s primitives, or the relevant page renderer.
2. Regenerate the styleframe: `.venv/bin/python scripts/build_styleframe.py`.
3. `.venv/bin/python -m pytest tests/test_design_system.py` — it fails on an
   unstyled class, an undefined token, or a stale styleframe.
4. If you added a component, show it on the styleframe's **Foundations** tab
   (`styleframe.py`).

## Recipe: add a CLI command

1. Add a subparser in `cli.py:_parse_args` and `set_defaults(func=_cmd_x)`.
2. Write `_cmd_x`, catching `ValueError → 2`, `ApiError`/`SourceError → 1`,
   `OSError → 1` (see the existing `_DATA_DIR_HINT` pattern).
3. Keep it thin: put logic in the relevant module, not the CLI.
4. Add arg-parsing / usage tests in `tests/test_cli.py`.

## Recipe: add a config key

1. Add it to `DEFAULTS` (and the example in `config.yaml`) with a comment.
2. Add a `validate()` branch if it can be malformed.
3. Cover both default and rejection in `tests/test_config.py`.

## Recipe: add a source type

1. Write `parse_<type>(xml_or_html_text, …) -> list[Item]` in `source.py`
   (pure; strip tags via `clean_text`).
2. Dispatch it in `source.parse_source` and allow the type in `config.validate`.
3. Fetching is usually unchanged — `SourceClient.get_text` returns text.
4. Test it in `tests/test_source.py` with a fixture string.

## Recipe: add a destination

Everything platform-specific lives in one package; the core never changes.

1. Create `src/social_bot/destinations/<name>/` with a `Publisher` subclass
   (`destinations/base.py`): set `name`, `label`, implement
   `describe(draft) -> str` and `publish(draft) -> PublishResult`, and override
   `validate_config(dst)` / `configured()` if it has its own config schema.
2. Register it in `destinations/registry.py` (`PUBLISHERS`; add a `READERS`
   entry too if it can read an account feed).
3. Add its `DEFAULTS["destinations"]["<name>"]` block in `config.py` and the
   `credentials.example.yaml` entry. Routing is `publish.destinations` in
   `config.yaml`; `config.validate` accepts any registered name automatically.
4. Test the field mapping in `tests/test_publishers.py` with a fake transport;
   registry/config behaviour in `tests/test_destinations.py`.
5. `linkedin/publisher.py` shows the delegate shape: it holds no token and calls
   linkin-bot's `POST /post` gateway (text + optional image as base64) instead of
   the platform API. A destination that talks to the platform directly needs its
   own OAuth (LinkedIn: `w_member_social` for a profile, partner approval for a
   company page, and `POST https://api.linkedin.com/rest/posts`).

## Recipe: add a route

Routes live in `web.create_app`. Import fastapi names at module scope (they are
guarded by `try/except ImportError` so `web.py` still imports without the
extra) — keeping them module-level is required for FastAPI to resolve the
handlers' string annotations (e.g. `Request`). Mirror `/refresh` for
fire-and-forget jobs (409 when busy) and `/scan`/`/publish/run` for the
browser-vs-JSON response pattern. A new scheduled loop belongs in
`create_app` beside `_scheduler_loop`/`_scanner_loop`/`_posting_loop`, keyed on a
pure `HH:MM` helper + a `current_slot` dedupe.

## Exit codes

`0` success · `1` network/Graph/source/write failure · `2` usage/config error.
Each `_cmd_*` returns the code; `main` never lets an exception traceback.

## Live checks before shipping

1. `.venv/bin/python -m pytest`
2. `.venv/bin/social-bot blog scan` (or `curl -X POST …/scan`) → drafts appear.
3. `curl -s …/api/status` → counts look right.
4. `serve` → `/review/{id}` renders; **Save** persists edits, and the Preview
   panel shows the exact text that would post.
5. `publish.private: true` makes the real approve an **unpublished** post, so
   you can exercise the whole publish path (Graph call, audit, redirect) without
   going public.
6. Timed posting: approve a draft (**Approve & schedule**), then either wait for
   a `publish.post_at` slot or hit `POST /publish/run` / `blog publish`. Confirm
   exactly one audit record and the expected state (`posted` publicly; the draft
   stays `approved` after a private send, and a second run the same day skips it).
   **Unapprove** on the same page pulls a queued draft back out (it returns to
   `ai_draft`), so one approved by mistake can be recovered before the slot.
7. Only then a real public approve — and only deliberately.

