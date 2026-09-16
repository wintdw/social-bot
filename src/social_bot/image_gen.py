"""AI image generation for drafts that arrive without a photo.

Uses Pollinations.ai. Two endpoints exist and they are not equivalent:

- ``https://gen.pollinations.ai/image`` (the modern gateway, the default) —
  real model choice (flux), no watermark, but requires a valid API key.
- ``https://image.pollinations.ai/prompt`` (legacy) — no key needed, but it
  ignores ``model`` (serves the older ``sana`` model) and watermarks every
  image.

The endpoint is ``image_gen.base_url`` in config; the key is
``image_gen.api_key`` (credentials.yaml). No extra dependency — urllib only,
like api.py.

The generated image URL is stored on the draft so the Facebook publisher posts
it as a photo instead of a link post. Generation is best-effort: if it fails,
the draft keeps whatever image it had and the pipeline continues — image gen is
an enhancement, not a gate.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request

_WS_RE = re.compile(r"\s+")

DEFAULT_BASE_URL = "https://gen.pollinations.ai/image"
# The pre-gateway prompt endpoint, still selectable via image_gen.base_url. Named
# here so a stored URL can be recognised as generated whichever one built it.
LEGACY_BASE_URL = "https://image.pollinations.ai/prompt"


class ImageGenError(Exception):
    """Image generation failed (network, provider, or bad response)."""


def _urlopen(url: str, timeout: float, headers: dict | None = None) -> bytes:
    request_headers = {"User-Agent": "social-bot/0.1 (+image gen)"}
    request_headers.update(headers or {})
    req = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def build_prompt(title: str, excerpt: str, style: str = "", image_prompt: str = "") -> str:
    """A tight, brand-safe prompt for one draft's image.

    ``image_prompt`` (when the rewriter supplied one) wins outright: it is a
    concrete visual concept written by something that understood the article.
    Falling back to the title/excerpt is a last resort — raw prose (especially
    Vietnamese) is not something the model can turn into a picture, which is
    why every auto-built image came out looking the same.

    ``style`` is the brand look: the draft's chosen treatment (which governs the
    medium, the composition *and* what to avoid — lettering included) followed by
    the shared ``image_gen.style_file`` palette. It leads the prompt so the
    treatment outranks the subject line in the model's reading.

    This only assembles the three parts. Every prohibition belongs to the
    treatment the rewriter picked, in ``docs/image-styles/<key>.md``, so a look
    is never fought by a rule written somewhere else.
    """
    subject = _WS_RE.sub(" ", image_prompt or "").strip()
    if not subject:
        title = _WS_RE.sub(" ", title or "").strip()
        excerpt = _WS_RE.sub(" ", excerpt or "").strip()[:120]
        subject = ". ".join(part for part in (title, excerpt) if part)
    if not subject:
        subject = "software engineering: foundations, structure and steady growth"

    parts = []
    if style and style.strip():
        parts.append(style.strip())
    # "Subject:" not "Illustrate this idea:" — the treatment chooses the medium
    # (sketch, still life, poster, schematic), so the subject line must not beg
    # for an illustration of its own.
    parts.append(f"Subject: {subject}")
    return ". ".join(parts)


def generate_image_url(
    prompt: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    width: int = 1080,
    height: int = 1350,
    model: str = "flux",
    timeout: float = 60.0,
    api_key: str = "",
) -> str:
    """Generate an image via Pollinations.ai and return its public URL.

    ``api_key`` goes in the ``Authorization`` header — never the URL, which is
    stored on the draft and published. The modern gateway requires it; the
    legacy endpoint ignores it. We read the image bytes to confirm it actually
    rendered.
    """
    encoded = urllib.parse.quote(prompt, safe="")
    url = (
        f"{base_url.rstrip('/')}/{encoded}?width={width}&height={height}&model={model}&nologo=true"
    )
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    try:
        data = _urlopen(url, timeout=timeout, headers=headers)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200].strip()
        raise ImageGenError(f"image generation failed: HTTP {exc.code} {detail}") from exc
    except Exception as exc:
        raise ImageGenError(f"image generation failed: {exc}") from exc
    if not data or len(data) < 1000:
        raise ImageGenError("image generation returned an empty or tiny response")
    return url


def generate_for_draft(
    title: str,
    excerpt: str,
    *,
    style: str = "",
    image_prompt: str = "",
    base_url: str = DEFAULT_BASE_URL,
    width: int = 1080,
    height: int = 1350,
    model: str = "flux",
    timeout: float = 60.0,
    api_key: str = "",
) -> str:
    """Build a prompt from the draft and generate an image URL.

    Returns the URL to use as the draft's ``image``. Raises ImageGenError on
    failure — callers decide whether to swallow or propagate.
    """
    prompt = build_prompt(title, excerpt, style=style, image_prompt=image_prompt)
    return generate_image_url(
        prompt,
        base_url=base_url,
        width=width,
        height=height,
        model=model,
        timeout=timeout,
        api_key=api_key,
    )


__all__ = [
    "DEFAULT_BASE_URL",
    "LEGACY_BASE_URL",
    "ImageGenError",
    "build_prompt",
    "generate_image_url",
    "generate_for_draft",
]
