"""Config loading: built-in DEFAULTS deep-merged with the project config.yaml."""

from __future__ import annotations

import copy
import os
import pathlib
from typing import Any

import yaml

# Project root = <src/social_bot>/.. = parent of the src layout. Override with
# SOCIAL_BOT_HOME when running from a non-editable install (e.g. /app in Docker).
ROOT = pathlib.Path(
    os.environ.get("SOCIAL_BOT_HOME") or pathlib.Path(__file__).resolve().parents[2]
)
CONFIG_PATH = ROOT / "config.yaml"

# Secrets live here, never in the committed config.yaml. The file sits next to
# whichever config.yaml is in use, so `--config /elsewhere/config.yaml` picks up
# /elsewhere/credentials.yaml. Template: credentials.example.yaml.
CREDENTIALS_NAME = "credentials.yaml"

# Token resolution order: --token flag > SOCIAL_BOT_TOKEN env > graph.token
# (which credentials.yaml populates).
TOKEN_ENV = "SOCIAL_BOT_TOKEN"

DEFAULTS: dict[str, Any] = {
    "graph": {
        "base_url": "https://graph.facebook.com",
        "api_version": "v26.0",
        "timeout_seconds": 30.0,
        "page_id": "",
        "token": "",  # populated by credentials.yaml (git-ignored), not config.yaml
    },
    "feed": {
        "limit": 10,  # default number of feed posts shown by `feed`
        "dir": "data/feed",  # cache written by `refresh` and served by `serve`
    },
    # Source feeds the content pipeline scans for new items. Add more entries
    # to watch more sites; `type` is `sitemap`, `rss`, or `index` (a listing
    # page's JSON-LD ItemList, for sites with neither feed nor sitemap posts).
    "sources": [
        {
            "name": "atento-blog",
            "type": "index",
            "url": "https://atento.vn/blog",
            "path_prefix": "/blog/",
            "lang": "vi",
        },
    ],
    # Review queue (/review): queue.json holds the drafts awaiting review, and
    # seen.json dedupes scanned source items across runs.
    "review": {
        "dir": "data/review",
        "queue_name": "queue.json",
        "seen_name": "seen.json",
    },
    # Publishing is human-gated: destinations are what a review-page approval
    # may post to. `dna_file` is an optional path to your brand-voice brief,
    # surfaced to the rewriter through GET /api/drafts. `dir` + `log_name` are
    # the append-only audit log shown on /publish.
    "publish": {
        "enabled": True,
        "destinations": ["facebook"],
        "max_per_day": 10,
        # Timed posting: a list of container-local "HH:MM" slots. The serve
        # scheduler posts *human-approved* drafts at each slot (oldest first,
        # up to `post_per_slot`), never approving anything itself. Empty (the
        # default) disables timed posting — approval then only posts on demand.
        # An entry may also be a window "HH:MM-HH:MM": the scheduler then fires
        # once that day at a random time inside it (stable per day across
        # restarts), which reads less mechanically than a fixed slot.
        "post_at": [],
        "post_per_slot": 1,
        # Minimum days between *public* posts (0 = no minimum). Enforced by
        # publish_draft alongside the daily cap, so it paces the scheduler and a
        # manual "Post now" alike; private (unpublished) sends don't count.
        "interval_days": 0,
        # Real sends but unpublished (visible to page admins only): the Graph
        # API's way to test posting without going public. Private sends are
        # audited but don't consume drafts or the daily cap.
        "private": False,
        # Series masthead on line 1 of every caption (see the DNA §4.5). The
        # label is a content judgment, not a source default: the rewriter picks
        # one of `choices` per post (worth learning vs just information);
        # `default` is only the fallback the pipeline prepends when it doesn't.
        # Empty `choices` + `default` disables the masthead.
        "mastheads": {"choices": [], "default": ""},
        "dna_file": "",
        "dir": "data/publish",
        "log_name": "published.jsonl",
    },
    # Scanning: how often `serve` looks for new source items, and how it fetches
    # them. `scan_at` is a list of container-local "HH:MM" slots.
    "blog": {
        "scan_at": ["06:00"],
        "timeout_seconds": 30.0,
        "retries": 2,
        "max_scan": 12,
        "excerpt_chars": 240,
        "enrich": True,  # fetch each new post page for title/excerpt/image
        "user_agent": "social-bot/0.1 (+content pipeline)",
    },
    # AI image generation for drafts (Pollinations.ai by default). Off by
    # default: it makes outbound calls and slows a scan, so opt in per project.
    # `overwrite` true replaces a source image with a generated one; false (the
    # default) only fills drafts that have no image, keeping a source post's
    # own cover. `base_url` is the prompt endpoint; the
    # default is the modern gateway (clean flux output, needs image_gen.api_key
    # in credentials.yaml). The legacy `https://image.pollinations.ai/prompt`
    # needs no key but is watermarked and locked to the older `sana` model.
    # `style_file` is a short brand-look brief prepended to every prompt.
    # `model` must be one the endpoint serves: the gen.pollinations.ai gateway
    # takes provider-qualified names (e.g. "openai/gpt-image-1-mini"); the
    # legacy endpoint ignores it entirely. The default follows the negative
    # instructions in the style brief far better than flux.1-schnell.
    "image_gen": {
        "enabled": False,
        "provider": "pollinations",
        "base_url": "https://gen.pollinations.ai/image",
        "style_file": "",
        "overwrite": False,
        "model": "openai/gpt-image-1-mini",
        "width": 1080,
        "height": 1350,
        "timeout_seconds": 60.0,
        "api_key": "",  # populated by credentials.yaml, never config.yaml
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into a copy of base."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _read_yaml(path: pathlib.Path) -> dict:
    """Decode a YAML file into a dict ({} if the document is empty)."""
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_config(path: str | os.PathLike[str] | None = None) -> dict:
    """Load config.yaml from the project root (or an explicit path) over DEFAULTS.

    A ``credentials.yaml`` sitting next to the config file is merged last, so
    the secret token stays out of the committed config.
    """
    source = pathlib.Path(path) if path else CONFIG_PATH
    cfg = _deep_merge(DEFAULTS, {})
    if source.exists():
        cfg = _deep_merge(cfg, _read_yaml(source))
    credentials = source.with_name(CREDENTIALS_NAME)
    if credentials.exists():
        cfg = _deep_merge(cfg, _read_yaml(credentials))
    return cfg


def resolve_token(token: str | None, cfg: dict) -> str:
    """The access token from --token, the environment, or the credentials file;
    '' if absent."""
    token = (
        token
        or os.environ.get(TOKEN_ENV, "")
        or str(cfg.get("graph", {}).get("token", ""))
    )
    return token.strip()


def _hhmm_minutes(value: str, field: str) -> int:
    """Parse "HH:MM" into minutes since midnight; raise ValueError on anything else."""
    hh, sep, mm = str(value).partition(":")
    if not (sep and hh.isdigit() and mm.isdigit()):
        raise ValueError(f"config: {field} has invalid time {value!r}")
    hour, minute = int(hh), int(mm)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"config: {field} has invalid time {value!r}")
    return hour * 60 + minute


def validate(cfg: dict) -> None:
    """Raise ValueError on obviously unusable configuration."""
    graph = cfg.get("graph", {})
    if not str(graph.get("api_version", "")).startswith("v"):
        raise ValueError("config: graph.api_version must look like 'v26.0'")
    if not str(graph.get("base_url", "")).startswith("https://"):
        raise ValueError("config: graph.base_url must be an https URL")
    if graph.get("timeout_seconds", 30) <= 0:
        raise ValueError("config: graph.timeout_seconds must be positive")
    if cfg.get("feed", {}).get("limit", 10) < 1:
        raise ValueError("config: feed.limit must be >= 1")

    sources = cfg.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("config: sources must be a non-empty list")
    for source in sources:
        if not isinstance(source, dict) or not source.get("name"):
            raise ValueError("config: each source needs a name")
        if not str(source.get("url", "")).startswith("https://"):
            raise ValueError(f"config: source {source.get('name')!r} url must be an https URL")
        if source.get("type") not in ("sitemap", "rss", "index"):
            raise ValueError(
                f"config: source {source.get('name')!r} type must be 'sitemap', 'rss', or 'index'"
            )
        if source.get("type") in ("sitemap", "index") and not source.get("path_prefix"):
            raise ValueError(
                f"config: source {source.get('name')!r} needs path_prefix"
            )

    publish = cfg.get("publish", {})
    destinations = publish.get("destinations")
    if not isinstance(destinations, list) or not destinations:
        raise ValueError("config: publish.destinations must be a non-empty list")
    for destination in destinations:
        if destination not in ("facebook", "linkedin"):
            raise ValueError(f"config: unknown publish destination {destination!r}")
    if int(publish.get("max_per_day", 10)) < 1:
        raise ValueError("config: publish.max_per_day must be >= 1")
    if int(publish.get("post_per_slot", 1)) < 1:
        raise ValueError("config: publish.post_per_slot must be >= 1")
    if int(publish.get("interval_days", 0)) < 0:
        raise ValueError("config: publish.interval_days must be >= 0")
    post_at = publish.get("post_at", [])
    if not isinstance(post_at, list):
        raise ValueError("config: publish.post_at must be a list of HH:MM")
    for slot in post_at:
        text = str(slot)
        if "-" in text:
            start, _, end = text.partition("-")
            if _hhmm_minutes(start, "publish.post_at") >= _hhmm_minutes(
                end, "publish.post_at"
            ):
                raise ValueError(
                    f"config: publish.post_at window {slot!r} must start before it ends"
                )
        else:
            _hhmm_minutes(text, "publish.post_at")

    blog = cfg.get("blog", {})
    if float(blog.get("timeout_seconds", 30)) <= 0:
        raise ValueError("config: blog.timeout_seconds must be positive")
    if int(blog.get("max_scan", 12)) < 1:
        raise ValueError("config: blog.max_scan must be >= 1")
    scan_at = blog.get("scan_at")
    if not isinstance(scan_at, list) or not scan_at:
        raise ValueError("config: blog.scan_at must be a non-empty list of HH:MM")
    for slot in scan_at:
        _hhmm_minutes(str(slot), "blog.scan_at")

    image_gen = cfg.get("image_gen", {})
    if image_gen.get("provider") not in ("pollinations",):
        raise ValueError(
            f"config: unknown image_gen.provider {image_gen.get('provider')!r}"
        )
    if not str(image_gen.get("base_url", "")).startswith("https://"):
        raise ValueError("config: image_gen.base_url must be an https URL")
    if float(image_gen.get("timeout_seconds", 60)) <= 0:
        raise ValueError("config: image_gen.timeout_seconds must be positive")
    if int(image_gen.get("width", 1080)) < 1 or int(image_gen.get("height", 1350)) < 1:
        raise ValueError("config: image_gen.width/height must be >= 1")
