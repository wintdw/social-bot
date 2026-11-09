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


class TestVideoNames:
    def test_accepts_flat_video_names(self):
        assert media.valid_video_name("post-one.mp4")
        assert media.valid_video_name("x.MOV")
        assert media.valid_video_name("a_b-c.webm")

    def test_rejects_traversal_and_other_extensions(self):
        assert not media.valid_video_name("../secret.mp4")
        assert not media.valid_video_name("a/b.mp4")
        assert not media.valid_video_name("x.png")
        assert not media.valid_video_name(".hidden.mp4")
        assert not media.valid_video_name("")

    def test_media_type_by_extension(self):
        assert media.video_media_type("a.mp4") == "video/mp4"
        assert media.video_media_type("a.webm") == "video/webm"
        assert media.video_media_type("a.MOV") == "video/quicktime"
        assert media.video_media_type("a.unknown") == "application/octet-stream"

    def test_video_ext_for_sniffs_the_magic_bytes(self):
        assert media.video_ext_for(b"\x00\x00\x00\x18ftypisom____") == ".mp4"
        assert media.video_ext_for(b"\x00\x00\x00\x14ftypqt  ____") == ".mov"
        assert media.video_ext_for(b"\x1a\x45\xdf\xa3____") == ".webm"
        # Unknown bytes default to mp4: an attached clip is always video, and
        # the store still needs a servable extension.
        assert media.video_ext_for(b"????") == ".mp4"


class TestVideoStore:
    def test_save_writes_the_file_and_returns_the_served_url(self, tmp_path):
        cfg = _cfg(tmp_path)
        url = media.save_video(cfg, "post-one", b"\x00\x00\x00\x18ftypisom")
        assert url == "/videos/post-one.mp4"
        assert (
            (media.videos_dir(cfg) / "post-one.mp4")
            .read_bytes()
            .startswith(b"\x00\x00\x00\x18ftyp")
        )

    def test_videos_live_beside_images_not_inside_them(self, tmp_path):
        cfg = _cfg(tmp_path)
        media.save_video(cfg, "p", b"\x1a\x45\xdf\xa3")
        assert media.videos_dir(cfg) != media.images_dir(cfg)
        assert (media.videos_dir(cfg) / "p.webm").is_file()

    def test_save_refuses_a_name_it_could_not_serve(self, tmp_path):
        with pytest.raises(media.MediaError):
            media.save_video(_cfg(tmp_path), "../escape", b"x")

    def test_load_reads_a_local_video(self, tmp_path):
        cfg = _cfg(tmp_path)
        url = media.save_video(cfg, "p", b"\x00\x00\x00\x18ftypisom")
        data, name = media.load_video(cfg, url)
        assert data.startswith(b"\x00\x00\x00\x18ftyp")
        assert name == "p.mp4"

    def test_load_refuses_a_remote_url(self, tmp_path):
        # A video is attached from a rendered file, never fetched from a source
        # page, so there is no download path to fall back to.
        with pytest.raises(media.MediaError, match="locally stored"):
            media.load_video(_cfg(tmp_path), "https://cdn.example/x.mp4")

    def test_load_reports_a_missing_file(self, tmp_path):
        with pytest.raises(media.MediaError):
            media.load_video(_cfg(tmp_path), "/videos/nope.mp4")

    def test_video_path_for_ignores_traversal(self, tmp_path):
        cfg = _cfg(tmp_path)
        assert media.video_path_for(cfg, "/videos/../a.mp4") is None
        assert media.video_path_for(cfg, "/images/a.mp4") is None
        assert media.video_path_for(cfg, "/videos/a.mp4") == media.videos_dir(cfg) / "a.mp4"


def test_served_url_versions_a_local_file(tmp_path):
    cfg = {"review": {"dir": str(tmp_path)}}
    (tmp_path / "videos").mkdir()
    clip = tmp_path / "videos" / "draft-one.mp4"
    clip.write_bytes(b"x" * 32)

    url = media.served_url(cfg, "/videos/draft-one.mp4")
    assert url.startswith("/videos/draft-one.mp4?v=")
    assert url.endswith("-32")


def test_served_url_leaves_remote_and_missing_alone(tmp_path):
    cfg = {"review": {"dir": str(tmp_path)}}
    (tmp_path / "images").mkdir()

    remote = "https://example.com/cover.png"
    assert media.served_url(cfg, remote) == remote
    # a stored URL whose file is gone (or never existed) is passed through
    assert media.served_url(cfg, "/images/nope.png") == "/images/nope.png"


def test_served_url_changes_when_the_bytes_change(tmp_path):
    cfg = {"review": {"dir": str(tmp_path)}}
    (tmp_path / "videos").mkdir()
    clip = tmp_path / "videos" / "draft-one.mp4"
    clip.write_bytes(b"a" * 10)
    first = media.served_url(cfg, "/videos/draft-one.mp4")
    clip.write_bytes(b"b" * 10)
    assert media.served_url(cfg, "/videos/draft-one.mp4") != first
