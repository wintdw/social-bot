"""HTML-to-PNG through the host's Chromium: binary lookup and the screenshot call."""

from __future__ import annotations

import pytest

from social_bot import browser_shot


class TestBrowserShot:
    def test_env_override_wins(self, tmp_path, monkeypatch):
        binary = tmp_path / "chrome"
        binary.write_bytes(b"x")
        monkeypatch.setenv("SOCIAL_BOT_CHROMIUM", str(binary))
        assert browser_shot.find_chromium() == str(binary)

    def test_empty_when_nothing_available(self, monkeypatch):
        monkeypatch.delenv("SOCIAL_BOT_CHROMIUM", raising=False)
        monkeypatch.setattr(browser_shot.glob, "glob", lambda pattern: [])
        monkeypatch.setattr(browser_shot.shutil, "which", lambda name: None)
        assert browser_shot.find_chromium() == ""

    def test_raises_without_a_browser(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SOCIAL_BOT_CHROMIUM", raising=False)
        monkeypatch.setattr(browser_shot.glob, "glob", lambda pattern: [])
        monkeypatch.setattr(browser_shot.shutil, "which", lambda name: None)
        with pytest.raises(browser_shot.ShotError, match="no Chromium"):
            browser_shot.html_to_png("<html></html>", tmp_path / "out.png")

    def test_returns_the_screenshot(self, tmp_path, monkeypatch):
        dest = tmp_path / "out.png"
        monkeypatch.setattr(browser_shot, "find_chromium", lambda: "/bin/chromium")

        def _run(cmd, **kwargs):
            assert "--screenshot=" + str(dest) in cmd
            dest.write_bytes(b"\x89PNG fake")
            return browser_shot.subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(browser_shot.subprocess, "run", _run)
        assert browser_shot.html_to_png("<html></html>", dest) == dest
        assert dest.read_bytes() == b"\x89PNG fake"
