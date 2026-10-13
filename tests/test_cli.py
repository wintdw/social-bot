"""`post` argument parsing and usage validation (no network)."""

from __future__ import annotations

import json

import pytest

from social_bot import cli

PHOTO = "https://example.com/a.jpg"


@pytest.fixture
def stub_config(monkeypatch):
    """Bypass config loading so _cmd_post can be driven in isolation."""
    monkeypatch.setattr(
        cli,
        "_load_config",
        lambda args: {"destinations": {"facebook": {"account_id": "123"}}},
    )


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
    def test_photo_dry_run_targets_photos_endpoint(self, stub_config, monkeypatch, capsys):
        monkeypatch.setattr(cli, "api_from_config", lambda cfg, token: object())
        args = cli._parse_args(["post", "--message", "hi", "--photo", PHOTO, "--dry-run"])
        assert cli._cmd_post(args) == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == "dry-run: would POST to /123/photos"
        assert json.loads("\n".join(lines[1:])) == {"url": PHOTO, "caption": "hi"}

    def test_photo_post_downloads_then_uploads_the_bytes(self, stub_config, monkeypatch, capsys):
        calls = {}
        monkeypatch.setattr(
            cli.media,
            "load",
            lambda cfg, url, **kw: (b"\xff\xd8\xffjpeg", "photo.jpg", "image/jpeg"),
        )

        class FakeApi:
            def create_photo_post(
                self, page_id, caption, data, *, filename="", content_type="", published=True
            ):
                calls.update(
                    page_id=page_id,
                    caption=caption,
                    data=data,
                    filename=filename,
                    content_type=content_type,
                    published=published,
                )
                return {"id": "999", "post_id": "123_456"}

        monkeypatch.setattr(cli, "api_from_config", lambda cfg, token: FakeApi())
        args = cli._parse_args(["post", "--photo", PHOTO])
        assert cli._cmd_post(args) == 0
        assert calls == {
            "page_id": "123",
            "caption": "",
            "data": b"\xff\xd8\xffjpeg",
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
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
            lambda args: {
                "destinations": {"facebook": {"account_id": "123"}},
                "publish": {"private": True},
            },
        )

    def test_dry_run_marks_the_post_unpublished(self, private_config, monkeypatch, capsys):
        monkeypatch.setattr(cli, "api_from_config", lambda cfg, token: object())
        args = cli._parse_args(["post", "--message", "hi", "--photo", PHOTO, "--dry-run"])
        assert cli._cmd_post(args) == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == "dry-run: would POST to /123/photos (unpublished)"
        assert json.loads("\n".join(lines[1:])) == {
            "url": PHOTO,
            "caption": "hi",
            "published": "false",
        }

    def test_private_post_sends_published_false(self, private_config, monkeypatch, capsys):
        calls = {}
        monkeypatch.setattr(
            cli.media, "load", lambda cfg, url, **kw: (b"jpeg", "photo.jpg", "image/jpeg")
        )

        class FakeApi:
            def create_photo_post(
                self, page_id, caption, data, *, filename="", content_type="", published=True
            ):
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


class TestBlogLocalizeArgs:
    def test_flags_parse(self):
        args = cli._parse_args(["blog", "localize-images", "--draft", "a", "--limit", "2"])
        assert args.draft == ["a"]
        assert args.limit == 2
        assert args.func is cli._cmd_blog_localize

    def test_defaults(self):
        args = cli._parse_args(["blog", "localize-images"])
        assert args.draft is None
        assert args.limit is None
        assert args.json is False


class TestBlogLocalizeCommand:
    def test_reports_what_moved(self, monkeypatch, capsys):
        monkeypatch.setattr(cli, "_load_config", lambda args: {})
        monkeypatch.setattr(
            cli,
            "localize_images",
            lambda cfg, **kw: {
                "localized": 1,
                "candidates": 2,
                "ids": ["post-one"],
                "errors": [],
            },
        )
        assert cli._cmd_blog_localize(cli._parse_args(["blog", "localize-images"])) == 0
        out = capsys.readouterr().out
        assert "Moved 1 image(s)" in out
        assert "post-one" in out


class TestBlogMastheadArgs:
    def test_flags_parse(self):
        args = cli._parse_args(["blog", "masthead", "--draft", "a", "--limit", "2", "--json"])
        assert args.draft == ["a"]
        assert args.limit == 2
        assert args.json is True
        assert args.func is cli._cmd_blog_masthead

    def test_defaults(self):
        args = cli._parse_args(["blog", "masthead"])
        assert args.draft is None
        assert args.limit is None


