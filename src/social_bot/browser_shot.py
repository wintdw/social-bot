"""HTML-to-PNG via a headless Chromium (stdlib only, no new dependency).

The renderer runs on the **host**, not in the container — the image is
python-slim with no browser. Resolution order for the binary:

1. ``SOCIAL_BOT_CHROMIUM`` env (explicit path),
2. a Playwright browser cache (``~/.cache/ms-playwright``),
3. ``chromium`` / ``chromium-browser`` / ``google-chrome`` on PATH.

A missing or failing browser is a ``ShotError`` — callers treat the PNG as
an enhancement (keep the SVG preview) and never let it fail the pipeline.
"""

from __future__ import annotations

import glob
import os
import pathlib
import shutil
import subprocess
import tempfile


class ShotError(Exception):
    """Chromium is missing or the screenshot failed."""


def find_chromium() -> str:
    """The Chromium binary path, or '' when none is available."""
    explicit = os.environ.get("SOCIAL_BOT_CHROMIUM", "").strip()
    if explicit and pathlib.Path(explicit).is_file():
        return explicit
    cache = sorted(
        glob.glob(str(pathlib.Path.home() / ".cache/ms-playwright/chromium-*/chrome-linux*/chrome"))
        + sorted(
            glob.glob(
                str(
                    pathlib.Path.home()
                    / ".cache/ms-playwright/chromium-*/chrome-linux*/headless_shell"
                )
            )
        )
    )
    if cache:
        return cache[-1]
    for name in ("chromium", "chromium-browser", "google-chrome"):
        found = shutil.which(name)
        if found:
            return found
    return ""


def html_to_png(
    page: str,
    dest: str | pathlib.Path,
    *,
    width: int = 1080,
    height: int = 1350,
    timeout: float = 120.0,
) -> pathlib.Path:
    """Screenshot one HTML document to ``dest``; return the path.

    Raises ``ShotError`` when no Chromium is available, it exits non-zero,
    or no file lands. The screenshot is the exact ``width``x``height`` CSS
    pixels of the page — the template owns the canvas size.
    """
    binary = find_chromium()
    if not binary:
        raise ShotError(
            "no Chromium found (SOCIAL_BOT_CHROMIUM, ~/.cache/ms-playwright, or chromium on PATH)"
        )
    dest = pathlib.Path(dest)
    with tempfile.NamedTemporaryFile(
        suffix=".html", delete=False, mode="w", encoding="utf-8"
    ) as tmp:
        tmp.write(page)
        src = tmp.name
    try:
        proc = subprocess.run(
            [
                binary,
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--hide-scrollbars",
                f"--window-size={width},{height}",
                f"--screenshot={dest}",
                f"file://{src}",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ShotError(f"chromium failed: {exc}") from exc
    finally:
        try:
            os.unlink(src)
        except OSError:
            pass
    if proc.returncode != 0 or not dest.is_file():
        raise ShotError(f"chromium exited {proc.returncode}: {(proc.stderr or '').strip()[:200]}")
    return dest


__all__ = ["ShotError", "find_chromium", "html_to_png"]
