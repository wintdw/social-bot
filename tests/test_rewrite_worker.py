"""The rewriter worker: prompt building, CLI parsing, and the post-back loop.

No network and no CLI: subprocess and the HTTP calls are stubbed.
"""

from __future__ import annotations

import subprocess

import pytest
import rewrite_worker as worker

from social_bot.config import DEFAULTS


def _cfg(**rewrite):
    return {**DEFAULTS, "rewrite": {**DEFAULTS["rewrite"], **rewrite}}


def _payload(drafts=None):
    return {
        "dna": "DNA BRIEF",
        "voices": {"technical": "Voice brief"},
        "voice_choices": ["technical", "essay"],
        "default_voice": "technical",
        "mastheads": {"choices": ["[Học cùng Atento]"], "default": "[Học cùng Atento]"},
        "image_styles": ["technical", "editorial"],
        "default_style": "editorial",
        "recent": [{"id": "prev", "source": "x", "caption": "old caption"}],
        "drafts": drafts or [],
    }


class TestExtractJson:
    def test_plain(self):
        assert worker.extract_json('{"a": 1}') == {"a": 1}

    def test_fenced(self):
        assert worker.extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_surrounded_by_prose(self):
        assert worker.extract_json('Here you go:\n{"a": 1}\nThanks') == {"a": 1}

    def test_no_json_is_an_error(self):
        with pytest.raises(worker.WorkerError):
            worker.extract_json("no object here")

    def test_not_an_object_is_an_error(self):
        with pytest.raises(worker.WorkerError):
            worker.extract_json("[1, 2]")


class TestBuildPrompt:
    def test_carries_the_brief_choices_and_draft(self):
        prompt = worker.build_prompt(_payload(), {"id": "d1", "title": "Headline"})
        assert "DNA BRIEF" in prompt
        assert "Voice brief" in prompt
        assert "[Học cùng Atento]" in prompt  # the masthead choices
        assert "old caption" in prompt  # recent captions to avoid
        assert '"id": "d1"' in prompt
        assert "technical" in prompt  # voice + style choices


class TestAuthHeader:
    def test_empty_without_site_credentials(self):
        assert worker._auth_header({}) == {}

    def test_basic_auth_from_site_credentials(self):
        header = worker._auth_header({"site": {"user": "u", "password": "p"}})
        assert header == {"Authorization": "Basic dTpw"}  # base64("u:p")


class TestRunCommandcode:
    def _fake(self, monkeypatch, returncode, stdout="", stderr=""):
        monkeypatch.setattr(
            worker.subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(a[0], returncode, stdout, stderr),
        )

    def test_parses_the_final_result_frame(self, monkeypatch):
        out = (
            '{"type": "event", "event": {}}\n'
            '{"type": "result", "subtype": "success", "finalText": "{\\"caption\\": \\"hi\\"}"}\n'
        )
        self._fake(monkeypatch, 0, out)
        assert worker.run_commandcode(_cfg()["rewrite"], "prompt") == {"caption": "hi"}

    def test_nonzero_exit_is_an_error(self, monkeypatch):
        self._fake(monkeypatch, 3, "", "not authenticated")
        with pytest.raises(worker.WorkerError, match="exited 3"):
            worker.run_commandcode(_cfg()["rewrite"], "prompt")

    def test_a_missing_command_is_an_error(self, monkeypatch):
        def boom(*a, **k):
            raise FileNotFoundError("nope")

        monkeypatch.setattr(worker.subprocess, "run", boom)
        with pytest.raises(worker.WorkerError, match="command not found"):
            worker.run_commandcode(_cfg()["rewrite"], "prompt")

    def test_a_failed_subtype_is_an_error(self, monkeypatch):
        self._fake(monkeypatch, 0, '{"type": "result", "subtype": "error", "finalText": ""}\n')
        with pytest.raises(worker.WorkerError, match="ended early"):
            worker.run_commandcode(_cfg()["rewrite"], "prompt")


class TestProcessOnce:
    def _patch(self, monkeypatch, calls, *, drafts, result=None, error=None):
        def fake_request(cfg, method, url, payload=None):
            calls.append((method, url, payload))
            if url.endswith("/api/rewrite-queue"):
                return _payload(drafts)
            return {}

        def fake_run(settings, prompt):
            if error:
                raise worker.WorkerError(error)
            return result

        monkeypatch.setattr(worker, "_request_json", fake_request)
        monkeypatch.setattr(worker, "run_commandcode", fake_run)

    def test_posts_the_rewrite_back(self, monkeypatch):
        calls = []
        self._patch(monkeypatch, calls, drafts=[{"id": "d1"}], result={"caption": "hi"})
        assert worker.process_once(_cfg()) == 1
        assert calls[-1] == (
            "POST",
            "http://127.0.0.1:8083/api/drafts/d1/rewrite",
            {"caption": "hi"},
        )

    def test_records_a_failure_and_keeps_going(self, monkeypatch):
        calls = []
        self._patch(monkeypatch, calls, drafts=[{"id": "d1"}], error="boom")
        assert worker.process_once(_cfg()) == 0
        method, url, payload = calls[-1]
        assert method == "POST" and url.endswith("/api/drafts/d1/rewrite-error")
        assert payload == {"error": "boom"}

    def test_no_requests_only_polls(self, monkeypatch):
        calls = []
        self._patch(monkeypatch, calls, drafts=[])
        assert worker.process_once(_cfg()) == 0
        assert len(calls) == 1  # just the GET

    def test_dry_run_never_runs_the_cli_or_posts(self, monkeypatch):
        calls = []
        self._patch(monkeypatch, calls, drafts=[{"id": "d1"}], result={"caption": "hi"})

        def fail(*a, **k):
            raise AssertionError("the CLI must not run in --dry-run")

        monkeypatch.setattr(worker, "run_commandcode", fail)
        assert worker.process_once(_cfg(), dry_run=True) == 0
        assert len(calls) == 1

    def test_an_unknown_draft_id_raises(self, monkeypatch):
        calls = []
        self._patch(monkeypatch, calls, drafts=[{"id": "d1"}])
        with pytest.raises(worker.WorkerError, match="not in the rewrite queue"):
            worker.process_once(_cfg(), draft_id="nope")