class TestBlogMastheadCommand:
    DOC_BAO = "[Đọc báo cùng Atento]"

    def _stub(self, monkeypatch, result):
        monkeypatch.setattr(cli, "_load_config", lambda args: {})
        monkeypatch.setattr(cli, "apply_masthead", lambda cfg, **kw: result)

    def test_reports_filled(self, monkeypatch, capsys):
        self._stub(
            monkeypatch,
            {"updated": 2, "ids": ["a", "b"], "masthead": self.DOC_BAO},
        )
        assert cli._cmd_blog_masthead(cli._parse_args(["blog", "masthead"])) == 0
        out = capsys.readouterr().out
        assert "Filled masthead on 2 draft(s)" in out and self.DOC_BAO in out

    def test_flags_are_passed_through(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(cli, "_load_config", lambda args: {})
        monkeypatch.setattr(
            cli,
            "apply_masthead",
            lambda cfg, **kw: captured.update(kw) or {"updated": 0, "ids": [], "masthead": ""},
        )
        cli._cmd_blog_masthead(
            cli._parse_args(["blog", "masthead", "--draft", "a", "--limit", "5"])
        )
        assert captured == {"draft_ids": ["a"], "limit": 5}

    def test_json_mode(self, monkeypatch, capsys):
        self._stub(monkeypatch, {"updated": 0, "ids": [], "masthead": ""})
        assert cli._cmd_blog_masthead(cli._parse_args(["blog", "masthead", "--json"])) == 0
        assert json.loads(capsys.readouterr().out)["updated"] == 0

    def test_unconfigured_returns_usage_error(self, monkeypatch, capsys):
        monkeypatch.setattr(cli, "_load_config", lambda args: {})

        def boom(cfg, **kw):
            raise ValueError("no default masthead: set publish.mastheads.default in config.yaml")

        monkeypatch.setattr(cli, "apply_masthead", boom)
        assert cli._cmd_blog_masthead(cli._parse_args(["blog", "masthead"])) == 2
        assert "no default masthead" in capsys.readouterr().err


class TestBlogBackfillDestinationsArgs:
    def test_flags_parse(self):
        args = cli._parse_args(["blog", "backfill-destinations", "--draft", "a", "--limit", "2"])
        assert args.draft == ["a"]
        assert args.limit == 2
        assert args.func is cli._cmd_blog_backfill_destinations

    def test_defaults(self):
        args = cli._parse_args(["blog", "backfill-destinations"])
        assert args.draft is None
        assert args.limit is None


class TestBlogBackfillDestinationsCommand:
    def _stub(self, monkeypatch, result):
        monkeypatch.setattr(cli, "_load_config", lambda args: {})
        monkeypatch.setattr(cli, "backfill_destinations", lambda cfg, **kw: result)

    def test_reports_backfilled(self, monkeypatch, capsys):
        self._stub(
            monkeypatch,
            {"updated": 2, "ids": ["a", "b"], "destinations": ["facebook", "linkedin"]},
        )
        assert (
            cli._cmd_blog_backfill_destinations(cli._parse_args(["blog", "backfill-destinations"]))
            == 0
        )
        out = capsys.readouterr().out
        assert "Backfilled 2 draft(s)" in out and "facebook" in out and "linkedin" in out

    def test_json_mode(self, monkeypatch, capsys):
        self._stub(monkeypatch, {"updated": 0, "ids": [], "destinations": ["facebook"]})
        assert (
            cli._cmd_blog_backfill_destinations(
                cli._parse_args(["blog", "backfill-destinations", "--json"])
            )
            == 0
        )
        assert json.loads(capsys.readouterr().out)["updated"] == 0

    def test_unconfigured_returns_usage_error(self, monkeypatch, capsys):
        monkeypatch.setattr(cli, "_load_config", lambda args: {})

        def boom(cfg, **kw):
            raise ValueError("unknown destination(s): mastodon")

        monkeypatch.setattr(cli, "backfill_destinations", boom)
        assert (
            cli._cmd_blog_backfill_destinations(cli._parse_args(["blog", "backfill-destinations"]))
            == 2
        )
        assert "unknown destination" in capsys.readouterr().err


class TestBlogScanCommand:
    def _stub(self, monkeypatch, result):
        monkeypatch.setattr(cli, "_load_config", lambda args: {})
        monkeypatch.setattr(cli, "scan_sources", lambda cfg, limit=None, source_names=None: result)

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


class TestBlogPublishArgs:
    def test_flags_parse(self):
        args = cli._parse_args(["blog", "publish", "--limit", "2", "--dry-run", "--json"])
        assert args.limit == 2
        assert args.dry_run is True
        assert args.json is True
        assert args.func is cli._cmd_blog_publish

    def test_defaults(self):
        args = cli._parse_args(["blog", "publish"])
        assert args.limit is None
        assert args.dry_run is False


class TestBlogPublishCommand:
    def _stub(self, monkeypatch, result):
        monkeypatch.setattr(cli, "_load_config", lambda args: {})
        monkeypatch.setattr(cli, "publish_scheduled", lambda cfg, **kw: result)

    def test_reports_posted(self, monkeypatch, capsys):
        self._stub(
            monkeypatch,
            {
                "posted": [
                    {
                        "id": "post-one",
                        "destination": "facebook",
                        "post_id": "123_9",
                        "permalink": "https://www.facebook.com/123_9",
                        "private": False,
                    }
                ],
                "skipped": [],
                "errors": [],
                "batch": 1,
                "queued": 1,
            },
        )
        assert cli._cmd_blog_publish(cli._parse_args(["blog", "publish"])) == 0
        out = capsys.readouterr().out
        assert "Posted 1 draft(s)" in out
        assert "https://www.facebook.com/123_9" in out

    def test_dry_run_verb(self, monkeypatch, capsys):
        self._stub(
            monkeypatch,
            {"posted": [], "skipped": [], "errors": [], "batch": 1, "queued": 0},
        )
        assert cli._cmd_blog_publish(cli._parse_args(["blog", "publish", "--dry-run"])) == 0
        assert "Would post 0 draft(s)" in capsys.readouterr().out

    def test_error_exits_1(self, monkeypatch, capsys):
        self._stub(
            monkeypatch,
            {
                "posted": [],
                "skipped": [],
                "errors": [{"id": "a", "error": "boom"}],
                "batch": 1,
                "queued": 1,
            },
        )
        assert cli._cmd_blog_publish(cli._parse_args(["blog", "publish"])) == 1
        assert "boom" in capsys.readouterr().err

    def test_disabled_returns_usage_error(self, monkeypatch, capsys):
        monkeypatch.setattr(cli, "_load_config", lambda args: {})

        def boom(cfg, **kw):
            raise ValueError("publishing is disabled")

        monkeypatch.setattr(cli, "publish_scheduled", boom)
        assert cli._cmd_blog_publish(cli._parse_args(["blog", "publish"])) == 2
        assert "publishing is disabled" in capsys.readouterr().err
