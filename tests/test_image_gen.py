"""AI image generation: prompt building and URL construction (no network)."""

from __future__ import annotations

import pytest

from social_bot import image_gen


class TestBuildPrompt:
    def test_includes_title_and_excerpt(self):
        prompt = image_gen.build_prompt("System design", "A short summary")
        assert "System design" in prompt
        assert "A short summary" in prompt

    def test_adds_no_prohibitions_of_its_own(self):
        # Every prohibition belongs to the treatment file, so the builder must
        # not smuggle one in that could fight a look — a diagram is lettered,
        # and a rule written here would win over the file that asked for it.
        prompt = image_gen.build_prompt("Title", "Excerpt")
        for banned in ("no text", "no words", "no lettering", "No people", "no faces"):
            assert banned not in prompt

    def test_labels_in_the_subject_pass_through(self):
        subject = 'two agents exchanging messages. Labels: "AGENT 1", "SHARED CHANNEL"'
        prompt = image_gen.build_prompt("T", "E", image_prompt=subject)
        assert prompt.endswith(f"Subject: {subject}")

    def test_image_prompt_wins_over_title(self):
        # The rewriter's concept is what actually gets illustrated.
        prompt = image_gen.build_prompt(
            "Consumer Group", "an excerpt", image_prompt="a long ledger unspooling"
        )
        assert "a long ledger unspooling" in prompt
        assert "Consumer Group" not in prompt

    def test_image_prompt_omits_the_fallback_subject(self):
        prompt = image_gen.build_prompt("T", "E", image_prompt="a lone tree")
        assert "Subject: a lone tree" in prompt

    def test_style_leads_the_prompt(self):
        prompt = image_gen.build_prompt("T", "E", style="Deep navy palette.")
        assert prompt.startswith("Deep navy palette.")
        assert "Subject:" in prompt
        assert "Illustrate this idea" not in prompt

    def test_blank_style_is_omitted(self):
        prompt = image_gen.build_prompt("T", "E", style="   ")
        assert prompt.startswith("Subject:")

    def test_truncates_excerpt(self):
        prompt = image_gen.build_prompt("T", "x" * 500)
        assert "x" * 120 in prompt
        assert "x" * 121 not in prompt

    def test_empty_falls_back_to_generic(self):
        prompt = image_gen.build_prompt("", "")
        assert "software engineering" in prompt


class TestGenerateImageUrl:
    def test_builds_endpoint_and_params(self, monkeypatch):
        seen = {}

        def fake_urlopen(url, timeout, headers=None):
            seen["url"] = url
            seen["timeout"] = timeout
            seen["headers"] = headers
            return b"x" * 2000

        monkeypatch.setattr(image_gen, "_urlopen", fake_urlopen)
        url = image_gen.generate_image_url("a cat", width=512, height=768, timeout=12.0)
        assert url.startswith(f"{image_gen.DEFAULT_BASE_URL}/a%20cat")
        assert "width=512" in url and "height=768" in url
        assert "nologo=true" in url
        assert "token=" not in url
        assert "sk_" not in url
        assert seen["timeout"] == 12.0
        assert seen["headers"] is None

    def test_custom_base_url_is_used(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            image_gen,
            "_urlopen",
            lambda url, timeout, headers=None: seen.update(url=url) or b"x" * 2000,
        )
        url = image_gen.generate_image_url("p", base_url="https://legacy.example/prompt/")
        assert url.startswith("https://legacy.example/prompt/p")
        assert seen["url"].startswith("https://legacy.example/prompt/p")

    def test_api_key_goes_in_authorization_header_not_url(self, monkeypatch):
        seen = {}

        def fake_urlopen(url, timeout, headers=None):
            seen["url"] = url
            seen["headers"] = headers
            return b"x" * 2000

        monkeypatch.setattr(image_gen, "_urlopen", fake_urlopen)
        url = image_gen.generate_image_url("p", api_key="sk_abc")
        # The key must never land in the stored/published URL.
        assert "sk_abc" not in url
        assert seen["headers"] == {"Authorization": "Bearer sk_abc"}

    def test_http_error_reports_status_and_body(self, monkeypatch):
        import io
        import urllib.error

        def fake_urlopen(url, timeout, headers=None):
            body = io.BytesIO(b'{"error":"A valid API key is required"}')
            raise urllib.error.HTTPError(url, 401, "Unauthorized", None, body)

        monkeypatch.setattr(image_gen, "_urlopen", fake_urlopen)
        with pytest.raises(image_gen.ImageGenError, match="HTTP 401"):
            image_gen.generate_image_url("p")

    def test_transport_failure_raises(self, monkeypatch):
        def boom(url, timeout, headers=None):
            raise OSError("no route")

        monkeypatch.setattr(image_gen, "_urlopen", boom)
        with pytest.raises(image_gen.ImageGenError):
            image_gen.generate_image_url("p")

    def test_tiny_response_raises(self, monkeypatch):
        monkeypatch.setattr(image_gen, "_urlopen", lambda url, timeout, headers=None: b"")
        with pytest.raises(image_gen.ImageGenError):
            image_gen.generate_image_url("p")


class TestGenerateForDraft:
    def test_passes_prompt_and_key_through(self, monkeypatch):
        captured = {}

        def fake_generate(prompt, **kwargs):
            captured["prompt"] = prompt
            captured.update(kwargs)
            return "https://image/prompt"

        monkeypatch.setattr(image_gen, "generate_image_url", fake_generate)
        url = image_gen.generate_for_draft(
            "Title",
            "Excerpt",
            style="Navy palette.",
            image_prompt="a long ledger unspooling",
            width=100,
            height=200,
            api_key="k",
        )
        assert url == "https://image/prompt"
        assert captured["prompt"].startswith("Navy palette.")
        assert "a long ledger unspooling" in captured["prompt"]
        assert captured["api_key"] == "k"
        assert captured["width"] == 100 and captured["height"] == 200
