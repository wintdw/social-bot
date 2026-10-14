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

# Token resolution order (per destination): --token flag > SOCIAL_BOT_<NAME>_TOKEN
# env > SOCIAL_BOT_TOKEN env (global fallback) > destinations.<name>.token
# (which credentials.yaml populates).
TOKEN_ENV = "SOCIAL_BOT_TOKEN"

DEFAULTS: dict[str, Any] = {
    # One block per destination the factory can publish to — connection settings
    # only. `publish.destinations` below selects where new drafts are routed.
    # Secrets (tokens) live in credentials.yaml, never in the committed config.
    "destinations": {
        "facebook": {
            "base_url": "https://graph.facebook.com",
            "api_version": "v26.0",
            "timeout_seconds": 30.0,
            "account_id": "",  # the Page id
            "token": "",  # populated by credentials.yaml (git-ignored)
        },
        "linkedin": {
            # linkin-bot (a sibling service) owns the LinkedIn OAuth token and
            # talks to LinkedIn; this app posts through its POST /post gateway.
            # A draft with a source URL sends it as the `comment` field too: the
            # gateway types it into the new post right after publishing, as the
            # same Page (the caption's CTA points at the comment).
            "base_url": "http://host.docker.internal:8082",
            "timeout_seconds": 30.0,
            "visibility": "PUBLIC",  # PUBLIC | CONNECTIONS
        },
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
    # may post to. `dir` + `log_name` are the append-only audit log shown on
    # /publish.
    "publish": {
        "enabled": True,
        "destinations": ["facebook", "linkedin"],
        # Timed posting: a list of container-local "HH:MM" slots. The serve
        # scheduler posts *human-approved* drafts at each slot (oldest first,
        # up to `post_per_slot`), never approving anything itself. Empty (the
        # default) disables timed posting — approval then only posts on demand.
        # An entry may also be a window "HH:MM-HH:MM": the scheduler then fires
        # once that day at a random time inside it (stable per day across
        # restarts), which reads less mechanically than a fixed slot.
        "post_at": [],
        # Per-destination slot overrides, e.g. {"linkedin": ["14:00-14:30"]}. A
        # destination not listed here uses `post_at`. Each destination has its own
        # slots and its own interval_days pacing.
        "destination_post_at": {},
        "post_per_slot": 1,
        # Minimum days between *scheduled* public posts (0 = no minimum).
        # Enforced by publish_draft on the unattended drain, so it paces the
        # poster (post_at slots, blog publish, Post approved now); private
        # (unpublished) sends and manual sends (a draft's Post now, a /queue
        # platform button) are outside it entirely — they are never refused and
        # never counted. 1 = at most one scheduled post per day.
        "interval_days": 0,
        # Real sends but unpublished (visible to page admins only): the Graph
        # API's way to test posting without going public. Private sends are
        # audited but don't consume drafts or count toward interval_days.
        "private": False,
        # Series masthead on line 1 of every caption. The label is a content judgment, not a source default: you pick one of
        # `choices` per post (worth learning vs just information); `default` is
        # what `blog masthead` backfills onto captions that have none.
        # Empty `choices` + `default` disables the masthead.
        "mastheads": {"choices": [], "default": ""},
        # How many recently-written captions the caption lint compares a new one
        # against, so a repeated opener/closer/vocabulary across posts is flagged.
        # 0 disables the comparison.
        "recent_captions": 12,
        "dir": "data/publish",
        "log_name": "published.jsonl",
    },
    # Scanning: how often `serve` looks for new source items, and how it fetches
    # them. `scan_at` is a list of container-local "HH:MM" slots. `max_age_days`
    # drops items published more than that many days ago (0 = no limit): a feed
    # that exposes more entries than one scan takes (martinfowler's Atom, say)
    # is otherwise walked back one `max_scan` batch per run.
    "blog": {
        "scan_at": ["06:00"],
        "timeout_seconds": 30.0,
        "retries": 2,
        "max_scan": 12,
        "max_age_days": 0,
        "excerpt_chars": 240,
        "enrich": True,  # fetch each new post page for title/excerpt/image
        "user_agent": "social-bot/0.1 (+content pipeline)",
    },
    # Idea seeds: the systems/architectures *original* Atento posts are drawn
    # from — NOT `sources[]` (those are feeds to repost). Nothing is fetched:
    # `topics_file` is a plain list of themes (Elasticsearch, ClickHouse, Loki,
    # MySQL, …) to write about. Ideas are written in Claude and queued by hand
    # (`social-bot blog add-idea`); the app only holds the themes and the dedupe
    # ledger (see draft_pipeline.queue_ideas).
    "ideas": {
        "topics_file": "data/ideas/topics.md",  # one system/theme per line
        "source_name": "atento-original",  # the `source` on idea drafts
        "dir": "data/ideas",  # dedupe ledger
        "seen_name": "seen.json",
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


def resolve_token(name: str, cfg: dict, token: str | None = None) -> str:
    """The access token for a destination; '' if none is configured.

    Order: an explicit token > ``SOCIAL_BOT_<NAME>_TOKEN`` > ``SOCIAL_BOT_TOKEN``
    (global fallback) > ``destinations.<name>.token`` from credentials.yaml.
    """
    env_specific = os.environ.get(f"SOCIAL_BOT_{name.upper()}_TOKEN", "")
    resolved = (
        token
        or env_specific
        or os.environ.get(TOKEN_ENV, "")
        or str(cfg.get("destinations", {}).get(name, {}).get("token", ""))
    )
    return resolved.strip()


def _hhmm_minutes(value: str, field: str) -> int:
    """Parse "HH:MM" into minutes since midnight; raise ValueError on anything else."""
    hh, sep, mm = str(value).partition(":")
    if not (sep and hh.isdigit() and mm.isdigit()):
        raise ValueError(f"config: {field} has invalid time {value!r}")
    hour, minute = int(hh), int(mm)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"config: {field} has invalid time {value!r}")
    return hour * 60 + minute


def _check_post_slots(slots, field: str) -> None:
    """Validate a list of HH:MM slots or HH:MM-HH:MM windows (publish.post_at shape)."""
    if not isinstance(slots, list):
        raise ValueError(f"config: {field} must be a list of HH:MM")
    for slot in slots:
        text = str(slot)
        if "-" in text:
            start, _, end = text.partition("-")
            if _hhmm_minutes(start, field) >= _hhmm_minutes(end, field):
                raise ValueError(f"config: {field} window {slot!r} must start before it ends")
        else:
            _hhmm_minutes(text, field)


def validate(cfg: dict) -> None:
    """Raise ValueError on obviously unusable configuration."""
    # Imported here (not at module scope) to avoid a config <-> destinations
    # import cycle: the registry pulls in the platform packages, which import
    # resolve_token from this module.
    from .destinations import names as destination_names
    from .destinations import validate_destinations

    validate_destinations(cfg)
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
            raise ValueError(f"config: source {source.get('name')!r} needs path_prefix")

    publish = cfg.get("publish", {})
    destinations = publish.get("destinations")
    if not isinstance(destinations, list) or not destinations:
        raise ValueError("config: publish.destinations must be a non-empty list")
    known = set(destination_names())
    for destination in destinations:
        if destination not in known:
            raise ValueError(f"config: unknown publish destination {destination!r}")
    if int(publish.get("post_per_slot", 1)) < 1:
        raise ValueError("config: publish.post_per_slot must be >= 1")
    if int(publish.get("interval_days", 0)) < 0:
        raise ValueError("config: publish.interval_days must be >= 0")
    if int(publish.get("recent_captions", 0)) < 0:
        raise ValueError("config: publish.recent_captions must be >= 0")
    _check_post_slots(publish.get("post_at", []), "publish.post_at")
    per_destination = publish.get("destination_post_at", {})
    if not isinstance(per_destination, dict):
        raise ValueError("config: publish.destination_post_at must map destination -> slots")
    for name, slots in per_destination.items():
        if name not in known:
            raise ValueError(f"config: unknown publish.destination_post_at destination {name!r}")
        _check_post_slots(slots, f"publish.destination_post_at.{name}")

    blog = cfg.get("blog", {})
    if float(blog.get("timeout_seconds", 30)) <= 0:
        raise ValueError("config: blog.timeout_seconds must be positive")
    if int(blog.get("max_scan", 12)) < 1:
        raise ValueError("config: blog.max_scan must be >= 1")
    if int(blog.get("max_age_days", 0)) < 0:
        raise ValueError("config: blog.max_age_days must be >= 0")
    scan_at = blog.get("scan_at")
    if not isinstance(scan_at, list) or not scan_at:
        raise ValueError("config: blog.scan_at must be a non-empty list of HH:MM")
    for slot in scan_at:
        _hhmm_minutes(str(slot), "blog.scan_at")

    ideas = cfg.get("ideas", {})
    if not str(ideas.get("topics_file", "")).strip():
        raise ValueError("config: ideas.topics_file must not be empty")
    if not str(ideas.get("source_name", "")).strip():
        raise ValueError("config: ideas.source_name must not be empty")
