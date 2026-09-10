"""social-bot command line: `whoami`, `feed`, `post`, `refresh`, `blog scan`, `serve`."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from . import __version__
from .api import ApiError, api_from_config
from .config import load_config, validate
from .draft_pipeline import scan_sources
from .feed import format_feed_md, parse_feed_response
from .refresh import refresh_feed

# Shown when the state directory can't be written (a common Docker uid mismatch).
_DATA_DIR_HINT = (
    "hint: the state directory must be writable by this process. The container "
    "runs as uid 1000 — on the host run `sudo chown -R 1000:1000 data`."
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="social-bot", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", type=pathlib.Path, help="config.yaml path (default: project root)")
    parser.add_argument(
        "--token",
        help="Page access token (overrides SOCIAL_BOT_TOKEN and config.yaml)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_whoami = sub.add_parser("whoami", help="check the token and list pages it can manage")
    p_whoami.set_defaults(func=_cmd_whoami)

    p_feed = sub.add_parser("feed", help="fetch the page feed (read-only)")
    p_feed.add_argument("--page-id", help="override graph.page_id from config.yaml")
    p_feed.add_argument("--limit", type=int, default=None, help="posts to show (default: feed.limit)")
    p_feed.add_argument("--json", action="store_true", help="print the raw Graph API JSON instead")
    p_feed.set_defaults(func=_cmd_feed)

    p_post = sub.add_parser("post", help="post a status, link, or photo to the page")
    p_post.add_argument("--page-id", help="override graph.page_id from config.yaml")
    p_post.add_argument("--message", help="post text (required unless --photo is given)")
    p_post.add_argument("--link", help="optional link attached to the post")
    p_post.add_argument(
        "--photo",
        help="publish a photo from a public image URL; --message becomes its caption",
    )
    p_post.add_argument("--dry-run", action="store_true", help="print the request without sending it")
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

    p_serve = sub.add_parser(
        "serve", help="run the feed dashboard + draft review UI + scheduled refresh/scan"
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
    p_serve.set_defaults(func=_cmd_serve)
    return parser.parse_args(argv)


def _load_config(args: argparse.Namespace) -> dict:
    cfg = load_config(args.config)
    validate(cfg)
    return cfg


def _page_id(args: argparse.Namespace, cfg: dict) -> str:
    page_id = (args.page_id or cfg["graph"]["page_id"] or "").strip()
    if not page_id:
        raise ValueError(
            "no page id: set graph.page_id in config.yaml, pass --page-id, "
            "or run `whoami` to list the pages the token can manage"
        )
    return page_id


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
    print("Set graph.page_id in config.yaml to one of these ids.")
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
            resp = api.create_photo_post(
                page_id, args.message or "", args.photo, published=not private
            )
        else:
            resp = api.create_post(
                page_id, args.message, args.link, published=not private
            )
    except ApiError as exc:
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
        print(
            f"Queued {result['added']} new draft(s) from {result['sources']} source(s); "
            f"{result['total_drafts']} total."
        )
        for item in result["items"]:
            print(f"  - {item['id']}: {item['title'] or '(untitled)'}")
    for err in result["errors"]:
        print(f"  ! {err['source']}: {err['error']}", file=sys.stderr)
    return 1 if result["errors"] else 0


def _cmd_serve(args: argparse.Namespace) -> int:
    from .web import create_app

    import uvicorn

    app = create_app(
        config_path=args.config,
        refresh_at=args.refresh_at,
        boot_refresh=args.boot_refresh,
        scan_at=args.scan_at,
        boot_scan=args.boot_scan,
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
