# Development

Conventions and recipes for changing the code. See
[README.md](README.md) for the module map and design spine.

## Setup and tests

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest          # whole suite; no network
```

Tests never touch the network and never need the `[server]` extra. Conventions:

- Pure logic is tested directly against fixture strings (XML/HTML/JSON), e.g.
  `tests/test_source.py` parses sample sitemap/RSS/HTML with no I/O.
- I/O is stubbed: monkeypatch `refresh.api_from_config`,
  `publishers.api_from_config`, or `draft_pipeline.publisher_for`, and pass a
  fake `SourceClient` (`FakeClient`, `FakeApi` in the test files).
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

1. Add a class in `publishers.py` with `name`, `describe(draft) -> str`, and
   `publish(draft) -> {"destination", "post_id", "permalink"}`.
2. Register it in `PUBLISHERS` and allow it in `config.validate` (the
   `facebook`/`linkedin` set).
3. Test the field mapping in `tests/test_publishers.py` with a fake API.
4. `LinkedInPublisher` is a stub — a real one needs OAuth (`w_member_social`
   for a profile, `w_organization_social` + partner approval for a company
   page) and `POST https://api.linkedin.com/rest/posts`.

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
4. `serve` → `/review/{id}` renders; **Dry run** prints the exact text.
5. `publish.private: true` makes the real approve an **unpublished** post, so
   you can exercise the whole publish path (Graph call, audit, redirect) without
   going public.
6. Timed posting: approve a draft (**Approve & schedule**), then either wait for
   a `publish.post_at` slot or hit `POST /publish/run` / `blog publish`. Confirm
   exactly one audit record and the expected state (`posted` publicly; the draft
   stays `approved` after a private send, and a second run the same day skips it).
7. Only then a real public approve — and only deliberately.
