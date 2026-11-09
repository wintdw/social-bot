"""The Reels spec check: parsing, limits, and the missing-ffprobe case (no network)."""

from __future__ import annotations

import json

import pytest

from social_bot import video_spec


def _spec(**kw):
    base = {"width": 1080, "height": 1920, "duration": 6.0, "fps": 30.0, "codec": "h264"}
    base.update(kw)
    return base


class TestProblems:
    def test_a_vertical_six_second_clip_is_clean(self):
        assert video_spec.problems(_spec()) == []

    def test_a_landscape_clip_is_allowed(self):
        assert video_spec.problems(_spec(width=1920, height=1080)) == []

    def test_short_duration_is_rejected(self):
        assert "3–90s" in " ".join(video_spec.problems(_spec(duration=1.5)))

    def test_long_duration_is_rejected(self):
        assert "3–90s" in " ".join(video_spec.problems(_spec(duration=120)))

    def test_low_frame_rate_is_rejected(self):
        assert "24–60fps" in " ".join(video_spec.problems(_spec(fps=15)))

    def test_high_frame_rate_is_rejected(self):
        assert "24–60fps" in " ".join(video_spec.problems(_spec(fps=120)))

    def test_ntsc_24_is_accepted(self):
        assert video_spec.problems(_spec(fps=24000 / 1001)) == []

    def test_small_short_side_is_rejected(self):
        assert "540" in " ".join(video_spec.problems(_spec(width=480, height=854)))

    def test_extreme_aspect_is_rejected(self):
        assert "9:16" in " ".join(video_spec.problems(_spec(width=1080, height=3000)))

    def test_unknown_codec_is_rejected(self):
        assert "codec" in " ".join(video_spec.problems(_spec(codec="prores")))

    def test_summary_is_one_readable_line(self):
        assert video_spec.summary(_spec()) == "1080x1920, 6.0s, 30.00fps, h264"


class TestProbe:
    def test_parses_the_first_video_stream(self, monkeypatch):
        payload = {
            "streams": [
                {"codec_type": "audio", "codec_name": "aac"},
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1080,
                    "height": 1920,
                    "avg_frame_rate": "30000/1001",
                    "duration": "6.04",
                },
            ],
            "format": {"duration": "6.0"},
        }

        class Proc:
            returncode = 0
            stdout = json.dumps(payload).encode()
            stderr = b""

        monkeypatch.setattr(video_spec, "find_ffprobe", lambda: "/usr/bin/ffprobe")
        monkeypatch.setattr(video_spec.subprocess, "run", lambda *a, **kw: Proc())
        spec = video_spec.probe("clip.mp4")
        assert spec["width"] == 1080
        assert spec["height"] == 1920
        assert spec["codec"] == "h264"
        assert round(spec["fps"], 2) == 29.97
        assert spec["duration"] == 6.04

    def test_missing_ffprobe_raises_spec_error(self, monkeypatch):
        monkeypatch.setattr(video_spec, "find_ffprobe", lambda: "")
        with pytest.raises(video_spec.SpecError, match="ffprobe not found"):
            video_spec.probe("clip.mp4")

    def test_a_file_without_a_video_stream_is_an_error(self, monkeypatch):
        class Proc:
            returncode = 0
            stdout = b'{"streams":[{"codec_type":"audio"}],"format":{}}'
            stderr = b""

        monkeypatch.setattr(video_spec, "find_ffprobe", lambda: "ffprobe")
        monkeypatch.setattr(video_spec.subprocess, "run", lambda *a, **kw: Proc())
        with pytest.raises(video_spec.SpecError, match="no video stream"):
            video_spec.probe("clip.mp4")

    def test_a_failed_probe_surfaces_ffprobe_stderr(self, monkeypatch):
        class Proc:
            returncode = 1
            stdout = b""
            stderr = b"Invalid data found"

        monkeypatch.setattr(video_spec, "find_ffprobe", lambda: "ffprobe")
        monkeypatch.setattr(video_spec.subprocess, "run", lambda *a, **kw: Proc())
        with pytest.raises(video_spec.SpecError, match="Invalid data"):
            video_spec.probe("clip.mp4")
