"""Content pipeline orchestration: scan sources, receive rewrites, publish.

The fetch/write glue lives here, the pure model in drafts.py, the pure parsing
in source.py, and the network in source_api.py and the `destinations/` packages.
Publishing is always explicit — scan never posts.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

from . import ideas as idea_seeds
from . import media
from .browser_shot import ShotError, html_to_png
from .caption import display_title
from .caption_lint import lint_caption
from .config import ROOT, load_config
from .destinations import (
    DestinationError,
    describe_all,
    publisher_for,
)
from .destinations import (
    names as destination_names,
)
from .diagram import render_for_draft as render_diagram_for_draft
from .diagram_html import render_for_draft_html as render_diagram_html_for_draft
from .drafts import (
    AI_DRAFT,
    APPROVED,
    EXTRACTED,
    REWRITE_CAPTION,
    REWRITE_CAPTION_VOICE,
    STATES,
    Draft,
    append_audit,
    find,
    load_drafts,
    now_iso,
    parse_when,
    save_drafts,
)
from .source import Source, parse_blog_posting, parse_source
from .source_api import SourceClient, SourceError

# States shown for review / rewrite. OPEN_STATES is the rewrite backlog (what
# the rewriter reads and may rewrite); REVIEW_STATES adds approved drafts, which
# stay on /review until they post.
OPEN_STATES = ("extracted", "ai_draft")
REVIEW_STATES = (EXTRACTED, AI_DRAFT, APPROVED)
# The scheduler's queue: drafts a human approved, waiting for a posting slot.
SCHEDULED_STATES = (APPROVED,)


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


# Parsed side-files (seen ledger, publish audit, DNA/style briefs) keyed by
# path, validated against (mtime_ns, size). Read on every request by /status,
# /review and /api/drafts; re-parsing them each time is pure waste once warm.
# Callers get a copy of the cached value, never the cache itself.
_FILE_CACHE: dict[str, tuple[int, int, object]] = {}


def _cached_file(path: pathlib.Path, parse):
    """parse(path) memoized on (mtime_ns, size); None when the file is absent."""
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (stat.st_mtime_ns, stat.st_size)
    cached = _FILE_CACHE.get(str(path))
    if cached is not None and cached[0] == key[0] and cached[1] == key[1]:
        return cached[2]
    value = parse(path)
    _FILE_CACHE[str(path)] = (key[0], key[1], value)
    return value


def _write_json(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    _FILE_CACHE.pop(str(path), None)


def load_seen(cfg: dict) -> set[str]:
    cached = _cached_file(seen_path(cfg), lambda p: set(json.loads(p.read_text(encoding="utf-8"))))
    return set(cached) if cached else set()


def save_seen(cfg: dict, seen: set[str]) -> None:
    _write_json(seen_path(cfg), sorted(seen))


def _read_optional_file(raw) -> str:
    """Contents of a configured file path (resolved against ROOT), or ''."""
    raw = str(raw or "").strip()
    if not raw:
        return ""
    path = pathlib.Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return _cached_file(path, lambda p: p.read_text(encoding="utf-8")) or ""


def dna_text(cfg: dict) -> str:
    """Contents of publish.dna_file, if configured and present."""
    return _read_optional_file(cfg.get("publish", {}).get("dna_file"))


def voice_map(cfg: dict) -> dict[str, str]:
    """The configured voice menu ``publish.voices`` as {key: file path}."""
    raw = cfg.get("publish", {}).get("voices")
    if not isinstance(raw, dict):
        return {}
    return {
        str(key).strip(): str(path).strip()
        for key, path in raw.items()
        if str(key).strip() and str(path).strip()
    }


def voice_choices(cfg: dict) -> list[str]:
    """The voice keys a rewriter may pick from (DNA §3)."""
    return list(voice_map(cfg))


def default_voice(cfg: dict) -> str:
    """The voice key the pipeline falls back to when the rewriter omits one."""
    return str(cfg.get("publish", {}).get("default_voice") or "").strip()


def _resolve_voice(cfg: dict, key) -> str:
    """Keep a valid voice key; otherwise the default; '' when no menu."""
    choices = voice_choices(cfg)
    key = str(key or "").strip()
    if key in choices:
        return key
    fallback = default_voice(cfg)
    return fallback if fallback in choices else ""


def voice_text(cfg: dict, key: str = "") -> str:
    """The resolved voice file's text (brief + samples) for one draft.

    A voice file is the register's full brief with its verbatim ``Samples``; the
    rewriter reads it to write in that voice. An unknown or blank key falls back
    to ``publish.default_voice``; '' when no menu is configured.
    """
    voices = voice_map(cfg)
    chosen = _resolve_voice(cfg, key)
    return _read_optional_file(voices.get(chosen)).strip() if chosen else ""


def _first_paragraph(text: str) -> str:
    """A file's opening paragraph collapsed to one line ('' when empty)."""
    lines: list[str] = []
    for line in text.strip().splitlines():
        if not line.strip():
            break
        lines.append(line)
    return " ".join(" ".join(lines).split())


def voice_hints(cfg: dict) -> dict[str, str]:
    """Operator guidance per voice: ``{key: the file's opening paragraph}``.

    The hint is each voice file's own "when to use" paragraph, so the review page
    describes the voices from ``docs/voices/`` rather than keeping a second copy
    that drifts. A key whose file is missing or empty is omitted.
    """
    hints: dict[str, str] = {}
    for key, path in voice_map(cfg).items():
        paragraph = _first_paragraph(_read_optional_file(path))
        if paragraph:
            # Drop the "Voice: " lead-in and the files' markdown emphasis, which
            # would otherwise show literally as asterisks in the UI.
            hints[key] = paragraph.removeprefix("Voice: ").replace("*", "")
    return hints


# -- AI image generation -------------------------------------------------


def rewrite_config(cfg: dict) -> dict:
    """The rewriter-worker settings (``rewrite``); see scripts/rewrite_worker.py."""
    return dict(cfg.get("rewrite", {}) or {})


def diagram_dir(cfg: dict) -> pathlib.Path:
    """Where code-drawn diagrams and generated images are stored.

    Served by the app at ``/images/`` (see ``media``, which owns the folder and
    the name validation).
    """
    return media.images_dir(cfg)


