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
        assert "technical" in prompt  # voice choices

    def test_says_not_to_write_an_image_prompt(self):
        prompt = worker.build_prompt(_payload(), {"id": "d1"})
        assert "Do not write an image prompt" in prompt

    def test_names_the_product_so_readers_know_what_it_is_about(self):
        prompt = worker.build_prompt(_payload(), {"id": "d1"})
        assert "Name the product the post is about" in prompt

    def test_a_locked_voice_names_the_key_and_forbids_another(self):
        # "Rewrite in this voice": the operator picked the register, so there is no
        # choice to make — the contract names that one key and a rule forbids
        # substituting another. The menu still rides along: the chosen register's
        # brief *is* the text the caption is written from.
        prompt = worker.build_prompt(_payload(), {"id": "d1", "voice": "essay"}, voice_locked=True)
        assert '"voice":        exactly "essay" — the reviewer chose it' in prompt
        assert '"voice":        exactly one of' not in prompt
        assert '- Write in the reviewer\'s chosen voice "essay"' in prompt
        assert "Voice brief" in prompt

    def test_an_unlocked_voice_is_the_agents_choice(self):
        prompt = worker.build_prompt(_payload(), {"id": "d1", "voice": "essay"})
        assert '"voice":        exactly one of: technical, essay' in prompt
        assert "the reviewer chose it" not in prompt
        assert "reviewer's chosen voice" not in prompt

    def test_a_lock_with_no_voice_falls_back_to_the_free_choice(self):
        # Nothing picked means nothing to hold, so the agent chooses as usual.
        prompt = worker.build_prompt(_payload(), {"id": "d1"}, voice_locked=True)
        assert '"voice":        exactly one of: technical, essay' in prompt
        assert "reviewer's chosen voice" not in prompt

    def test_carries_the_operators_own_voice_when_supplied(self):
        prompt = worker.build_prompt(_payload(), {"id": "d1"}, my_voice="PROFILE + REAL LINES")
        assert "=== MY VOICE (match the voice, not the content) ===" in prompt
        assert "PROFILE + REAL LINES" in prompt
        assert "Match the VOICE of the real messages in MY VOICE below" in prompt

    def test_my_voice_sits_between_the_menu_and_the_draft(self):
        prompt = worker.build_prompt(_payload(), {"id": "d1"}, my_voice="X")
        assert (
            prompt.index("=== VOICE MENU")
            < prompt.index("=== MY VOICE")
            < prompt.index("=== DRAFT TO REWRITE")
        )

    def test_leaves_my_voice_out_entirely_when_empty(self):
        # A run with no corpus must read exactly as it did before voice existed.
        prompt = worker.build_prompt(_payload(), {"id": "d1"})
        assert "MY VOICE" not in prompt
        assert "Match the VOICE of the real messages" not in prompt


class TestMyVoice:
    """The operator's own voice, attached to caption runs and never fatal."""

    def test_empty_when_the_voice_block_is_off(self, monkeypatch, capsys):
        monkeypatch.setattr(worker.voice, "enabled", lambda cfg: False)
        assert worker._my_voice({}, {"id": "d1"}) == ""
        assert capsys.readouterr().err == ""  # switched off is not a warning

    def test_warns_when_enabled_but_nothing_came_back(self, monkeypatch, capsys):
        monkeypatch.setattr(worker.voice, "enabled", lambda cfg: True)
        monkeypatch.setattr(worker.voice, "examples_block", lambda cfg, draft: "")
        assert worker._my_voice({}, {"id": "d1"}) == ""
        assert "no voice examples for d1" in capsys.readouterr().err

    def test_returns_the_block_when_there_is_one(self, monkeypatch):
        monkeypatch.setattr(worker.voice, "enabled", lambda cfg: True)
        monkeypatch.setattr(worker.voice, "examples_block", lambda cfg, draft: "BLOCK")
        assert worker._my_voice({}, {"id": "d1"}) == "BLOCK"


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

    def test_an_unknown_mode_is_a_full_rewrite(self, monkeypatch):
        calls = []
        self._patch(
            monkeypatch,
            calls,
            drafts=[{"id": "d1", "rewrite_mode": "nonsense"}],
            result={"caption": "hi"},
        )
        assert worker.process_once(_cfg()) == 1
        assert calls[-1][1].endswith("/api/drafts/d1/rewrite")

    def test_a_voice_locked_request_is_the_full_task_with_the_voice_pinned(self, monkeypatch):
        prompts = []
        calls = []
        self._patch(
            monkeypatch,
            calls,
            drafts=[{"id": "d1", "rewrite_mode": "caption-voice", "voice": "essay"}],
            result={"caption": "hi"},
        )
        original = worker.run_commandcode

        def capture(settings, prompt):
            prompts.append(prompt)
            return original(settings, prompt)

        monkeypatch.setattr(worker, "run_commandcode", capture)
        assert worker.process_once(_cfg()) == 1
        # The whole rewrite, not the smaller prompt-only task…
        assert "DNA BRIEF" in prompts[0]
        # …with the operator's register pinned.
        assert '"voice":        exactly "essay"' in prompts[0]
        # …and posted back where a caption rewrite lands, not to the image endpoint.
        assert calls[-1][1].endswith("/api/drafts/d1/rewrite")

    def test_a_caption_rewrite_carries_the_operators_voice(self, monkeypatch):
        prompts = []
        calls = []
        self._patch(monkeypatch, calls, drafts=[{"id": "d1"}], result={"caption": "hi"})
        monkeypatch.setattr(worker, "_my_voice", lambda cfg, draft: "VOICE-FOR-d1")
        original = worker.run_commandcode

        def capture(settings, prompt):
            prompts.append(prompt)
            return original(settings, prompt)

        monkeypatch.setattr(worker, "run_commandcode", capture)
        assert worker.process_once(_cfg()) == 1
        assert "VOICE-FOR-d1" in prompts[0]

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


