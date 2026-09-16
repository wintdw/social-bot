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
        "image_style_briefs": {
            "technical": "TREATMENT BRIEF: drafted schematic, no lettering.",
            "editorial": "TREATMENT BRIEF: quiet still life.",
        },
        "default_style": "editorial",
        "recent": [{"id": "prev", "source": "x", "caption": "old caption"}],
        "recent_images": [
            {"id": "prev", "image_style": "editorial", "image_prompt": "a stack of books"}
        ],
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

    def test_carries_the_treatment_briefs_themselves(self):
        # A prompt has to serve the style it picks, which a bare key list cannot
        # tell it how to do.
        prompt = worker.build_prompt(_payload(), {"id": "d1"})
        assert "TREATMENT BRIEF: drafted schematic, no lettering." in prompt
        assert "TREATMENT BRIEF: quiet still life." in prompt
        assert "IMAGE STYLE BRIEFS" in prompt

    def test_carries_the_recent_images_to_avoid(self):
        prompt = worker.build_prompt(_payload(), {"id": "d1"})
        assert "RECENT IMAGES" in prompt
        assert "[editorial] a stack of books" in prompt

    def test_says_so_when_no_treatment_briefs_are_configured(self):
        payload = {**_payload(), "image_style_briefs": {}}
        assert "no treatment briefs configured" in worker.build_prompt(payload, {"id": "d1"})

    def test_empty_recent_images_reads_as_none(self):
        payload = {**_payload(), "recent_images": []}
        prompt = worker.build_prompt(payload, {"id": "d1"})
        assert "RECENT IMAGES (avoid repeating these subjects) ===\n(none)" in prompt

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


class TestBuildImagePrompt:
    """The prompt-only task: a new image prompt, caption untouched."""

    def test_asks_for_the_prompt_alone_and_leaves_the_style_to_the_operator(self):
        prompt = worker.build_image_prompt(
            _payload(), {"id": "d1", "caption": "Một caption", "image_style": "sketch"}
        )
        assert '"image_prompt"' in prompt
        assert "exactly this one key" in prompt
        # The treatment was picked on /review/{id}: it is context (it rides in the
        # POST block, which is how the agent knows what to write for), never a key
        # to send back. The old task asked it to choose one.
        assert "do NOT pick one" in prompt
        assert "the image_style you choose" not in prompt
        assert '"image_style":  exactly one of' not in prompt
        # The caption is context, not a thing to rewrite.
        assert "Một caption" in prompt
        assert "its image is being redone" in prompt

    def test_carries_the_treatment_briefs_and_the_recent_images(self):
        prompt = worker.build_image_prompt(_payload(), {"id": "d1"})
        assert "TREATMENT BRIEF: drafted schematic, no lettering." in prompt
        assert "RECENT IMAGES" in prompt and "[editorial] a stack of books" in prompt

    def test_leaves_the_caption_contract_out(self):
        # The DNA, the voice menu and the mastheads are about prose: beside the
        # point here, and their bulk would only dilute the image instruction.
        prompt = worker.build_image_prompt(_payload(), {"id": "d1"})
        assert "DNA BRIEF" not in prompt
        assert "Voice brief" not in prompt
        assert "[Học cùng Atento]" not in prompt


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

    def test_an_image_only_request_posts_to_the_image_prompt_endpoint(self, monkeypatch):
        calls = []
        self._patch(
            monkeypatch,
            calls,
            drafts=[{"id": "d1", "rewrite_mode": "image"}],
            result={"image_prompt": "a labelled diagram", "image_style": "diagram"},
        )
        assert worker.process_once(_cfg()) == 1
        assert calls[-1] == (
            "POST",
            "http://127.0.0.1:8083/api/drafts/d1/image-prompt",
            {"image_prompt": "a labelled diagram", "image_style": "diagram"},
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
        assert "IMAGE STYLE BRIEFS" in prompts[0]
        # …with the operator's register pinned.
        assert '"voice":        exactly "essay"' in prompts[0]
        # …and posted back where a caption rewrite lands, not to the image endpoint.
        assert calls[-1][1].endswith("/api/drafts/d1/rewrite")

    def test_each_draft_uses_its_own_prompt(self, monkeypatch):
        # Two requests of different kinds in one poll: each gets its own task.
        prompts = []
        calls = []
        self._patch(
            monkeypatch,
            calls,
            drafts=[{"id": "cap"}, {"id": "img", "rewrite_mode": "image"}],
            result={"caption": "hi"},
        )
        original = worker.run_commandcode

        def capture(settings, prompt):
            prompts.append(prompt)
            return original(settings, prompt)

        monkeypatch.setattr(worker, "run_commandcode", capture)
        worker.process_once(_cfg())
        assert len(prompts) == 2
        assert "IMAGE STYLE BRIEFS" in prompts[1]
        assert "DNA BRIEF" in prompts[0] and "DNA BRIEF" not in prompts[1]
        assert [call[1].rsplit("/", 1)[-1] for call in calls[1:]] == ["rewrite", "image-prompt"]

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