def render_diagrams(
    cfg: dict | None = None,
    *,
    draft_ids: list[str] | None = None,
    states: tuple[str, ...] | None = OPEN_STATES,
    limit: int | None = None,
    overwrite: bool = False,
) -> dict:
    """Render code-drawn diagrams for queued drafts and point them at it.

    No network, no provider — the renderer (``diagram.py``) draws the draft's
    mechanism from its own template and the file lands in ``diagram_dir``
    (inside the bind-mounted review dir, so the container serves it with no
    rebuild). A batch only picks up drafts with ``image_style == diagram``;
    a caller naming drafts explicitly renders them regardless of style.

    Graph only accepts raster, so each SVG is also screenshotted to PNG
    through the host's Chromium (``diagram_html`` + ``browser_shot``) and the
    draft points at the PNG — exactly the bytes a later publish uploads.
    A missing or failing browser never blocks the render: the draft keeps
    pointing at the SVG preview.

    Fills the gap by default and never replaces an existing image without
    ``overwrite``.
    """
    cfg = cfg or load_config()
    drafts = load_drafts(queue_path(cfg))
    wanted = set(draft_ids) if draft_ids else None
    if wanted is not None:
        states = None
    selected = [
        draft
        for draft in drafts
        if (wanted is None or draft.id in wanted)
        and (states is None or draft.state in states)
        and (wanted is not None or draft.image_style == "diagram")
        and (overwrite or not draft.image)
    ]
    if wanted:
        missing = wanted - {draft.id for draft in drafts}
        if missing:
            raise ValueError(f"no draft {sorted(missing)[0]!r}")
    if limit is not None:
        selected = selected[:limit]

    rendered: list[str] = []
    rastered: set[str] = set()
    out_dir = diagram_dir(cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    for draft in selected:
        svg = render_diagram_for_draft(draft)
        if not svg:
            continue
        (out_dir / f"{draft.id}.svg").write_text(svg, encoding="utf-8")
        try:
            page = render_diagram_html_for_draft(draft)
            if page:
                html_to_png(page, out_dir / f"{draft.id}.png")
                rastered.add(draft.id)
        except ShotError:
            pass
        rendered.append(draft.id)

    if rendered:
        fresh = load_drafts(queue_path(cfg))
        for draft in fresh:
            if draft.id in rendered:
                ext = ".png" if draft.id in rastered else ".svg"
                draft.image = f"/images/{draft.id}{ext}"
                draft.touch()
        save_drafts(queue_path(cfg), fresh)
    return {
        "rendered": len(rendered),
        "candidates": len(selected),
        "ids": rendered,
    }


def localize_images(
    cfg: dict | None = None,
    *,
    draft_ids: list[str] | None = None,
    states: tuple[str, ...] | None = REVIEW_STATES,
    limit: int | None = None,
) -> dict:
    """Copy still-remote non-source images into the local store.

    A migration for drafts whose image is a remote URL that is not the source
    post's own cover (e.g. a legacy AI image): the bytes are kept and the draft
    just points at ``/images/<id>.<ext>`` instead. A draft showing the source
    post's own cover keeps that remote URL.
    """
    cfg = cfg or load_config()
    drafts = load_drafts(queue_path(cfg))
    wanted = set(draft_ids) if draft_ids else None
    if wanted is not None:
        states = None
    selected = [
        draft
        for draft in drafts
        if (wanted is None or draft.id in wanted)
        and (states is None or draft.state in states)
        and draft.image
        and not media.is_local(draft.image)
        and image_is_generated(cfg, draft)
    ]
    if wanted:
        missing = wanted - {draft.id for draft in drafts}
        if missing:
            raise ValueError(f"no draft {sorted(missing)[0]!r}")
    if limit is not None:
        selected = selected[:limit]

    errors: list[dict] = []
    localized: dict[str, str] = {}
    for draft in selected:
        try:
            data, _, _ = media.load(cfg, draft.image)
            localized[draft.id] = media.save(cfg, draft.id, data)
        except media.MediaError as exc:
            errors.append({"source": draft.id, "error": f"image {draft.id}: {exc}"})

    if localized:
        # Re-read before saving: the downloads are slow, and writing back the
        # queue loaded above would discard anything that landed meanwhile.
        fresh = load_drafts(queue_path(cfg))
        for draft in fresh:
            url = localized.get(draft.id)
            if url:
                draft.image = url
                draft.touch()
        save_drafts(queue_path(cfg), fresh)
    return {
        "localized": len(localized),
        "candidates": len(selected),
        "ids": list(localized),
        "errors": errors,
    }


def image_is_generated(cfg: dict, draft: Draft) -> bool:
    """True when the draft's current image is not the source post's own cover.

    With ``source_image`` recorded the answer is exact — the source's own cover
    is either the current image or it isn't. Older drafts have no
    ``source_image``: any locally stored ``/images/...`` file (a diagram or a
    previously localized image) counts as generated, while a remote URL does
    not.
    """
    url = str(draft.image or "").strip()
    if not url:
        return False
    if draft.source_image:
        return url != draft.source_image
    return media.is_local(url)


def restore_source_image(cfg: dict, draft_id: str, *, client: SourceClient | None = None) -> Draft:
    """Put the source post's own image back on a draft, replacing a generated one.

    The image the source published is kept on the draft (``source_image``), so
    this is usually just a swap. Drafts scanned before it was recorded — and
    drafts whose source image was replaced by a diagram — have none, so the
    source page is fetched once and asked for its own image; that recovered
    image is stored so the next restore needs no network.

    Raises ``ValueError`` when there is nothing to restore: an unknown draft, a
    draft with no source URL, or a source page that publishes no image.
    """
    drafts = load_drafts(queue_path(cfg))
    draft = find(drafts, draft_id)
    if draft is None:
        raise ValueError(f"no draft {draft_id!r}")

    image = draft.source_image
    if not image:
        if not draft.url:
            raise ValueError(
                "nothing to restore: this draft has no source URL to read an image from"
            )
        image = _fetch_source_image(cfg, draft, client)
        if not image:
            raise ValueError("the source post publishes no image to restore")

    draft.source_image = image
    draft.image = image
    draft.touch()
    save_drafts(queue_path(cfg), drafts)
    return draft


def _fetch_source_image(cfg: dict, draft: Draft, client: SourceClient | None) -> str:
    """The image on a draft's source page ('' when the page publishes none).

    Enrichment ran at scan time, so this only matters for a draft queued before
    the source image was kept — or whose page failed to load back then. Both
    "no image" and "unreachable" end as a ``ValueError`` the review page can
    show: a draft that never had a cover is not a broken pipeline.
    """
    fetcher = client or SourceClient.from_config(cfg)
    try:
        page = fetcher.get_text(draft.url)
    except SourceError as exc:
        raise ValueError(f"could not read the source page: {exc}") from exc
    item = parse_blog_posting(
        page,
        draft.url,
        source_name=draft.source,
        excerpt_chars=int(cfg.get("blog", {}).get("excerpt_chars", 240)),
    )
    return item.image


# -- reading the queue ---------------------------------------------------


_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)


def _sort_key(draft: Draft) -> tuple[dt.datetime, dt.datetime]:
    """Newest first by the item's own date, falling back to when it was queued.

    Scanning queues a whole batch within seconds, so `created_at` orders a scan
    almost arbitrarily; the source's `published` date is the one shown on the
    review cards and the one an operator expects to sort by.
    """
    queued = parse_when(draft.created_at) or parse_when(draft.updated_at) or _EPOCH
    return (parse_when(draft.published) or queued, queued)


def list_drafts(cfg: dict, states: tuple[str, ...] | None = None) -> list[Draft]:
    """Queue drafts, newest first (source publish date, then queue time)."""
    drafts = load_drafts(queue_path(cfg))
    if states is not None:
        drafts = [d for d in drafts if d.state in states]
    return sorted(drafts, key=_sort_key, reverse=True)


def _queue_key(draft: Draft) -> tuple[int, int, tuple[dt.datetime, dt.datetime]]:
    """Posting order: manually-ranked drafts first, then the default FIFO.

    A draft with a manual ``queue_order`` (set on the Post queue tab)
    sorts by rank ascending; everything else keeps the default oldest-source-first
    order and follows the ranked block. With no ranks set this is exactly
    ``_sort_key``.
    """
    default = _sort_key(draft)
    rank = draft.rank
    return (0, rank, default) if rank else (1, 0, default)


def _queue_first(drafts: list[Draft]) -> list[Draft]:
    """Sort drafts the way the poster drains them (see ``_queue_key``)."""
    return sorted(drafts, key=_queue_key)


