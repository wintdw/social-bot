"""Locally stored post media — served by the app, uploaded bytes for posting.

Photos used to be published by handing Graph a remote URL and letting Graph
fetch it. That only works while the host serves the image anonymously, so
images are stored locally — the folder that holds the drawn plates,
which the app serves at ``/images/`` — and the publisher uploads the bytes
instead of a URL.

Stdlib only, and deliberately imports neither ``draft_pipeline`` nor
``destinations``: both import this, so it stays the leaf module they can share.
"""

from __future__ import annotations

import pathlib
import re
import urllib.error
import urllib.request

from .config import ROOT

# The URL prefix the app serves these files under.
PREFIX = "/images/"

# One flat name, ``<draft id>.<ext>``, validated so a request can never escape
# the images directory. ``.png`` is a drawn plate; the rest are copied down
# from a source cover.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.(svg|jpg|jpeg|png|webp)$", re.IGNORECASE)

MEDIA_TYPES = {
    ".svg": "image/svg+xml",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

# Videos are a separate flat store: one ``<draft id>.<ext>`` per draft, served
# under its own prefix. They are much larger than plates, so they are not mixed
# into the image folder (and never in git — ``data/`` is ignored).
VIDEO_PREFIX = "/videos/"

VIDEO_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.(mp4|webm|mov)$", re.IGNORECASE)

VIDEO_TYPES = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
}

# The longest a single publish can take: a video upload. `serve` drains an
# in-flight publish on shutdown, so this also bounds that wait (web.py).
UPLOAD_TIMEOUT_SECONDS = 300.0

DOWNLOAD_TIMEOUT_SECONDS = 60.0
UA = "social-bot/0.1 (+media store)"


class MediaError(Exception):
    """A draft image could not be read from disk or downloaded."""


def images_dir(cfg: dict) -> pathlib.Path:
    """The local image folder (``<review.dir>/images``; bind-mounted)."""
    raw = str((cfg.get("review") or {}).get("dir") or "data/review")
    path = pathlib.Path(raw)
    return (path if path.is_absolute() else ROOT / path) / "images"


def videos_dir(cfg: dict) -> pathlib.Path:
    """The local video folder (``<review.dir>/videos``; bind-mounted)."""
    raw = str((cfg.get("review") or {}).get("dir") or "data/review")
    path = pathlib.Path(raw)
    return (path if path.is_absolute() else ROOT / path) / "videos"


def valid_name(name: str) -> bool:
    return bool(NAME_RE.match(str(name or "")))


def served_url(cfg: dict, url: str) -> str:
    """A stored media URL as the browser should request it, versioned by file.

    A plate or a clip is replaced *in place* (``blog attach-video``, a redrawn
    image), so its URL never changes and the browser keeps serving the copy it
    already cached — the operator sees the old file until a hard reload. The
    ``?v=`` is the file's mtime and size: cheap, and it changes exactly when the
    bytes change. Anything that is not a local file (a source's own remote
    cover) is returned untouched.
    """
    text = str(url or "")
    if not text or "?" in text or "#" in text:
        return text
    path: pathlib.Path | None = None
    if text.startswith(VIDEO_PREFIX):
        path = video_path_for(cfg, text)
    elif text.startswith(PREFIX) and valid_name(text[len(PREFIX) :]):
        path = images_dir(cfg) / text[len(PREFIX) :]
    if path is None:
        return text
    try:
        stat = path.stat()
    except OSError:
        return text
    return f"{text}?v={stat.st_mtime_ns}-{stat.st_size}"


def media_type(name: str) -> str:
    return MEDIA_TYPES.get(pathlib.Path(str(name)).suffix.lower(), "application/octet-stream")


def ext_for(data: bytes) -> str:
    """The file extension for some image bytes (sniffed from magic bytes)."""
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ".jpg"


def is_local(url: str) -> bool:
    """True for an image the app serves itself (vs. a remote source cover)."""
    return str(url or "").startswith(PREFIX)


