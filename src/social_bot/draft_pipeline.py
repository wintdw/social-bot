"""Content pipeline orchestration: scan sources, receive rewrites, publish.

Mirrors refresh.py: the fetch/write glue lives here, the pure model in
drafts.py, the pure parsing in source.py, and the network in source_api.py /
publishers.py. Publishing is always explicit — scan never posts.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

from .config import ROOT, load_config
from .drafts import (
    AI_DRAFT,
    EXTRACTED,
    STATES,
    Draft,
    append_audit,
    find,
    load_drafts,
    now_iso,
    save_drafts,
)
from .publishers import publisher_for
from .source import Source, parse_blog_posting, parse_source
from .source_api import SourceClient, SourceError

# States shown for review / rewrite.
OPEN_STATES = ("extracted", "ai_draft")


def _dir(cfg: dict, section: str, default: str) -> pathlib.Path:
    """A configured store's directory, resolved against the project root."""
    raw = str(cfg.get(section, {}).get("dir") or default)
    path = pathlib.Path(raw)
    return path if path.is_absolute() else ROOT / path


def review_dir(cfg: dict) -> pathlib.Path:
    return _dir(cfg, "review", "data/review")


def queue_path(cfg: dict) -> pathlib.Path:
    return review_dir(cfg) / str(cfg["review"].get("queue_name", "queue.json"))


def seen_path(cfg: dict) -> pathlib.Path:
    return review_dir(cfg) / str(cfg["review"].get("seen_name", "seen.json"))


def published_path(cfg: dict) -> pathlib.Path:
    return _dir(cfg, "publish", "data/publish") / str(
        cfg.get("publish", {}).get("log_name", "published.jsonl")
    )