def _pending_queue(drafts: list[Draft]) -> list[Draft]:
    """The drafts that are actually queued to post: approved, still pending."""
    return [
        draft
        for draft in drafts
        if draft.state in SCHEDULED_STATES and draft.pending_destinations()
    ]


def next_scheduled(drafts: list[Draft]) -> Draft | None:
    """The draft ``publish_scheduled`` would send next: the first in the queue.

    Pure over an already-loaded queue, so callers that need the whole snapshot
    (``status``) don't re-read the file. Returns None when nothing is approved —
    the scheduler then has nothing to post.
    """
    pending = _pending_queue(drafts)
    return _queue_first(pending)[0] if pending else None


def scheduled_queue(cfg: dict) -> list[Draft]:
    """Approved drafts with a destination still to post to, in posting order."""
    return _queue_first(_pending_queue(load_drafts(queue_path(cfg))))


def queue_view(cfg: dict) -> list[dict]:
    """The post queue as UI rows: id and display title, in posting order.

    One source for the CLI's ordered listing, so the list an operator sees is
    exactly what the poster will drain.
    """
    return [
        {"id": draft.id, "title": display_title(draft.caption, draft.title or draft.id)}
        for draft in scheduled_queue(cfg)
    ]


def set_queue_order(cfg: dict, ids: list[str]) -> list[Draft]:
    """Reorder the post queue to the given id order.

    ``ids`` must be queued drafts, unique, and in the desired relative order. A
    subset is allowed — its members are placed into the positions they currently
    occupy, so reordering one visible page leaves the rest of the queue put. The
    whole queue is then renumbered ``1..N`` so ranks stay contiguous; anything
    that was unranked becomes ranked, and a later-approved draft (rank 0) sorts
    after the ranked block. Returns the new queue.
    """
    queue = scheduled_queue(cfg)
    by_id = {draft.id: draft for draft in queue}
    wanted = [str(draft_id) for draft_id in ids]
    if len(set(wanted)) != len(wanted):
        raise ValueError("duplicate draft ids in the new order")
    unknown = [draft_id for draft_id in wanted if draft_id not in by_id]
    if unknown:
        raise ValueError(f"not in the post queue: {', '.join(unknown)}")

    positions = [index for index, draft in enumerate(queue) if draft.id in set(wanted)]
    reordered = list(queue)
    for slot, draft_id in zip(positions, wanted, strict=True):
        reordered[slot] = by_id[draft_id]

    ranks = {draft.id: index + 1 for index, draft in enumerate(reordered)}
    drafts = load_drafts(queue_path(cfg))
    for draft in drafts:
        if draft.id in ranks:
            draft.queue_order = ranks[draft.id]
    save_drafts(queue_path(cfg), drafts)
    return _queue_first([draft for draft in drafts if draft.id in ranks])


def move_in_queue(cfg: dict, draft_id: str, direction: str) -> list[Draft]:
    """Move one queued draft up, down, to the top, or to the bottom.

    Only drafts in the post queue (approved, with a destination to post to) can
    be reordered; the ends are no-ops rather than errors, so an out-of-range
    click is harmless. Delegates the write to ``set_queue_order``.
    """
    queue = scheduled_queue(cfg)
    ids = [draft.id for draft in queue]
    if draft_id not in ids:
        raise ValueError(f"draft {draft_id!r} is not in the post queue")
    index = ids.index(draft_id)
    if direction == "up" and index > 0:
        ids[index - 1], ids[index] = ids[index], ids[index - 1]
    elif direction == "down" and index < len(ids) - 1:
        ids[index], ids[index + 1] = ids[index + 1], ids[index]
    elif direction == "top":
        ids.insert(0, ids.pop(index))
    elif direction == "bottom":
        ids.append(ids.pop(index))
    elif direction not in ("up", "down"):
        raise ValueError(f"unknown direction {direction!r}")
    return set_queue_order(cfg, ids)


def reset_queue_order(cfg: dict) -> int:
    """Clear every manual rank, restoring the default oldest-first order.

    Returns how many drafts were cleared.
    """
    drafts = load_drafts(queue_path(cfg))
    cleared = 0
    for draft in drafts:
        if draft.rank:
            draft.queue_order = 0
            cleared += 1
    if cleared:
        save_drafts(queue_path(cfg), drafts)
    return cleared


def filter_drafts(
    drafts: list[Draft], *, source: str = "", state: str = "", q: str = ""
) -> list[Draft]:
    """Narrow a listing by source, state, and/or a free-text search ('' = off).

    The search matches the title, the excerpt, or the caption, case-insensitively
    — the caption because that is where a row's displayed title (its hook) lives
    — so an operator can find one item in a long queue without paging through it.
    """
    if source:
        drafts = [d for d in drafts if d.source == source]
    if state:
        drafts = [d for d in drafts if d.state == state]
    if q:
        needle = str(q).strip().lower()
        if needle:
            drafts = [
                d
                for d in drafts
                if needle in (d.title or "").lower()
                or needle in (d.excerpt or "").lower()
                or needle in (d.caption or "").lower()
            ]
    return drafts


def sort_drafts(drafts: list[Draft], sort: str = "") -> list[Draft]:
    """Order the review listing for display: 'newest' (default) or 'oldest'.

    Display only — the posting order is a separate rule entirely (``_queue_key``),
    which is why it lives on the post queue page rather than here.
    """
    if sort == "oldest":
        return sorted(drafts, key=_sort_key)
    return sorted(drafts, key=_sort_key, reverse=True)