def path_for(cfg: dict, url: str) -> pathlib.Path | None:
    """The file behind a ``/images/<name>`` URL, or None if it isn't one."""
    if not is_local(url):
        return None
    name = str(url)[len(PREFIX) :]
    return images_dir(cfg) / name if valid_name(name) else None


def save(cfg: dict, draft_id: str, data: bytes) -> str:
    """Store image bytes for a draft; return the served ``/images/<name>`` URL."""
    name = f"{draft_id}{ext_for(data)}"
    if not valid_name(name):
        raise MediaError(f"cannot store an image for draft id {draft_id!r}")
    directory = images_dir(cfg)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(data)
    return f"{PREFIX}{name}"


def load(
    cfg: dict, url: str, *, timeout: float = DOWNLOAD_TIMEOUT_SECONDS
) -> tuple[bytes, str, str]:
    """``(bytes, filename, content_type)`` for a draft's image URL.

    A local ``/images/<name>`` is read from disk. Anything else — the source
    post's own cover — is downloaded here. Either way the publisher uploads
    bytes and never depends on Graph reaching a third-party host.
    """
    path = path_for(cfg, url)
    if path is not None:
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise MediaError(f"cannot read {path.name}: {exc}") from None
        return data, path.name, media_type(path.name)

    request = urllib.request.Request(str(url), headers={"User-Agent": UA, "Accept": "image/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
            content_type = str(response.headers.get("content-type") or "").split(";")[0].strip()
    except urllib.error.HTTPError as exc:
        raise MediaError(f"downloading {url} failed: HTTP {exc.code}") from None
    except (urllib.error.URLError, ValueError) as exc:
        raise MediaError(f"downloading {url} failed: {exc}") from None
    if not data:
        raise MediaError(f"downloading {url} returned nothing")
    return data, f"image{_ext_for_type(content_type, data)}", content_type or media_type("x.jpg")


def _ext_for_type(content_type: str, data: bytes) -> str:
    by_type = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    return by_type.get(content_type) or ext_for(data)


# -- videos ---------------------------------------------------------------


def valid_video_name(name: str) -> bool:
    return bool(VIDEO_NAME_RE.match(str(name or "")))


def video_media_type(name: str) -> str:
    return VIDEO_TYPES.get(pathlib.Path(str(name)).suffix.lower(), "application/octet-stream")


def video_ext_for(data: bytes) -> str:
    """The file extension for some video bytes (sniffed from magic bytes)."""
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return ".mov" if data[8:12] in {b"qt  "} else ".mp4"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return ".webm"
    return ".mp4"


def is_local_video(url: str) -> bool:
    """True for a video the app serves itself (the only kind it will upload)."""
    return str(url or "").startswith(VIDEO_PREFIX)


def video_path_for(cfg: dict, url: str) -> pathlib.Path | None:
    """The file behind a ``/videos/<name>`` URL, or None if it isn't one."""
    if not is_local_video(url):
        return None
    name = str(url)[len(VIDEO_PREFIX) :]
    return videos_dir(cfg) / name if valid_video_name(name) else None


def save_video(cfg: dict, draft_id: str, data: bytes) -> str:
    """Store video bytes for a draft; return the served ``/videos/<name>`` URL."""
    name = f"{draft_id}{video_ext_for(data)}"
    if not valid_video_name(name):
        raise MediaError(f"cannot store a video for draft id {draft_id!r}")
    directory = videos_dir(cfg)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(data)
    return f"{VIDEO_PREFIX}{name}"


def load_video(cfg: dict, url: str) -> tuple[bytes, str]:
    """``(bytes, filename)`` for a draft's video URL.

    Only a locally stored video is accepted: a video is attached from a file the
    operator rendered, never fetched from a source article, so there is no remote
    case to download (unlike a cover image).
    """
    path = video_path_for(cfg, url)
    if path is None:
        raise MediaError(f"not a locally stored video: {url!r}")
    try:
        return path.read_bytes(), path.name
    except OSError as exc:
        raise MediaError(f"cannot read {path.name}: {exc}") from None
