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

DOWNLOAD_TIMEOUT_SECONDS = 60.0
UA = "social-bot/0.1 (+media store)"


class MediaError(Exception):
    """A draft image could not be read from disk or downloaded."""


def images_dir(cfg: dict) -> pathlib.Path:
    """The local image folder (``<review.dir>/images``; bind-mounted)."""
    raw = str((cfg.get("review") or {}).get("dir") or "data/review")
    path = pathlib.Path(raw)
    return (path if path.is_absolute() else ROOT / path) / "images"


def valid_name(name: str) -> bool:
    return bool(NAME_RE.match(str(name or "")))


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