def paginate(items: list, *, page: int = 1, per_page: int | None = None) -> tuple[list, dict]:
    """Slice an ordered listing into one page plus its metadata.

    ``per_page`` falsy (0/None) disables paging and returns everything on one
    page. The requested page is clamped to ``[1, pages]`` so a stale bookmark
    past the end renders the last page instead of an empty one.
    """
    total = len(items)
    if not per_page or per_page < 1:
        return list(items), {
            "page": 1,
            "per_page": total,
            "total": total,
            "pages": 1,
            "has_prev": False,
            "has_next": False,
        }
    pages = max(1, -(-total // per_page))
    current = max(1, min(int(page or 1), pages))
    start = (current - 1) * per_page
    return items[start : start + per_page], {
        "page": current,
        "per_page": per_page,
        "total": total,
        "pages": pages,
        "has_prev": current > 1,
        "has_next": current < pages,
    }


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


def _scan_cutoff(cfg: dict) -> dt.datetime | None:
    """The oldest publish date a scan may queue, or None when uncapped.

    ``blog.max_age_days`` (0 = off) stops a feed that exposes more entries than
    one scan takes — martinfowler's Atom, notably — from being walked back one
    ``max_scan`` batch per run long after the first scan.
    """
    days = int(cfg.get("blog", {}).get("max_age_days", 0) or 0)
    if days <= 0:
        return None
    return dt.datetime.now(dt.UTC) - dt.timedelta(days=days)


def _too_old(published: str, cutoff: dt.datetime | None) -> bool:
    """True when an item's own date is before the cutoff.

    Undated items are kept: a source that gives no date (an unenriched index
    item, a sitemap entry with no ``lastmod``) can't be shown to be old, and
    dropping it would silently lose a new post.
    """
    if cutoff is None:
        return False
    when = parse_when(published)
    return when is not None and when < cutoff


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
    going. Marks an id seen only after it is queued (durable dedupe). Items older
    than ``blog.max_age_days`` are skipped (see ``_scan_cutoff``).
    """
    cfg = cfg or load_config()
    raw_sources = list(cfg.get("sources", []))
    if source_names:
        wanted = set(source_names)
        raw_sources = [s for s in raw_sources if s.get("name") in wanted]

    client = client or SourceClient.from_config(cfg)
    seen = load_seen(cfg)
    # Only the ids are needed from the queue up front: the queue itself is
    # re-read just before saving, once the (slow) fetches are done.
    existing_ids = {draft.id for draft in load_drafts(queue_path(cfg))}
    destinations = list(cfg.get("publish", {}).get("destinations", []))
    excerpt_chars = int(cfg.get("blog", {}).get("excerpt_chars", 240))
    max_scan = int(limit if limit is not None else cfg.get("blog", {}).get("max_scan", 12))
    enrich = bool(cfg.get("blog", {}).get("enrich", True))
    cutoff = _scan_cutoff(cfg)

    added: list[Draft] = []
    skipped_old = 0
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
        # Drop out-of-window items before the cap, so old entries can't consume
        # it and the walk back through an archive feed stops at the cutoff.
        if cutoff is not None:
            in_window = [item for item in fresh if not _too_old(item.published, cutoff)]
            skipped_old += len(fresh) - len(in_window)
            fresh = in_window
        for item in fresh[:max_scan]:
            if enrich and _needs_enrich(item):
                item = _enrich(client, source, item, excerpt_chars, errors)
            # An index item carries no date until enrichment: check it again now.
            if _too_old(item.published, cutoff):
                skipped_old += 1
                continue
            draft = Draft(
                id=item.id,
                source=source.name,
                url=item.url,
                title=item.title,
                excerpt=item.excerpt,
                image=item.image,
                source_image=item.image,
                published=item.published,
                lang=source.lang,
                state=EXTRACTED,
                destinations=list(destinations),
                created_at=now_iso(),
                updated_at=now_iso(),
            )
            seen.add(f"{source.name}:{item.id}")
            existing_ids.add(item.id)
            added.append(draft)

    # Re-read before saving: fetching every source is slow (and the host retries),
    # so writing back a queue read at the top would silently discard whatever
    # landed meanwhile — a manual post's record, a rewrite, an edit. Merge the
    # new drafts into the queue as it is now instead.
    merged = load_drafts(queue_path(cfg))
    known = {draft.id for draft in merged}
    merged.extend(draft for draft in added if draft.id not in known)
    save_drafts(queue_path(cfg), merged)
    save_seen(cfg, load_seen(cfg) | seen)
    return {
        "sources": len(raw_sources),
        "added": len(added),
        "skipped_old": skipped_old,
        "total_drafts": len(merged),
        "errors": errors,
        "items": [d.to_dict() for d in added],
    }


# -- rewrite intake ------------------------------------------------------


def ideas_config(cfg: dict) -> dict:
    """The ``ideas`` block (idea seeds: original posts, not source reposts)."""
    return dict(cfg.get("ideas", {}) or {})


def ideas_enabled(cfg: dict) -> bool:
    return bool(ideas_config(cfg).get("enabled", False))


def ideas_source_name(cfg: dict) -> str:
    """The ``source`` stamped on drafts the agent generates from an idea seed."""
    raw = str(ideas_config(cfg).get("source_name") or "").strip()
    return raw or "atento-original"


def ideas_dir(cfg: dict) -> pathlib.Path:
    return _dir(cfg, "ideas", "data/ideas")


def ideas_topics_path(cfg: dict) -> pathlib.Path:
    """The topics file (``ideas.topics_file``), resolved against the project root."""
    raw = str(ideas_config(cfg).get("topics_file") or "data/ideas/topics.md")
    path = pathlib.Path(raw)
    return path if path.is_absolute() else ROOT / path


def ideas_seen_path(cfg: dict) -> pathlib.Path:
    return ideas_dir(cfg) / str(ideas_config(cfg).get("seen_name", "seen.json"))


def ideas_state_path(cfg: dict) -> pathlib.Path:
    return ideas_dir(cfg) / str(ideas_config(cfg).get("state_name", "state.json"))


def load_topics(cfg: dict) -> list[dict]:
    """The configured idea seeds as ``[{"name", "url"}]`` ('' if the file is absent)."""
    text = _cached_file(ideas_topics_path(cfg), lambda p: p.read_text(encoding="utf-8")) or ""
    return idea_seeds.parse_topics(text)


def load_ideas_seen(cfg: dict) -> set[str]:
    """Slugs of ideas already queued, so the agent is never asked to repeat one."""
    cached = _cached_file(
        ideas_seen_path(cfg), lambda p: set(json.loads(p.read_text(encoding="utf-8")))
    )
    return set(cached) if cached else set()


def save_ideas_seen(cfg: dict, seen: set[str]) -> None:
    _write_json(ideas_seen_path(cfg), sorted(seen))


def load_ideas_request(cfg: dict) -> dict:
    """The pending "generate ideas" request state (``{}`` when none has been made)."""
    cached = _cached_file(
        ideas_state_path(cfg), lambda p: json.loads(p.read_text(encoding="utf-8"))
    )
    return dict(cached) if isinstance(cached, dict) else {}


def request_ideas(cfg: dict, note: str = "") -> dict:
    """Mark that the operator asked for a fresh batch of idea seeds.

    A human action (the review page's "Generate ideas" button, or ``blog ideas
    --request``) that only *records* the wish; the host-side worker
    (``scripts/rewrite_worker.py``) picks it up from ``GET /api/ideas`` and posts
    the ideas back through ``queue_ideas``. It never generates, rewrites, or
    posts anything itself.
    """
    if not ideas_enabled(cfg):
        raise ValueError("ideas are disabled (ideas.enabled is false)")
    if not load_topics(cfg):
        raise ValueError(f"no idea topics configured: add systems to {ideas_topics_path(cfg)}")
    payload = {"requested_at": now_iso(), "note": str(note or "").strip(), "error": ""}
    _write_json(ideas_state_path(cfg), payload)
    return payload


def clear_ideas_request(cfg: dict, *, error: str = "") -> dict:
    """Close a pending request (a batch landed, or the worker failed)."""
    payload = {"requested_at": "", "note": "", "error": str(error or "").strip()}
    _write_json(ideas_state_path(cfg), payload)
    return payload


def _existing_idea_titles(cfg: dict, limit: int = 40) -> list[str]:
    """Titles of ideas already queued (newest first) — what the agent must not repeat."""
    source = ideas_source_name(cfg)
    titles = [
        draft.title
        for draft in reversed(load_drafts(queue_path(cfg)))
        if draft.source == source and draft.title
    ]
    return titles[:limit]


def idea_brief(cfg: dict) -> dict:
    """Everything an agent needs to propose original ideas — and nothing to fetch.

    The configured themes (with optional reference-docs URLs), the titles already
    queued (so it does not repeat one), the DNA (the content pillars and brand
    rules live there), the most recently written captions (so a new idea does not
    reopen an old one), and the pending-request state the worker polls.
    """
    request = load_ideas_request(cfg)
    return {
        "enabled": ideas_enabled(cfg),
        "source_name": ideas_source_name(cfg),
        "per_run": max(1, int(ideas_config(cfg).get("per_run", 3))),
        "requested": bool(request.get("requested_at")),
        "requested_at": str(request.get("requested_at") or ""),
        "error": str(request.get("error") or ""),
        "topics": load_topics(cfg),
        "existing": _existing_idea_titles(cfg),
        "dna": dna_text(cfg),
        "recent": [{"id": d.id, "caption": d.caption} for d in recent_captions(cfg)],
    }


def queue_ideas(cfg: dict, ideas: list[dict]) -> dict:
    """Queue agent-proposed ideas as ``extracted`` drafts, deduped by title slug.

    Each idea is ``{"title", "topic", "excerpt"}`` — the specific angle, the
    system it belongs to (``ideas.topics_file``), and a short outline. The draft
    is an *original* post: ``source`` is ``ideas.source_name``, there is no
    ``url`` and no source image, and it flows through the normal rewrite + human
    review like any scanned draft. An idea whose slug already exists (in the
    queue or the ideas ledger) is skipped, so re-running a batch is safe. Never
    rewrites, approves, or posts.
    """
    if not ideas_enabled(cfg):
        raise ValueError("ideas are disabled (ideas.enabled is false)")
    source = ideas_source_name(cfg)
    seen = load_ideas_seen(cfg)
    drafts = load_drafts(queue_path(cfg))
    existing_ids = {draft.id for draft in drafts}
    destinations = list(cfg.get("publish", {}).get("destinations", []))

    added: list[Draft] = []
    skipped: list[dict] = []
    for raw in ideas or []:
        if not isinstance(raw, dict):
            continue
        title = " ".join(str(raw.get("title") or "").split())
        slug = idea_seeds.slugify(title)
        if not title or not slug:
            skipped.append({"title": title, "reason": "no title"})
            continue
        if slug in seen or slug in existing_ids:
            skipped.append({"title": title, "reason": "already queued"})
            continue
        excerpt = str(raw.get("excerpt") or raw.get("outline") or raw.get("angle") or "").strip()
        draft = Draft(
            id=slug,
            source=source,
            url="",
            title=title,
            topic=str(raw.get("topic") or "").strip(),
            excerpt=excerpt,
            lang="vi",
            state=EXTRACTED,
            destinations=list(destinations),
            created_at=now_iso(),
            updated_at=now_iso(),
        )
        drafts.append(draft)
        seen.add(slug)
        existing_ids.add(slug)
        added.append(draft)

    # Re-read before saving (see scan_sources): merge the new ideas into the queue
    # as it is now, so a concurrent write is never dropped.
    merged = load_drafts(queue_path(cfg))
    known = {draft.id for draft in merged}
    merged.extend(draft for draft in added if draft.id not in known)
    save_drafts(queue_path(cfg), merged)
    save_ideas_seen(cfg, load_ideas_seen(cfg) | seen)
    return {
        "added": len(added),
        "skipped": len(skipped),
        "drafts": [draft.to_dict() for draft in added],
        "skipped_ideas": skipped,
    }


def masthead_config(cfg: dict) -> dict:
    return dict(cfg.get("publish", {}).get("mastheads", {}) or {})


def masthead_choices(cfg: dict) -> list[str]:
    """The mastheads a rewriter may pick from (DNA §4.5)."""
    raw = masthead_config(cfg).get("choices") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(masthead).strip() for masthead in raw if str(masthead).strip()]


def default_masthead(cfg: dict) -> str:
    """The masthead the pipeline falls back to when the rewriter omits one."""
    return str(masthead_config(cfg).get("default") or "").strip()


def _leading_masthead(caption: str, choices: list[str]) -> str:
    """The allowed masthead the caption already opens with, or ''."""
    text = caption.lstrip()
    for masthead in choices:
        if text.startswith(masthead):
            return masthead
    return ""


def _ensure_masthead(caption: str, fallback: str, choices: list[str]) -> str:
    """Keep the rewriter's chosen masthead; prepend the fallback when absent.

    The DNA asks the rewriter to pick a masthead per post (by content, not
    source), so a caption that already opens with one of ``choices`` is left
    exactly as written. This only fills the gap when the rewriter didn't.
    """
    fallback = fallback.strip()
    if not fallback or _leading_masthead(caption, choices):
        return caption
    return f"{fallback}\n\n{caption}" if caption else fallback


def recent_caption_limit(cfg: dict) -> int:
    """``publish.recent_captions`` as an int (0 = don't send any)."""
    return int(cfg.get("publish", {}).get("recent_captions", 0) or 0)


def _recent_written(
    drafts: list[Draft], exclude_id: str = "", field: str = "caption"
) -> list[Draft]:
    """Drafts that already have ``field`` set, most recently written first."""
    written = [draft for draft in drafts if getattr(draft, field) and draft.id != exclude_id]
    return sorted(
        written,
        key=lambda d: parse_when(d.updated_at) or parse_when(d.created_at) or _EPOCH,
        reverse=True,
    )


def recent_captions(cfg: dict, *, limit: int | None = None, exclude_id: str = "") -> list[Draft]:
    """The most recently written captions, newest first, for anti-repetition.

    A rewriter only sees the *open* drafts it is asked to rewrite, so without
    this it can't tell it has opened three posts in a row the same way. Capped by
    ``publish.recent_captions`` (0 = off); the rewriter reads them and avoids
    reusing an opener, a closer, or the same vocabulary (DNA §12).
    """
    cap = recent_caption_limit(cfg) if limit is None else int(limit)
    if cap <= 0:
        return []
    return _recent_written(load_drafts(queue_path(cfg)), exclude_id)[:cap]


def _recent_texts(drafts: list[Draft], cfg: dict, exclude_id: str = "") -> list[str]:
    """The recent captions to lint against, as plain text ([] when disabled)."""
    cap = recent_caption_limit(cfg)
    if cap <= 0:
        return []
    return [draft.caption for draft in _recent_written(drafts, exclude_id)[:cap]]


def receive_rewrite(cfg: dict, draft_id: str, body: dict) -> Draft:
    """Store the AI rewrite (from the Command Code agent) on a draft.

    The caption is also *linted* — advisory only. The tells a run of posts
    converges on (a repeated hook or closer, a stock opener, a flat rhythm, the
    rule of three) are stored on the draft for the reviewer to see; the pipeline
    never edits the text itself (DNA §12).

    A **voice-locked** request ("Rewrite in this voice") keeps the voice the
    operator picked: the register on the draft was saved with the request, and it is
    this side — not the agent — that decides, so a run that ignored the prompt's
    instruction cannot quietly relabel the post. Read before ``apply_rewrite``,
    which clears the request.
    """
    choices = masthead_choices(cfg)
    fallback = default_masthead(cfg)
    drafts = load_drafts(queue_path(cfg))
    draft = find(drafts, draft_id)
    if draft is None:
        raise ValueError(f"no draft {draft_id!r}")
    if not draft.can_receive_rewrite():
        raise ValueError(f"draft {draft_id!r} in state {draft.state!r} cannot be rewritten")
    locked_voice = (
        _resolve_voice(cfg, draft.voice) if draft.rewrite_kind() == REWRITE_CAPTION_VOICE else ""
    )
    hashtags = body.get("hashtags")
    draft.apply_rewrite(
        caption=_ensure_masthead(str(body.get("caption", "") or ""), fallback, choices),
        hashtags=hashtags if hashtags is None else hashtags,
        cta=str(body.get("cta", "") or ""),
        commentary=str(body.get("commentary", "") or ""),
        image_prompt=str(body.get("image_prompt", "") or ""),
        image_style=str(body.get("image_style", "") or "").strip(),
        voice=_resolve_voice(cfg, locked_voice or body.get("voice")),
    )
    draft.lint = lint_caption(draft.caption, recent=_recent_texts(drafts, cfg, draft_id))
    save_drafts(queue_path(cfg), drafts)
    return draft


def edit_draft(
    cfg: dict,
    draft_id: str,
    *,
    caption: str | None = None,
    hashtags: str | None = None,
    image_prompt: str | None = None,
    image_style: str | None = None,
    voice: str | None = None,
    destinations: list[str] | None = None,
) -> Draft:
    """Human edits from the review page (caption, hashtags, image prompt, style, voice).

    ``destinations`` replaces the draft's target list — the review page's
    destination picker, so one draft can go to Facebook, another to LinkedIn,
    or one to both, instead of every draft inheriting ``publish.destinations``.
    An empty list is refused: a draft with no target could never be posted, and
    ``publish_draft`` would silently re-adopt the configured default.

    Re-lints the caption so the /review/{id} warnings track what a human just
    wrote too, not only what the rewriter submitted.
    """

    drafts = load_drafts(queue_path(cfg))
    draft = find(drafts, draft_id)
    if draft is None:
        raise ValueError(f"no draft {draft_id!r}")
    if caption is not None:
        draft.caption = caption
    if hashtags is not None:
        draft.hashtags = _split_hashtags(hashtags)
    if image_prompt is not None:
        draft.image_prompt = image_prompt
    if image_style is not None:
        draft.image_style = image_style
    if voice is not None:
        draft.voice = voice
    if destinations is not None:
        unknown = [name for name in destinations if name not in destination_names()]
        if unknown:
            raise ValueError(f"unknown destination(s): {', '.join(unknown)}")
        if not destinations:
            raise ValueError("a draft must target at least one destination")
        draft.destinations = list(dict.fromkeys(destinations))
    draft.touch()
    if draft.caption:
        draft.lint = lint_caption(draft.caption, recent=_recent_texts(drafts, cfg, draft_id))
    save_drafts(queue_path(cfg), drafts)
    return draft


def request_rewrite(cfg: dict, draft_id: str) -> Draft:
    """Ask the rewriter worker to rewrite a draft (a human action on /review).

    The agent picks the voice here, like the masthead and the image treatment;
    ``request_voice_rewrite`` is the sibling that locks it to the operator's pick.

    Only a draft still awaiting a rewrite (``extracted``/``ai_draft``) can be
    requested — an ``approved`` draft is already queued to post, and rewriting it
    would have to undo that approval. This only *marks* the draft; the host-side
    worker (``scripts/rewrite_worker.py``) picks the request up from
    ``GET /api/rewrite-queue`` and posts the result back through
    ``receive_rewrite``, which clears the request. Nothing here rewrites,
    approves, or posts.
    """
    now = now_iso()

    def _mutate(draft: Draft) -> None:
        if not draft.can_receive_rewrite():
            raise ValueError(f"draft {draft.id!r} in state {draft.state!r} cannot be rewritten")
        draft.rewrite_requested_at = now
        draft.rewrite_mode = REWRITE_CAPTION
        draft.rewrite_error = ""

    return _save_one(cfg, draft_id, _mutate)


def request_voice_rewrite(cfg: dict, draft_id: str) -> Draft:
    """Ask the worker to rewrite a draft *in the voice the operator picked*.

    The "Rewrite in this voice" action on /review/{id}: the same full rewrite as
    ``request_rewrite``, except the caption's register is not the agent's to choose.
    It submits the compose form, so the Voice pick is saved before this runs;
    ``build_prompt`` then names that key and forbids another, and ``receive_rewrite``
    re-asserts it on the way back in. Same gate as ``request_rewrite``
    (``extracted``/``ai_draft``) — an ``approved`` draft's caption is what a human
    already approved. Like every request this only *marks* the draft, and never
    touches the caption, the state, or a post.
    """
    now = now_iso()

    def _mutate(draft: Draft) -> None:
        if not draft.can_receive_rewrite():
            raise ValueError(f"draft {draft.id!r} in state {draft.state!r} cannot be rewritten")
        # Resolve first: the lock has to name a register that exists, or the prompt's
        # hard rule would point the agent at a key that is not in the menu.
        draft.voice = _resolve_voice(cfg, draft.voice)
        draft.rewrite_requested_at = now
        draft.rewrite_mode = REWRITE_CAPTION_VOICE
        draft.rewrite_error = ""

    return _save_one(cfg, draft_id, _mutate)


def cancel_rewrite(cfg: dict, draft_id: str) -> Draft:
    """Drop a pending rewriter request (and any error it left behind)."""

    def _mutate(draft: Draft) -> None:
        draft.rewrite_requested_at = ""
        draft.rewrite_mode = ""
        draft.rewrite_error = ""

    return _save_one(cfg, draft_id, _mutate)


def record_rewrite_error(cfg: dict, draft_id: str, error: str) -> Draft:
    """Close a rewriter request with the worker's failure recorded on the draft.

    The request is cleared so it does not sit open forever (the operator can ask
    again), and the error is stored so ``/review/{id}`` can say why nothing came
    back instead of showing a request that waits indefinitely.
    """

    def _mutate(draft: Draft) -> None:
        draft.rewrite_error = str(error or "").strip() or "unknown error"
        draft.rewrite_requested_at = ""
        draft.rewrite_mode = ""

    return _save_one(cfg, draft_id, _mutate)


def rewrite_queue(cfg: dict) -> list[Draft]:
    """The drafts a human asked the rewriter for, oldest request first (the worker's FIFO).

    A full rewrite or a full rewrite in a voice the operator picked, marked
    with ``Draft.rewrite_mode``; a draft leaves the queue when its result lands
    (``receive_rewrite``) or the request is cancelled / fails.
    """
    pending = [draft for draft in load_drafts(queue_path(cfg)) if draft.rewrite_requested_at]
    return sorted(pending, key=lambda d: parse_when(d.rewrite_requested_at) or _EPOCH)


def reject_draft(cfg: dict, draft_id: str) -> Draft:
    return _save_one(cfg, draft_id, lambda d: d.reject())


def approve_draft(cfg: dict, draft_id: str) -> Draft:
    """Queue a draft for the next posting slot (human action on /review).

    Approval does not post — the scheduler posts approved drafts later. This is
    the human gate: the scheduler itself never approves.
    """
    return _save_one(cfg, draft_id, lambda d: d.approve())


def unapprove_draft(cfg: dict, draft_id: str) -> Draft:
    """Pull a draft back out of the post queue (human action on /review).

    The inverse of ``approve_draft``: the draft leaves the queue the poster
    drains and returns to ``ai_draft``, so the scheduler skips it but it stays on
    /review for further edits, a rewrite, or another approval. It never posts,
    and never touches the caption.
    """
    return _save_one(cfg, draft_id, lambda d: d.unapprove())


def _split_hashtags(text: str) -> list[str]:
    for sep in (",", "\n"):
        text = text.replace(sep, " ")
    return [tag for tag in text.split() if tag]


def apply_masthead(
    cfg: dict | None = None,
    *,
    draft_ids: list[str] | None = None,
    states: tuple[str, ...] | None = OPEN_STATES,
    limit: int | None = None,
) -> dict:
    """Fill the default masthead into captions that have none.

    A safety net for captions written before/without a masthead. Normally the
    rewriter picks one per post (DNA §4.5) and ``receive_rewrite`` keeps it —
    and since that choice is a *content* judgment, this never replaces an
    existing one; a wrong label is for a human to fix on ``/review/{id}``.
    Idempotent, and never touches the image.
    """
    cfg = cfg or load_config()
    fallback = default_masthead(cfg)
    if not fallback:
        raise ValueError("no default masthead: set publish.mastheads.default in config.yaml")
    known = list(dict.fromkeys([fallback, *masthead_choices(cfg)]))
    drafts = load_drafts(queue_path(cfg))
    wanted = set(draft_ids) if draft_ids else None
    if wanted:
        missing = wanted - {draft.id for draft in drafts}
        if missing:
            raise ValueError(f"no draft {sorted(missing)[0]!r}")

    updated: list[Draft] = []
    for draft in drafts:
        if wanted is not None and draft.id not in wanted:
            continue
        if states is not None and draft.state not in states:
            continue
        if not draft.caption or _leading_masthead(draft.caption, known):
            continue
        if limit is not None and len(updated) >= limit:
            break
        draft.caption = f"{fallback}\n\n{draft.caption}"
        draft.touch()
        updated.append(draft)

    if updated:
        save_drafts(queue_path(cfg), drafts)
    return {
        "masthead": fallback,
        "updated": len(updated),
        "ids": [draft.id for draft in updated],
    }


def backfill_destinations(
    cfg: dict | None = None,
    *,
    draft_ids: list[str] | None = None,
    states: tuple[str, ...] | None = None,
    limit: int | None = None,
) -> dict:
    """Union queued drafts onto the configured ``publish.destinations``.

    A one-shot migration for drafts queued when the default was facebook-only:
    every draft missing a configured destination gains it, so an old
    ``["facebook"]`` draft becomes ``["facebook", "linkedin"]``. Never removes —
    a draft deliberately narrowed to one platform keeps that choice plus the
    missing defaults, and drafts already covering the set are untouched.
    Idempotent, and never touches the caption, the image, or the state.
    """
    cfg = cfg or load_config()
    configured = list(dict.fromkeys(cfg.get("publish", {}).get("destinations", []) or []))
    unknown = [name for name in configured if name not in destination_names()]
    if unknown:
        raise ValueError(f"unknown destination(s): {', '.join(unknown)}")
    if not configured:
        raise ValueError("no destinations: set publish.destinations in config.yaml")
    drafts = load_drafts(queue_path(cfg))
    wanted = set(draft_ids) if draft_ids else None
    if wanted:
        missing = wanted - {draft.id for draft in drafts}
        if missing:
            raise ValueError(f"no draft {sorted(missing)[0]!r}")

    updated: list[Draft] = []
    for draft in drafts:
        if wanted is not None and draft.id not in wanted:
            continue
        if states is not None and draft.state not in states:
            continue
        if limit is not None and len(updated) >= limit:
            break
        merged = list(dict.fromkeys([*draft.destinations, *configured]))
        if not draft.destinations:
            merged = list(configured)
        if merged == list(draft.destinations):
            continue
        draft.destinations = merged
        draft.touch()
        updated.append(draft)

    if updated:
        save_drafts(queue_path(cfg), drafts)
    return {
        "destinations": configured,
        "updated": len(updated),
        "ids": [draft.id for draft in updated],
    }


# -- publishing ----------------------------------------------------------


def _parse_published(path: pathlib.Path) -> list[dict]:
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


def list_published(cfg: dict) -> list[dict]:
    """The publish audit log as a list of records (newest last)."""
    records = _cached_file(published_path(cfg), _parse_published)
    return list(records) if records else []


def interval_days(cfg: dict) -> int:
    """``publish.interval_days`` as an int (0 = no minimum gap)."""
    return int(cfg.get("publish", {}).get("interval_days", 0) or 0)


def post_schedule(cfg: dict, default: list[str] | None = None) -> dict[str, list[str]]:
    """Each destination's posting slots: its own override, else the shared slots.

    ``default`` replaces ``publish.post_at`` as the shared slots (the serve CLI's
    ``--publish-at``); overrides in ``publish.destination_post_at`` still win.
    """
    publish = cfg.get("publish", {})
    shared = list(publish.get("post_at") or []) if default is None else list(default)
    overrides = publish.get("destination_post_at") or {}
    names = list(publish.get("destinations", []))
    names += [name for name in overrides if name not in names]
    return {
        name: list(overrides[name] or []) if name in overrides else list(shared) for name in names
    }


def _last_public_post_date(cfg: dict, destination: str | None = None) -> dt.date | None:
    """The local date of the most recent *pacing* post, or None if there is none.

    Only the sends ``publish.interval_days`` exists to pace are counted — the
    ones the scheduler made. Two kinds are skipped:
    - private (unpublished) sends, so they never pace the interval;
    - manual sends (``"manual": true``, an operator's Post now / a /queue
      platform button): the interval paces the machine, so a hand-made send must
      never hold the scheduler back afterwards.
    With ``destination`` set, only that destination's posts count, so each
    platform paces its own schedule.
    """
    latest: dt.date | None = None
    for record in list_published(cfg):
        if record.get("private") or record.get("manual"):
            continue
        recorded = record.get("destination")
        if destination is not None and recorded and recorded != destination:
            continue
        posted = str(record.get("posted_at", ""))[:10]
        try:
            day = dt.date.fromisoformat(posted)
        except ValueError:
            continue
        if latest is None or day > latest:
            latest = day
    return latest


def interval_remaining(cfg: dict, destination: str | None = None) -> int:
    """Days still to wait before interval_days allows another public post.

    0 means posting is allowed now (no interval, or enough days have passed).
    With ``destination`` set, it counts only that destination's posts.
    """
    minimum = interval_days(cfg)
    if minimum <= 0:
        return 0
    last = _last_public_post_date(cfg, destination)
    if last is None:
        return 0
    elapsed = (dt.datetime.now().astimezone().date() - last).days
    return max(0, minimum - elapsed)


def destination_state(cfg: dict) -> list[dict]:
    """Per-destination status for the operator UI (delegates to the registry)."""
    return describe_all(cfg)


def status(cfg: dict | None = None) -> dict:
    """A snapshot of the pipeline state for an operator/monitoring endpoint."""
    cfg = cfg or load_config()
    drafts = load_drafts(queue_path(cfg))
    by_state = dict.fromkeys(STATES, 0)
    for draft in drafts:
        by_state[draft.state] = by_state.get(draft.state, 0) + 1
    published = list_published(cfg)
    recent = list(reversed(published[-5:]))
    upcoming = next_scheduled(drafts)
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
            "open": (
                by_state.get(EXTRACTED, 0) + by_state.get(AI_DRAFT, 0) + by_state.get(APPROVED, 0)
            ),
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
            "destination_state": destination_state(cfg),
            "post_at": list(cfg.get("publish", {}).get("post_at", []) or []),
            "destination_post_at": post_schedule(cfg),
            "post_per_slot": int(cfg.get("publish", {}).get("post_per_slot", 1)),
            "interval_days": interval_days(cfg),
            "interval_remaining": max(
                [interval_remaining(cfg, name) for name in post_schedule(cfg)] or [0]
            ),
            "approved": by_state.get(APPROVED, 0),
            # What the poster will actually send next (the oldest approved). None
            # when nothing is approved, so the UI can say so instead of guessing.
            "next_draft": (
                {
                    "id": upcoming.id,
                    "title": display_title(upcoming.caption, upcoming.title),
                    "source": upcoming.source,
                    "has_image": bool(upcoming.image),
                }
                if upcoming
                else None
            ),
            "dna_file_set": bool(str(cfg.get("publish", {}).get("dna_file") or "").strip()),
            "voices_set": bool(voice_choices(cfg)),
            "voice_choices": voice_choices(cfg),
            "default_voice": default_voice(cfg),
        },
        "ideas": {
            # Idea seeds (original posts): how many systems are configured, and
            # whether a batch has been asked for but not yet delivered.
            "enabled": ideas_enabled(cfg),
            "source": ideas_source_name(cfg),
            "topics": len(load_topics(cfg)),
            "requested": bool(load_ideas_request(cfg).get("requested_at")),
        },
        "images": {
            "with_image": sum(1 for draft in drafts if draft.image),
        },
    }


def publish_draft(
    cfg: dict | None = None,
    draft_id: str = "",
    *,
    dry_run: bool = False,
    destination: str | None = None,
    token: str | None = None,
    skip_private_today: bool = False,
    manual: bool = False,
) -> dict:
    """Publish an approved/rewritten item to its destinations.

    Human-gated by construction: callers only reach here from an explicit
    approval action. ``dry_run`` prints the request and mutates nothing.

    A destination sending in private mode (``publish.private``) makes a real
    unpublished post: it is recorded in the audit log but leaves the draft in
    the queue, so the same draft can still be posted publicly later.

    ``manual`` marks an operator-initiated send (a draft's **Post now** on
    /review/{id}, or a platform button on /queue). Such a send sits outside
    ``publish.interval_days`` altogether: it is audited with ``"manual": true``,
    skips the interval gate, and does not pace it either — a person can always
    send by hand, and their one-off send never holds the scheduler back. The
    unattended drain (``publish_scheduled``, so also `blog publish` and **Post
    approved now**) leaves it false: that path is what the interval exists to
    pace.
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
            "run the rewrite (or approve it) before publishing"
        )

    if not draft.destinations:
        # A draft queued without routing adopts the configured set, so its post
        # records always have a target list to compare against.
        draft.destinations = list(cfg["publish"]["destinations"])
    targets = [destination] if destination else list(draft.destinations)
    # Each destination posts independently: skip the ones already posted publicly,
    # so a re-run (or a retry after a partial failure) only fills the gaps.
    already = set(draft.posted_destinations())
    targets = [name for name in targets if name not in already]
    # The interval only gates the unattended drain; a manual send always goes out
    # (and is excluded from the pacing afterwards, see _last_public_post_date).
    if not dry_run and not manual:
        for name in targets:
            remaining = interval_remaining(cfg, name)
            if remaining > 0:
                raise ValueError(
                    f"publish interval not reached for {name} (last public post "
                    f"{_last_public_post_date(cfg, name)}, minimum {interval_days(cfg)} "
                    f"day(s), {remaining} to go); not posting"
                )

    results: list[dict] = []
    for name in targets:
        # The scheduler passes skip_private_today: a private send deliberately
        # leaves the draft in the queue, so without this guard it would re-post
        # at every slot. A manual publish is never skipped.
        if skip_private_today and not dry_run and _private_sent_today(cfg, draft.id, name):
            results.append({"destination": name, "skipped": "already posted privately today"})
            continue
        publisher = publisher_for(name, cfg, token)
        if dry_run:
            print(f"dry-run: would {publisher.describe(draft)}")
            if draft.image:
                print(f"  image: {draft.image}")
            print(f"  caption:\n{draft.post_text}")
            results.append({"destination": name, "dry_run": True})
            continue
        result = publisher.publish(draft)
        draft.mark_posted(
            name,
            post_id=result.post_id,
            permalink=result.permalink,
            private=result.private,
        )
        append_audit(published_path(cfg), _audit_record(draft, name, manual=manual))
        save_drafts(queue_path(cfg), drafts)  # persist after each destination
        results.append(result.to_dict())

    return {
        "draft": draft.to_dict(),
        "results": results,
        "dry_run": dry_run,
        "private": any(result.get("private") for result in results),
    }


def _audit_record(draft: Draft, destination: str, *, manual: bool = False) -> dict:
    """The publish-log record for one destination, built from the draft's record.

    ``"manual": true`` marks an operator-initiated send, which
    ``_last_public_post_date`` leaves out of the ``publish.interval_days`` count.
    """
    record = draft.posts.get(destination, {})
    audit = {
        "id": draft.id,
        "source": draft.source,
        "url": draft.url,
        "destination": destination,
        "post_id": str(record.get("post_id", "")),
        "permalink": str(record.get("permalink", "")),
        "posted_at": str(record.get("posted_at", "")),
    }
    if record.get("private"):
        audit["private"] = True
    if manual:
        audit["manual"] = True
    return audit


def _private_sent_today(cfg: dict, draft_id: str, destination: str) -> bool:
    """True when this draft already had a *private* send to this destination today.

    Private sends deliberately leave the draft in the queue (see
    ``publish_draft``), so without this guard the scheduler would re-post the
    same draft at every slot while ``publish.private`` is on.
    """
    today = dt.datetime.now().astimezone().date().isoformat()
    return any(
        record.get("private")
        and record.get("id") == draft_id
        and record.get("destination") == destination
        and str(record.get("posted_at", "")).startswith(today)
        for record in list_published(cfg)
    )


def publish_scheduled(
    cfg: dict | None = None,
    *,
    limit: int | None = None,
    destination: str | None = None,
    token: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Post the oldest human-approved drafts, one slot's worth at a time.

    Human-gated by construction: it only ever touches drafts in state
    ``approved`` (a person clicked Approve on /review/{id}); it never approves.
    Each draft goes through the ordinary ``publish_draft`` path, so the
    ``publish.enabled`` kill-switch, the interval gate and the per-destination
    adapters all apply unchanged. These are *not* ``manual`` sends: the drain is
    the machine the interval paces, so its sends both obey the gate and count
    toward the gap (a draft's own **Post now** button does neither).

    ``limit`` overrides ``publish.post_per_slot`` for a manual run. A
    ``ValueError`` (the interval gate, most likely) stops the batch; a publisher
    or API error is recorded and the batch carries on.
    """
    cfg = cfg or load_config()
    if not cfg.get("publish", {}).get("enabled", True):
        raise ValueError("publishing is disabled (publish.enabled is false)")

    per_slot = int(cfg.get("publish", {}).get("post_per_slot", 1))
    batch = int(limit) if limit is not None else max(per_slot, 1)
    queued = scheduled_queue(cfg)  # oldest first
    if destination is not None:
        # A per-destination slot only sends to its own platform; a draft still
        # waiting on another platform stays queued for that platform's slot.
        queued = [draft for draft in queued if destination in draft.pending_destinations()]

    posted: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []
    handled = 0
    for draft in queued:
        if handled >= batch:
            break
        try:
            result = publish_draft(
                cfg,
                draft.id,
                dry_run=dry_run,
                destination=destination,
                token=token,
                skip_private_today=True,
            )
        except ValueError as exc:
            skipped.append({"id": draft.id, "reason": str(exc)})
            break  # interval/state unchanged: the rest would fail too
        except DestinationError as exc:
            errors.append({"id": draft.id, "error": str(exc)})
            continue
        handled += 1  # batch counts drafts, not destinations
        for entry in result["results"]:
            if entry.get("skipped"):
                skipped.append({"id": draft.id, "reason": entry["skipped"]})
                continue
            posted.append(
                {
                    "id": draft.id,
                    "destination": entry.get("destination", ""),
                    "post_id": entry.get("post_id", ""),
                    "permalink": entry.get("permalink", ""),
                    "private": bool(entry.get("private")),
                }
            )

    return {
        "posted": posted,
        "skipped": skipped,
        "errors": errors,
        "batch": batch,
        "queued": len(queued),
        "interval_remaining": interval_remaining(cfg),
    }