def _ideas_payload(**over):
    payload = {
        "enabled": True,
        "source_name": "atento-original",
        "per_run": 2,
        "requested": True,
        "requested_at": "2026-09-10T10:00:00+07:00",
        "error": "",
        "topics": [
            {"name": "ClickHouse architecture", "url": "https://clickhouse.com/docs"},
            {"name": "MySQL internals", "url": ""},
        ],
        "existing": ["Old idea"],
        "dna": "DNA BRIEF",
        "recent": [{"id": "prev", "caption": "old caption"}],
    }
    payload.update(over)
    return payload


class TestBuildIdeasPrompt:
    def test_carries_themes_docs_dna_and_anti_repetition(self):
        prompt = worker.build_ideas_prompt(_ideas_payload())
        assert "DNA BRIEF" in prompt
        assert "ClickHouse architecture" in prompt
        assert "https://clickhouse.com/docs" in prompt  # reference docs
        assert "- Old idea" in prompt  # already queued
        assert "old caption" in prompt  # recent captions
        assert "exactly 2 of them" in prompt  # per_run
        assert '"ideas"' in prompt

    def test_no_themes_reads_as_configured_none(self):
        prompt = worker.build_ideas_prompt(_ideas_payload(topics=[]))
        assert "(no themes configured)" in prompt

    def test_asks_for_an_approachable_single_aspect_with_a_real_problem(self):
        prompt = worker.build_ideas_prompt(_ideas_payload())
        assert "Aim at a wide audience" in prompt
        assert "Go deep in ONE spot only" in prompt
        assert "real, familiar problem" in prompt
        assert "X là gì" in prompt  # a named example of what to skip
        assert "naming the system" in prompt  # the title must name the product


class TestProcessIdeasOnce:
    def _patch(self, monkeypatch, calls, *, initial, result=None, error=None, response=None):
        def fake_request(cfg, method, url, body=None):
            calls.append((method, url, body))
            if method == "GET" and url.endswith("/api/ideas"):
                return initial
            if url.endswith("/api/ideas"):
                return response or {"added": 2}
            return {}

        def fake_run(settings, prompt):
            if error:
                raise worker.WorkerError(error)
            return result

        monkeypatch.setattr(worker, "_request_json", fake_request)
        monkeypatch.setattr(worker, "run_commandcode", fake_run)

    def test_no_request_only_polls(self, monkeypatch):
        calls = []
        self._patch(monkeypatch, calls, initial=_ideas_payload(requested=False))
        assert worker.process_ideas_once(_cfg()) == 0
        assert len(calls) == 1  # just the GET

    def test_posts_the_batch_back(self, monkeypatch):
        calls = []
        ideas = [{"topic": "MySQL internals", "title": "B+ tree"}]
        self._patch(monkeypatch, calls, initial=_ideas_payload(), result={"ideas": ideas})
        assert worker.process_ideas_once(_cfg()) == 2
        assert calls[-1] == ("POST", "http://127.0.0.1:8083/api/ideas", {"ideas": ideas})

    def test_a_run_without_ideas_is_a_failure(self, monkeypatch):
        calls = []
        self._patch(monkeypatch, calls, initial=_ideas_payload(), result={"nope": 1})
        assert worker.process_ideas_once(_cfg()) == 0
        assert calls[-1][1].endswith("/api/ideas/error")
        assert "no `ideas` array" in calls[-1][2]["error"]

    def test_records_a_failure_and_keeps_going(self, monkeypatch):
        calls = []
        self._patch(monkeypatch, calls, initial=_ideas_payload(), error="boom")
        assert worker.process_ideas_once(_cfg()) == 0
        method, url, body = calls[-1]
        assert method == "POST" and url.endswith("/api/ideas/error")
        assert body == {"error": "boom"}

    def test_dry_run_never_runs_the_cli_or_posts(self, monkeypatch):
        calls = []
        self._patch(monkeypatch, calls, initial=_ideas_payload(), result={"ideas": []})

        def fail(*a, **k):
            raise AssertionError("the CLI must not run in --dry-run")

        monkeypatch.setattr(worker, "run_commandcode", fail)
        assert worker.process_ideas_once(_cfg(), dry_run=True) == 0
        assert len(calls) == 1