def _write_json(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_seen(cfg: dict) -> set[str]:
    path = seen_path(cfg)
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def save_seen(cfg: dict, seen: set[str]) -> None:
    _write_json(seen_path(cfg), sorted(seen))


def dna_text(cfg: dict) -> str:
    """Contents of publish.dna_file, if configured and present."""
    raw = str(cfg.get("publish", {}).get("dna_file") or "").strip()
    if not raw:
        return ""
    path = pathlib.Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path.read_text(encoding="utf-8") if path.exists() else ""


# -- reading the queue ---------------------------------------------------


def list_drafts(cfg: dict, states: tuple[str, ...] | None = None) -> list[Draft]:
    drafts = load_drafts(queue_path(cfg))
    if states is None:
        return drafts
    return [d for d in drafts if d.state in states]


def get_draft(cfg: dict, draft_id: str) -> Draft | None:
    return find(load_drafts(queue_path(cfg)), draft_id)


def _save_one(cfg: dict, draft_id: str, mutate) -> Draft:
    drafts = load_drafts(queue_path(cfg))
    draft = find(drafts, draft_id)
    if draft is None:
        raise ValueError(f"no draft {draft_id!r}")
    mutate(draft)
    save_drafts(queue_path(cfg), drafts)
    return draft


# -- scanning ------------------------------------------------------------


def _needs_enrich(item) -> bool:
    """True while any of title/excerpt/image is still missing."""
    return not (item.title and item.excerpt and item.image)


def _enrich(client, source, item, excerpt_chars: int, errors: list[dict]):
    """Fill title/excerpt/image from a post page. Failures keep the bare item."""
    try:
        page = client.get_text(item.url)
    except SourceError as exc:
        errors.append({"source": source.name, "error": f"enrich {item.url}: {exc}"})
        return item
    enriched = parse_blog_posting(
        page, item.url, source_name=source.name, excerpt_chars=excerpt_chars
    )
    item.title = enriched.title or item.title
    item.excerpt = enriched.excerpt or item.excerpt
    item.image = enriched.image or item.image
    item.published = item.published or enriched.published
    item.url = enriched.url or item.url
    return item


def scan_sources(
    cfg: dict | None = None,
    *,
    client: SourceClient | None = None,
    limit: int | None = None,
    source_names: list[str] | None = None,
) -> dict:
    """Fetch each source, queue unseen items as EXTRACTED drafts.

    Never raises on a single source failure — it records the error and keeps
    going. Marks an id seen only after it is queued (durable dedupe).
    """
    cfg = cfg or load_config()
    raw_sources = list(cfg.get("sources", []))
    if source_names:
        wanted = set(source_names)
        raw_sources = [s for s in raw_sources if s.get("name") in wanted]

    client = client or SourceClient.from_config(cfg)
    seen = load_seen(cfg)
    drafts = load_drafts(queue_path(cfg))
    existing_ids = {d.id for d in drafts}
    destinations = list(cfg.get("publish", {}).get("destinations", []))
    excerpt_chars = int(cfg.get("blog", {}).get("excerpt_chars", 240))
    max_scan = int(limit if limit is not None else cfg.get("blog", {}).get("max_scan", 12))
    enrich = bool(cfg.get("blog", {}).get("enrich", True))

    added: list[Draft] = []
    errors: list[dict] = []
    for raw in raw_sources:
        source = Source.from_config(raw)
        try:
            xml_text = client.get_text(source.url)
            items = parse_source(source, xml_text, excerpt_chars=excerpt_chars)
        except SourceError as exc:
            errors.append({"source": source.name, "error": str(exc)})
            continue

        fresh = [
            item
            for item in items
            if f"{source.name}:{item.id}" not in seen and item.id not in existing_ids
        ]
        for item in fresh[:max_scan]:
            if enrich and _needs_enrich(item):
                item = _enrich(client, source, item, excerpt_chars, errors)
            draft = Draft(
                id=item.id,
                source=source.name,
                url=item.url,
                title=item.title,
                excerpt=item.excerpt,
                image=item.image,
                published=item.published,
                lang=source.lang,
                state=EXTRACTED,
                destinations=list(destinations),
                created_at=now_iso(),
                updated_at=now_iso(),
            )
            drafts.append(draft)
            seen.add(f"{source.name}:{item.id}")
            existing_ids.add(item.id)
            added.append(draft)

    save_drafts(queue_path(cfg), drafts)
    save_seen(cfg, seen)
    return {
        "sources": len(raw_sources),
        "added": len(added),
        "total_drafts": len(drafts),
        "errors": errors,
        "items": [d.to_dict() for d in added],
    }


# -- rewrite intake ------------------------------------------------------


def receive_rewrite(cfg: dict, draft_id: str, body: dict) -> Draft:
    """Store the AI rewrite (from the Command Code agent) on a draft."""

    def mutate(draft: Draft) -> None:
        if not draft.can_receive_rewrite():
            raise ValueError(f"draft {draft_id!r} in state {draft.state!r} cannot be rewritten")
        hashtags = body.get("hashtags")
        draft.apply_rewrite(
            caption=str(body.get("caption", "") or ""),
            hashtags=hashtags if hashtags is None else hashtags,
            cta=str(body.get("cta", "") or ""),
            alt_text=str(body.get("alt_text", "") or ""),
            commentary=str(body.get("commentary", "") or ""),
        )

    return _save_one(cfg, draft_id, mutate)


def edit_draft(
    cfg: dict,
    draft_id: str,
    *,
    caption: str | None = None,
    hashtags: str | None = None,
) -> Draft:
    """Human edits from the review page (caption textarea + hashtags field)."""

    def mutate(draft: Draft) -> None:
        if caption is not None:
            draft.caption = caption
        if hashtags is not None:
            draft.hashtags = _split_hashtags(hashtags)
        draft.touch()

    return _save_one(cfg, draft_id, mutate)


def reject_draft(cfg: dict, draft_id: str) -> Draft:
    return _save_one(cfg, draft_id, lambda d: d.reject())


def _split_hashtags(text: str) -> list[str]:
    for sep in (",", "\n"):
        text = text.replace(sep, " ")
    return [tag for tag in text.split() if tag]


# -- publishing ----------------------------------------------------------


def list_published(cfg: dict) -> list[dict]:
    """The publish audit log as a list of records (newest last)."""
    path = published_path(cfg)
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def _published_today(cfg: dict) -> int:
    """Public posts made today — private (unpublished) test sends don't count."""
    today = dt.datetime.now().astimezone().date().isoformat()
    return sum(
        1
        for record in list_published(cfg)
        if not record.get("private")
        and str(record.get("posted_at", "")).startswith(today)
    )


def status(cfg: dict | None = None) -> dict:
    """A snapshot of the pipeline state for an operator/monitoring endpoint."""
    cfg = cfg or load_config()
    drafts = load_drafts(queue_path(cfg))
    by_state = {state: 0 for state in STATES}
    for draft in drafts:
        by_state[draft.state] = by_state.get(draft.state, 0) + 1
    published = list_published(cfg)
    recent = list(reversed(published[-5:]))
    return {
        "sources": [
            {
                "name": source.get("name"),
                "type": source.get("type"),
                "url": source.get("url"),
                "lang": source.get("lang", ""),
            }
            for source in cfg.get("sources", [])
        ],
        "drafts": {
            "total": len(drafts),
            "open": by_state.get(EXTRACTED, 0) + by_state.get(AI_DRAFT, 0),
            "by_state": by_state,
        },
        "seen": len(load_seen(cfg)),
        "published": {
            "total": len(published),
            "private": sum(1 for record in published if record.get("private")),
            "recent": recent,
        },
        "publish": {
            "enabled": bool(cfg.get("publish", {}).get("enabled", True)),
            "private": bool(cfg.get("publish", {}).get("private", False)),
            "destinations": list(cfg.get("publish", {}).get("destinations", [])),
            "max_per_day": int(cfg.get("publish", {}).get("max_per_day", 10)),
            "dna_file_set": bool(str(cfg.get("publish", {}).get("dna_file") or "").strip()),
        },
    }


def publish_draft(
    cfg: dict | None = None,
    draft_id: str = "",
    *,
    dry_run: bool = False,
    destination: str | None = None,
    token: str | None = None,
) -> dict:
    """Publish an approved/AI-drafted item to its destinations.

    Human-gated by construction: callers only reach here from an explicit
    approval action. ``dry_run`` prints the request and mutates nothing.

    A destination sending in private mode (``publish.private``) makes a real
    unpublished post: it is recorded in the audit log but leaves the draft in
    the queue, so the same draft can still be posted publicly later.
    """
    cfg = cfg or load_config()
    if not cfg.get("publish", {}).get("enabled", True):
        raise ValueError("publishing is disabled (publish.enabled is false)")

    drafts = load_drafts(queue_path(cfg))
    draft = find(drafts, draft_id)
    if draft is None:
        raise ValueError(f"no draft {draft_id!r}")
    if not draft.can_publish():
        raise ValueError(
            f"draft {draft_id!r} is in state {draft.state!r}; "
            "run the AI rewrite (or approve it) before publishing"
        )

    targets = [destination] if destination else (draft.destinations or cfg["publish"]["destinations"])
    if not dry_run:
        cap = int(cfg.get("publish", {}).get("max_per_day", 10))
        if _published_today(cfg) >= cap:
            raise ValueError(f"daily publish cap reached ({cap}); not posting today")

    results: list[dict] = []
    for name in targets:
        publisher = publisher_for(name, cfg, token)
        if dry_run:
            print(f"dry-run: would {publisher.describe(draft)}")
            if draft.image:
                print(f"  image: {draft.image}")
            print(f"  caption:\n{draft.post_text}")
            results.append({"destination": name, "dry_run": True})
            continue
        result = publisher.publish(draft)
        if result.get("private"):
            append_audit(
                published_path(cfg),
                {
                    "id": draft.id,
                    "source": draft.source,
                    "url": draft.url,
                    "destination": name,
                    "post_id": str(result.get("post_id", "")),
                    "permalink": str(result.get("permalink", "")),
                    "posted_at": now_iso(),
                    "private": True,
                },
            )
            results.append(result)
            continue
        draft.mark_posted(
            post_id=str(result.get("post_id", "")),
            permalink=str(result.get("permalink", "")),
        )
        append_audit(
            published_path(cfg),
            {
                "id": draft.id,
                "source": draft.source,
                "url": draft.url,
                "destination": name,
                "post_id": draft.post_id,
                "permalink": draft.permalink,
                "posted_at": draft.posted_at,
            },
        )
        save_drafts(queue_path(cfg), drafts)  # persist after each destination
        results.append(result)

    return {
        "draft": draft.to_dict(),
        "results": results,
        "dry_run": dry_run,
        "private": any(result.get("private") for result in results),
    }
