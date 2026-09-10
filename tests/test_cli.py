"""`post` argument parsing and usage validation (no network)."""

from __future__ import annotations

import json

import pytest

from social_bot import cli

PHOTO = "https://example.com/a.jpg"


@pytest.fixture
def stub_config(monkeypatch):
    """Bypass config loading so _cmd_post can be driven in isolation."""
    monkeypatch.setattr(cli, "_load_config", lambda args: {"graph": {"page_id": "123"}})


class TestPostArgs:
    def test_photo_alone_is_accepted(self):
        args = cli._parse_args(["post", "--photo", PHOTO])
        assert args.message is None
        assert args.photo == PHOTO

    def test_message_plus_photo(self):
        args = cli._parse_args(["post", "--message", "hi", "--photo", PHOTO])
        assert (args.message, args.photo) == ("hi", PHOTO)


class TestPostValidation:
    def test_neither_message_nor_photo_is_usage_error(self, stub_config, capsys):
        assert cli._cmd_post(cli._parse_args(["post"])) == 2
        assert "provide --message and/or --photo" in capsys.readouterr().err

    def test_photo_with_link_is_rejected(self, stub_config, capsys):
        args = cli._parse_args(["post", "--photo", PHOTO, "--link", "https://x.test"])
        assert cli._cmd_post(args) == 2
        assert "--link cannot be combined with --photo" in capsys.readouterr().err


class TestPostExecution:
    def test_photo_dry_run_targets_photos_endpoint(
        self, stub_config, monkeypatch, capsys
    ):
        monkeypatch.setattr(cli, "api_from_config", lambda cfg, token: object())
        args = cli._parse_args(
            ["post", "--message", "hi", "--photo", PHOTO, "--dry-run"]
        )
        assert cli._cmd_post(args) == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == "dry-run: would POST to /123/photos"
        assert json.loads("\n".join(lines[1:])) == {"url": PHOTO, "caption": "hi"}

    def test_photo_post_sends_caption_and_prints_permalink(
        self, stub_config, monkeypatch, capsys
    ):
        calls = {}

        class FakeApi:
            def create_photo_post(self, page_id, caption, url, published=True):
                calls.update(
                    page_id=page_id, caption=caption, url=url, published=published
                )
                return {"id": "999", "post_id": "123_456"}

        monkeypatch.setattr(cli, "api_from_config", lambda cfg, token: FakeApi())
        args = cli._parse_args(["post", "--photo", PHOTO])
        assert cli._cmd_post(args) == 0
        assert calls == {
            "page_id": "123",
            "caption": "",
            "url": PHOTO,
            "published": True,
        }
        assert "https://www.facebook.com/123_456" in capsys.readouterr().out

    def test_status_post_still_targets_feed(self, stub_config, monkeypatch, capsys):
        monkeypatch.setattr(cli, "api_from_config", lambda cfg, token: object())
        args = cli._parse_args(["post", "--message", "hi", "--dry-run"])
        assert cli._cmd_post(args) == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == "dry-run: would POST to /123/feed"
        assert json.loads("\n".join(lines[1:])) == {"message": "hi"}


class TestPostPrivateMode:
    @pytest.fixture
    def private_config(self, monkeypatch):
        monkeypatch.setattr(
            cli,
            "_load_config",
            lambda args: {"graph": {"page_id": "123"}, "publish": {"private": True}},
        )

    def test_dry_run_marks_the_post_unpublished(
        self, private_config, monkeypatch, capsys
    ):
        monkeypatch.setattr(cli, "api_from_config", lambda cfg, token: object())
        args = cli._parse_args(
            ["post", "--message", "hi", "--photo", PHOTO, "--dry-run"]
        )
        assert cli._cmd_post(args) == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == "dry-run: would POST to /123/photos (unpublished)"
        assert json.loads("\n".join(lines[1:])) == {
            "url": PHOTO,
            "caption": "hi",
            "published": "false",
        }

    def test_private_post_sends_published_false(
        self, private_config, monkeypatch, capsys
    ):
        calls = {}

        class FakeApi:
            def create_photo_post(self, page_id, caption, url, published=True):
                calls["published"] = published
                return {"post_id": "123_456"}

        monkeypatch.setattr(cli, "api_from_config", lambda cfg, token: FakeApi())
        assert cli._cmd_post(cli._parse_args(["post", "--photo", PHOTO])) == 0
        assert calls["published"] is False
        assert "Posted privately (unpublished)" in capsys.readouterr().out


class TestBlogScanArgs:
    def test_flags_parse(self):
        args = cli._parse_args(
            ["blog", "scan", "--json", "--source", "a", "--source", "b", "--limit", "3"]
        )
        assert args.json is True
        assert args.source == ["a", "b"]
        assert args.limit == 3
        assert args.func is cli._cmd_blog_scan


class TestBlogScanCommand:
    def _stub(self, monkeypatch, result):
        monkeypatch.setattr(cli, "_load_config", lambda args: {})
        monkeypatch.setattr(
            cli, "scan_sources", lambda cfg, limit=None, source_names=None: result
        )

    def test_reports_queued(self, monkeypatch, capsys):
        self._stub(
            monkeypatch,
            {
                "sources": 1,
                "added": 1,
                "total_drafts": 1,
                "errors": [],
                "items": [{"id": "post-one", "title": "Title"}],
            },
        )
        assert cli._cmd_blog_scan(cli._parse_args(["blog", "scan"])) == 0
        out = capsys.readouterr().out
        assert "Queued 1 new draft(s)" in out and "post-one" in out

    def test_json_mode(self, monkeypatch, capsys):
        self._stub(
            monkeypatch,
            {"sources": 1, "added": 0, "total_drafts": 0, "errors": [], "items": []},
        )
        assert cli._cmd_blog_scan(cli._parse_args(["blog", "scan", "--json"])) == 0
        assert json.loads(capsys.readouterr().out)["added"] == 0

    def test_source_error_exits_1(self, monkeypatch, capsys):
        self._stub(
            monkeypatch,
            {
                "sources": 1,
                "added": 0,
                "total_drafts": 0,
                "errors": [{"source": "atento-blog", "error": "boom"}],
                "items": [],
            },
        )
        assert cli._cmd_blog_scan(cli._parse_args(["blog", "scan"])) == 1
        assert "boom" in capsys.readouterr().err
