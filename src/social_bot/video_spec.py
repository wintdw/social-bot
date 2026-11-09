"""Video spec check before a clip is attached to a draft (stdlib + ffprobe).

A Reel has hard platform limits, and a file that misses them is rejected by
Graph (or distributed badly) after the operator has already approved it. The
check runs at **attach** time, where fixing it is cheap.

``ffprobe`` runs on the **host**, alongside the renderer, not in the container.
A missing binary never blocks an attach — the file is still accepted, with a
warning — because the probe is an enhancement, never a gate that cannot open.

Rules mirror Meta's Reels publishing requirements:
3–90s, 24–60fps, at least 540px on the short side, and an aspect ratio between
9:16 and 16:9.
"""

from __future__ import annotations

import json
import shutil
import subprocess

# Meta's Reels limits (video-api/guides/reels-publishing).
REEL_MIN_SECONDS = 3.0
REEL_MAX_SECONDS = 90.0
REEL_MIN_FPS = 23.9  # 23.976 is the real-world "24"
REEL_MAX_FPS = 60.0
REEL_MIN_SHORT_SIDE = 540
REEL_MIN_ASPECT = 9 / 16
REEL_MAX_ASPECT = 16 / 9
REEL_CODECS = {"h264", "hevc", "vp9", "av1"}


class SpecError(Exception):
    """ffprobe is missing, or the file could not be read as a video."""


def find_ffprobe() -> str:
    """The ffprobe binary path, or '' when none is available."""
    return shutil.which("ffprobe") or ""


def probe(path: str, *, timeout: float = 30.0) -> dict:
    """The video stream's own numbers, as ``{width, height, duration, fps, codec}``.

    Raises ``SpecError`` when ffprobe is missing or the file has no video
    stream. Callers treat a missing binary as "cannot check", not "invalid".
    """
    binary = find_ffprobe()
    if not binary:
        raise SpecError("ffprobe not found")
    try:
        proc = subprocess.run(
            [
                binary,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                path,
            ],
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SpecError(f"ffprobe failed: {exc}") from None
    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip()
        raise SpecError(detail or "ffprobe could not read the file")
    try:
        payload = json.loads(proc.stdout.decode(errors="replace"))
    except ValueError as exc:
        raise SpecError(f"ffprobe returned non-JSON: {exc}") from None

    stream = next(
        (s for s in payload.get("streams", []) if s.get("codec_type") == "video"),
        None,
    )
    if stream is None:
        raise SpecError("no video stream in the file")
    duration = _float(stream.get("duration")) or _float(
        (payload.get("format") or {}).get("duration")
    )
    return {
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "duration": duration,
        "fps": _fps(stream.get("avg_frame_rate") or stream.get("r_frame_rate")),
        "codec": str(stream.get("codec_name") or ""),
    }


def _float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fps(value) -> float:
    text = str(value or "")
    if "/" in text:
        num, _, den = text.partition("/")
        try:
            return float(num) / float(den) if float(den) else 0.0
        except ValueError:
            return 0.0
    return _float(text)


def problems(spec: dict) -> list[str]:
    """Human-readable reasons this clip will not publish as a Reel; empty = ok."""
    found: list[str] = []
    duration = float(spec.get("duration") or 0)
    if duration < REEL_MIN_SECONDS or duration > REEL_MAX_SECONDS:
        found.append(f"duration {duration:.1f}s is outside 3–90s")
    fps = float(spec.get("fps") or 0)
    if fps and (fps < REEL_MIN_FPS or fps > REEL_MAX_FPS):
        found.append(f"frame rate {fps:.2f}fps is outside 24–60fps")
    width, height = int(spec.get("width") or 0), int(spec.get("height") or 0)
    if width and height:
        if min(width, height) < REEL_MIN_SHORT_SIDE:
            found.append(f"{width}x{height} is below the 540px minimum on the short side")
        aspect = width / height
        if not (REEL_MIN_ASPECT <= aspect <= REEL_MAX_ASPECT):
            found.append(f"{width}x{height} is outside the 9:16–16:9 range")
    codec = str(spec.get("codec") or "")
    if codec and codec not in REEL_CODECS:
        found.append(f"codec {codec!r} is not one of h264/hevc/vp9/av1")
    return found


def summary(spec: dict) -> str:
    """One line for the operator, e.g. ``1080x1920, 6.0s, 30.00fps, h264``."""
    return (
        f"{spec.get('width')}x{spec.get('height')}, "
        f"{float(spec.get('duration') or 0):.1f}s, "
        f"{float(spec.get('fps') or 0):.2f}fps, {spec.get('codec') or '?'}"
    )
