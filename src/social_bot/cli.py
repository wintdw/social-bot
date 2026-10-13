"""social-bot command line: `whoami`, `feed`, `post`, `refresh`, `blog scan`, `serve`."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from . import __version__, media
from .config import load_config, validate
from .destinations import names as destination_names
from .destinations import publisher_for
from .destinations.facebook import (
    ApiError,
    api_from_config,
    format_feed_md,
    parse_feed_response,
    refresh_feed,
)
from .draft_pipeline import (
    apply_masthead,
    backfill_destinations,
    ideas_topics_path,
    load_topics,
    localize_images,
    move_in_queue,
    publish_scheduled,
    queue_ideas,
    queue_view,
    reset_queue_order,
    scan_sources,
)

# Shown when the state directory can't be written (a common Docker uid mismatch).
_DATA_DIR_HINT = (
    "hint: the state directory must be writable by this process. The container "
    "runs as uid 1000 — on the host run `sudo chown -R 1000:1000 data`."
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="social-bot", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--config", type=pathlib.Path, help="config.yaml path (default: project root)"
    )
    parser.add_argument(
        "--token",
        help=(
            "facebook access token (overrides SOCIAL_BOT_TOKEN, "
            "SOCIAL_BOT_FACEBOOK_TOKEN, and credentials.yaml)"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_whoami = sub.add_parser("whoami", help="check the token and list pages it can manage")
    p_whoami.set_defaults(func=_cmd_whoami)

    p_dest = sub.add_parser(
        "destinations", help="list the destinations and whether each is routed/configured"
    )
    p_dest.set_defaults(func=_cmd_destinations)

    p_feed = sub.add_parser("feed", help="fetch the page feed (read-only)")
    p_feed.add_argument("--page-id", help="override destinations.facebook.account_id")
    p_feed.add_argument(
        "--limit", type=int, default=None, help="posts to show (default: feed.limit)"
    )
    p_feed.add_argument("--json", action="store_true", help="print the raw Graph API JSON instead")
    p_feed.set_defaults(func=_cmd_feed)

    p_post = sub.add_parser("post", help="post a status, link, or photo to the page")
    p_post.add_argument("--page-id", help="override destinations.facebook.account_id")
    p_post.add_argument("--message", help="post text (required unless --photo is given)")
    p_post.add_argument("--link", help="optional link attached to the post")
    p_post.add_argument(
        "--photo",
        help="publish a photo from a public image URL; --message becomes its caption",
    )
    p_post.add_argument(
        "--dry-run", action="store_true", help="print the request without sending it"
    )
    p_post.set_defaults(func=_cmd_post)

    p_refresh = sub.add_parser("refresh", help="fetch the page feed and cache it for `serve`")
    p_refresh.set_defaults(func=_cmd_refresh)

    p_blog = sub.add_parser("blog", help="content pipeline: scan source feeds into drafts")
    blog_sub = p_blog.add_subparsers(dest="blog_command", required=True)
    p_scan = blog_sub.add_parser(
        "scan", help="scan source feeds and queue new drafts (never posts)"
    )
    p_scan.add_argument("--json", action="store_true", help="print the scan summary as JSON")
    p_scan.add_argument(
        "--source",
        action="append",
        metavar="NAME",
        help="only scan this source name (repeatable)",
    )
    p_scan.add_argument(
        "--limit",
        type=int,
        default=None,
        help="max new drafts per source (default: blog.max_scan)",
    )
    p_scan.set_defaults(func=_cmd_blog_scan)

    p_localize = blog_sub.add_parser(
        "localize-images",
        help="copy still-remote non-source images into the local store (never renders)",
    )
    p_localize.add_argument(
        "--draft",
        action="append",
        metavar="ID",
        help="only this draft id (repeatable; default: all open drafts)",
    )
    p_localize.add_argument("--limit", type=int, default=None, help="max drafts to process")
    p_localize.add_argument("--json", action="store_true", help="print the summary as JSON")
    p_localize.set_defaults(func=_cmd_blog_localize)

    p_masthead = blog_sub.add_parser(
        "masthead",
        help="fill publish.mastheads.default into draft captions that lack one (never posts)",
    )
    p_masthead.add_argument(
        "--draft",
        action="append",
        metavar="ID",
        help="only this draft id (repeatable; default: all open drafts)",
    )
    p_masthead.add_argument("--limit", type=int, default=None, help="max drafts to update")
    p_masthead.add_argument("--json", action="store_true", help="print the summary as JSON")
    p_masthead.set_defaults(func=_cmd_blog_masthead)

    p_backfill = blog_sub.add_parser(
        "backfill-destinations",
        help="union queued drafts onto publish.destinations (never removes)",
    )
    p_backfill.add_argument(
        "--draft",
        action="append",
        metavar="ID",
        help="only this draft id (repeatable; default: all drafts)",
    )
    p_backfill.add_argument("--limit", type=int, default=None, help="max drafts to update")
    p_backfill.add_argument("--json", action="store_true", help="print the summary as JSON")
    p_backfill.set_defaults(func=_cmd_blog_backfill_destinations)

    p_publish = blog_sub.add_parser(
        "publish",
        help="post the approved queue now, without waiting for a scheduled slot (never approves)",
    )
    p_publish.add_argument(
        "--limit",
        type=int,
        default=None,
        help="max drafts to post (default: publish.post_per_slot)",
    )
    p_publish.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would post without sending anything",
    )
    p_publish.add_argument("--json", action="store_true", help="print the summary as JSON")
    p_publish.set_defaults(func=_cmd_blog_publish)

    p_queue = blog_sub.add_parser(
        "queue", help="show the approved post queue in the order it will post"
    )
    p_queue.add_argument(
        "--reset",
        action="store_true",
        help="clear every manual position first, restoring the oldest-first order",
    )
    p_queue.add_argument("--json", action="store_true", help="print the queue as JSON")
    p_queue.set_defaults(func=_cmd_blog_queue)

    p_move = blog_sub.add_parser(
        "move", help="move one approved draft in the post queue (never posts)"
    )
    p_move.add_argument("draft", metavar="ID", help="the draft id to move")
    p_move.add_argument(
        "direction", choices=("up", "down", "top", "bottom"), help="where to move it"
    )
    p_move.set_defaults(func=_cmd_blog_move)

    p_topics = blog_sub.add_parser(
        "topics", help="list the idea-seed systems original posts are drawn from"
    )
    p_topics.add_argument("--json", action="store_true", help="print the topics as JSON")
    p_topics.set_defaults(func=_cmd_blog_topics)

    p_add_idea = blog_sub.add_parser(
        "add-idea",
        help="queue one original-post idea by hand (never posts)",
    )
    p_add_idea.add_argument("title", help="the idea, as the post's hook or angle")
    p_add_idea.add_argument("--topic", default="", help="the system/theme it belongs to")
    p_add_idea.add_argument("--excerpt", default="", help="a short outline for the caption")
    p_add_idea.add_argument("--json", action="store_true", help="print the summary as JSON")
    p_add_idea.set_defaults(func=_cmd_blog_add_idea)

    p_serve = sub.add_parser(
        "serve",
        help="run the feed dashboard + draft review UI + scheduled refresh/scan/posting",
    )
    p_serve.add_argument("--host", default="0.0.0.0", help="bind address (default: 0.0.0.0)")
    p_serve.add_argument("--port", type=int, default=8080, help="bind port (default: 8080)")
    p_serve.add_argument(
        "--refresh-at",
        nargs="+",
        default=["07:00", "19:00"],
        metavar="HH:MM",
        help="daily refresh times, container-local (default: 07:00 19:00)",
    )
    p_serve.add_argument(
        "--boot-refresh", action="store_true", help="refresh once shortly after startup"
    )
    p_serve.add_argument(
        "--scan-at",
        nargs="+",
        default=None,
        metavar="HH:MM",
        help="daily source-scan times, container-local (default: blog.scan_at)",
    )
    p_serve.add_argument(
        "--boot-scan", action="store_true", help="scan source feeds once shortly after startup"
    )
    p_serve.add_argument(
        "--publish-at",
        nargs="+",
        default=None,
        metavar="HH:MM",
        help=(
            "daily posting times for approved drafts, container-local "
            "(default: publish.post_at); a slot may be a window HH:MM-HH:MM"
        ),
    )
    p_serve.set_defaults(func=_cmd_serve)

    return parser.parse_args(argv)


def _load_config(args: argparse.Namespace) -> dict:
    cfg = load_config(args.config)
    validate(cfg)
    return cfg


def _page_id(args: argparse.Namespace, cfg: dict) -> str:
    page_id = (args.page_id or cfg["destinations"]["facebook"].get("account_id") or "").strip()
    if not page_id:
        raise ValueError(
            "no page id: set destinations.facebook.account_id in config.yaml, pass "
            "--page-id, or run `whoami` to list the pages the token can manage"
        )
    return page_id


def _cmd_destinations(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    enabled = set(cfg.get("publish", {}).get("destinations", []) or [])
    for name in destination_names():
        publisher = publisher_for(name, cfg)
        state = "configured" if publisher.configured() else "not configured"
        routed = "routed" if name in enabled else "not routed"
        print(f"{name}: {publisher.label or name} — {state}, {routed}")
    return 0


def _cmd_whoami(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    try:
        api = api_from_config(cfg, args.token)
    except ValueError as exc:
        print(f"whoami: {exc}", file=sys.stderr)
        return 2
    me = api.me()
    print(f"Token owner: {me.get('name', '?')} (id {me.get('id', '?')})")
    pages = api.managed_pages()
    if not pages:
        print("  No pages this token can manage (need pages_show_list permission).")
        return 0
    print("Pages:")
    for page in pages:
        print(f"  - {page.get('name', '?')} (id {page.get('id', '?')})")
    print("Set destinations.facebook.account_id in config.yaml to one of these ids.")
    return 0


def _cmd_feed(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    limit = args.limit or int(cfg["feed"]["limit"])
    try:
        page_id = _page_id(args, cfg)
        api = api_from_config(cfg, args.token)
        raw_items = api.page_feed(page_id, limit)
    except ValueError as exc:
        print(f"feed: {exc}", file=sys.stderr)
        return 2
    except ApiError as exc:
        print(f"feed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(raw_items, indent=2, ensure_ascii=False))
    else:
        print(format_feed_md(parse_feed_response({"data": raw_items})))
    return 0


def _cmd_post(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    if not args.message and not args.photo:
        print("post: provide --message and/or --photo", file=sys.stderr)
        return 2
    if args.photo and args.link:
        print("post: --link cannot be combined with --photo", file=sys.stderr)
        return 2
    try:
        page_id = _page_id(args, cfg)
        api = api_from_config(cfg, args.token)
    except ValueError as exc:
        print(f"post: {exc}", file=sys.stderr)
        return 2
    private = bool(cfg.get("publish", {}).get("private", False))
    if args.photo:
        target = f"{page_id}/photos"
        params = {"url": args.photo}
        if args.message:
            params["caption"] = args.message
    else:
        target = f"{page_id}/feed"
        params = {"message": args.message}
        if args.link:
            params["link"] = args.link
    if private:
        params["published"] = "false"
    if args.dry_run:
        label = " (unpublished)" if private else ""
        print(f"dry-run: would POST to /{target}{label}")
        print(json.dumps(params, indent=2, ensure_ascii=False))
        return 0
    try:
        if args.photo:
            # Read the image here and upload the bytes: handing Graph the URL
            # only works while that host serves it anonymously (see media).
            image, filename, content_type = media.load(cfg, args.photo)
            resp = api.create_photo_post(
                page_id,
                args.message or "",
                image,
                filename=filename,
                content_type=content_type,
                published=not private,
            )
        else:
            resp = api.create_post(page_id, args.message, args.link, published=not private)
    except (ApiError, media.MediaError) as exc:
        print(f"post: {exc}", file=sys.stderr)
        return 1
    post_id = str(resp.get("post_id") or resp.get("id", ""))
    print(f"Posted{' privately (unpublished)' if private else ''}. id: {post_id}")
    # Page post ids are "<page>_<post>"; the underscore form is the permalink.
    if "_" in post_id:
        print(f"Permalink: https://www.facebook.com/{post_id}")
    return 0


def _cmd_refresh(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    try:
        result = refresh_feed(cfg)
    except ValueError as exc:
        print(f"refresh: {exc}", file=sys.stderr)
        return 2
    except ApiError as exc:
        print(f"refresh: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        where = getattr(exc, "filename", None) or "the feed directory"
        print(f"refresh: cannot write {where}: {exc.strerror or exc}", file=sys.stderr)
        print(_DATA_DIR_HINT, file=sys.stderr)
        return 1
    print(f"Cached {result['count']} post(s) -> {result['html_file']}")
    return 0


def _cmd_blog_scan(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    try:
        result = scan_sources(cfg, limit=args.limit, source_names=args.source)
    except ValueError as exc:
        print(f"blog scan: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        where = getattr(exc, "filename", None) or "the drafts directory"
        print(f"blog scan: cannot write {where}: {exc.strerror or exc}", file=sys.stderr)
        print(_DATA_DIR_HINT, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        skipped_old = int(result.get("skipped_old", 0))
        print(
            f"Queued {result['added']} new draft(s) from {result['sources']} source(s); "
            f"{result['total_drafts']} total."
        )
        if skipped_old:
            print(f"Skipped {skipped_old} item(s) older than blog.max_age_days.")
        for item in result["items"]:
            print(f"  - {item['id']}: {item['title'] or '(untitled)'}")
    for err in result["errors"]:
        print(f"  ! {err['source']}: {err['error']}", file=sys.stderr)
    return 1 if result["errors"] else 0


def _cmd_blog_localize(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    try:
        result = localize_images(cfg, draft_ids=args.draft, limit=args.limit)
    except ValueError as exc:
        print(f"blog localize-images: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        where = getattr(exc, "filename", None) or "the drafts directory"
        print(f"blog localize-images: cannot write {where}: {exc.strerror or exc}", file=sys.stderr)
        print(_DATA_DIR_HINT, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(
            f"Moved {result['localized']} image(s) into the local store "
            f"({result['candidates']} candidate(s))."
        )
        for draft_id in result["ids"]:
            print(f"  - {draft_id}")
        for error in result["errors"]:
            print(f"  ! {error['error']}", file=sys.stderr)
    return 0


def _cmd_blog_masthead(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    try:
        result = apply_masthead(cfg, draft_ids=args.draft, limit=args.limit)
    except ValueError as exc:
        print(f"blog masthead: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        where = getattr(exc, "filename", None) or "the drafts directory"
        print(f"blog masthead: cannot write {where}: {exc.strerror or exc}", file=sys.stderr)
        print(_DATA_DIR_HINT, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Filled masthead on {result['updated']} draft(s): {result['masthead']!r}")
        for draft_id in result["ids"]:
            print(f"  - {draft_id}")
    return 0


def _cmd_blog_backfill_destinations(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    try:
        result = backfill_destinations(cfg, draft_ids=args.draft, limit=args.limit)
    except ValueError as exc:
        print(f"blog backfill-destinations: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        where = getattr(exc, "filename", None) or "the drafts directory"
        print(
            f"blog backfill-destinations: cannot write {where}: {exc.strerror or exc}",
            file=sys.stderr,
        )
        print(_DATA_DIR_HINT, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Backfilled {result['updated']} draft(s) onto {', '.join(result['destinations'])}.")
        for draft_id in result["ids"]:
            print(f"  - {draft_id}")
    return 0


def _cmd_blog_publish(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    try:
        result = publish_scheduled(cfg, limit=args.limit, dry_run=args.dry_run)
    except ValueError as exc:
        print(f"blog publish: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        where = getattr(exc, "filename", None) or "the drafts directory"
        print(f"blog publish: cannot write {where}: {exc.strerror or exc}", file=sys.stderr)
        print(_DATA_DIR_HINT, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        verb = "Would post" if args.dry_run else "Posted"
        print(
            f"{verb} {len(result['posted'])} draft(s); "
            f"{len(result['skipped'])} skipped, {len(result['errors'])} error(s)."
        )
        for entry in result["posted"]:
            print(f"  - {entry['id']}: {entry['permalink'] or entry['post_id']}")
    for entry in result["skipped"]:
        print(f"  · skipped {entry['id']}: {entry['reason']}", file=sys.stderr)
    for entry in result["errors"]:
        print(f"  ! {entry['id']}: {entry['error']}", file=sys.stderr)
    return 1 if result["errors"] else 0


def _cmd_blog_queue(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    try:
        if args.reset:
            cleared = reset_queue_order(cfg)
            if not args.json:
                print(f"Cleared the manual order on {cleared} draft(s).")
        rows = queue_view(cfg)
    except OSError as exc:
        where = getattr(exc, "filename", None) or "the drafts directory"
        print(f"blog queue: cannot write {where}: {exc.strerror or exc}", file=sys.stderr)
        print(_DATA_DIR_HINT, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    if not rows:
        print("The post queue is empty — nothing approved to post.")
        return 0
    print(f"{len(rows)} approved draft(s), in posting order:")
    for position, row in enumerate(rows, start=1):
        print(f"  {position}. {row['title']}\n     {row['id']}")
    return 0


def _cmd_blog_move(args: argparse.Namespace) -> int:
    cfg = _load_config(args)
    try:
        queue = move_in_queue(cfg, args.draft, args.direction)
    except ValueError as exc:
        print(f"blog move: {exc}", file=sys.stderr)
        return 2
    position = next((i + 1 for i, draft in enumerate(queue) if draft.id == args.draft), 0)
    print(f"Moved {args.draft} to position {position} of {len(queue)}.")
    return 0


def _cmd_blog_topics(args: argparse.Namespace) -> int:
    """List the idea-seed systems (ideas.topics_file) — themes, not articles."""
    cfg = _load_config(args)
    topics = load_topics(cfg)
    if args.json:
        print(json.dumps(topics, indent=2, ensure_ascii=False))
        return 0
    if not topics:
        print(f"No idea topics configured. Add systems to {ideas_topics_path(cfg)}.")
        return 0
    print(f"{len(topics)} idea seed(s):")
    for topic in topics:
        suffix = f"  ({topic['url']})" if topic.get("url") else ""
        print(f"  - {topic['name']}{suffix}")
    return 0


def _cmd_blog_add_idea(args: argparse.Namespace) -> int:
    """Queue one original-post idea by hand (a seed for the normal caption flow)."""
    cfg = _load_config(args)
    try:
        result = queue_ideas(
            cfg,
            [{"title": args.title, "topic": args.topic, "excerpt": args.excerpt}],
        )
    except ValueError as exc:
        print(f"blog add-idea: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        where = getattr(exc, "filename", None) or "the drafts directory"
        print(f"blog add-idea: cannot write {where}: {exc.strerror or exc}", file=sys.stderr)
        print(_DATA_DIR_HINT, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if result["added"]:
        print(f"Queued idea {result['drafts'][0]['id']!r}: {args.title}")
        return 0
    reason = result["skipped_ideas"][0]["reason"] if result["skipped_ideas"] else "not added"
    print(f"Skipped: {reason}", file=sys.stderr)
    return 1


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .web import create_app

    app = create_app(
        config_path=args.config,
        refresh_at=args.refresh_at,
        boot_refresh=args.boot_refresh,
        scan_at=args.scan_at,
        boot_scan=args.boot_scan,
        post_at=args.publish_at,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
