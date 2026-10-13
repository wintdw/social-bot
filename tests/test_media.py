"""The local media store: names, paths, and reading images for upload (no network)."""

from __future__ import annotations

import pytest

from social_bot import media
from social_bot.config import load_config


def _cfg(tmp_path):
    cfg = load_config("/nonexistent/config.yaml")
    cfg["review"]["dir"] = str(tmp_path / "review")
    return cfg


class TestNames:
    def test_accepts_flat_image_names(self):
        assert media.valid_name("post-one.jpg")
        assert media.valid_name("a_b-c.svg")
        assert media.valid_name("x.WEBP")

    def test_rejects_traversal_and_other_extensions(self):
        assert not media.valid_name("../secret.jpg")
        assert not media.valid_name("a/b.jpg")
        assert not media.valid_name("x.txt")
        assert not media.valid_name(".hidden.jpg")
        assert not media.valid_name("")

    def test_media_type_by_extension(self):
        assert media.media_type("a.jpg") == "image/jpeg"
        assert media.media_type("a.svg") == "image/svg+xml"
        assert media.media_type("a.unknown") == "application/octet-stream"

    def test_ext_for_sniffs_the_magic_bytes(self):
        assert media.ext_for(b"\xff\xd8\xffzz") == ".jpg"
        assert media.ext_for(b"\x89PNG\r\n\x1a\n") == ".png"
        assert media.ext_for(b"RIFF____WEBP") == ".webp"


class TestStore:
    def test_save_writes_the_file_and_returns_the_served_url(self, tmp_path):
        cfg = _cfg(tmp_path)
        url = media.save(cfg, "post-one", b"\xff\xd8\xffjpeg")
        assert url == "/images/post-one.jpg"
        assert (media.images_dir(cfg) / "post-one.jpg").read_bytes() == b"\xff\xd8\xffjpeg"

    def test_save_refuses_a_name_it_could_not_serve(self, tmp_path):
        with pytest.raises(media.MediaError):
            media.save(_cfg(tmp_path), "../escape", b"x")

    def test_load_reads_a_local_image(self, tmp_path):
        cfg = _cfg(tmp_path)
        url = media.save(cfg, "p", b"\xff\xd8\xffjpeg")
        data, name, content_type = media.load(cfg, url)
        assert data == b"\xff\xd8\xffjpeg"
        assert name == "p.jpg"
        assert content_type == "image/jpeg"

    def test_load_reports_a_missing_file(self, tmp_path):
        with pytest.raises(media.MediaError):
            media.load(_cfg(tmp_path), "/images/nope.jpg")

    def test_path_for_ignores_remote_urls_and_traversal(self, tmp_path):
        cfg = _cfg(tmp_path)
        assert media.path_for(cfg, "https://cdn/x.jpg") is None
        assert media.path_for(cfg, "/images/../a.jpg") is None
        assert media.path_for(cfg, "/images/a.jpg") == media.images_dir(cfg) / "a.jpg"


class TestRemoteDownload:
    def _responder(self, data, content_type, seen):
        class FakeResponse:
            headers = {"content-type": content_type}

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return data

        def fake_urlopen(request, timeout=None):
            seen["headers"] = dict(request.headers)
            return FakeResponse()

        return fake_urlopen

    def test_downloads_a_remote_image_without_a_key(self, tmp_path, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            media.urllib.request,
            "urlopen",
            self._responder(b"\x89PNG\r\n\x1a\n", "image/png", seen),
        )
        data, name, content_type = media.load(_cfg(tmp_path), "https://cdn.example/a.png")
        assert data.startswith(b"\x89PNG")
        assert name == "image.png"
        assert content_type == "image/png"
        assert "Authorization" not in seen["headers"]

    def test_an_empty_download_is_an_error(self, tmp_path, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            media.urllib.request,
            "urlopen",
            self._responder(b"", "image/jpeg", seen),
        )
        with pytest.raises(media.MediaError):
            media.load(_cfg(tmp_path), "https://cdn.example/empty.jpg")
