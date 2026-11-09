"""Upload one video to the Facebook page — the platform smoke test.

    .venv/bin/python scripts/test_video_upload.py clip.mp4 \
        --title "Video đầu tiên" --description "Bản dựng từ hyperframes."

Draft by default: the upload is real (``video_state=DRAFT``, or
``published=false`` for a feed video), visible to page admins only, and the
script then checks the id is *absent* from the page's public ``/videos`` edge.
Pass ``--public`` to publish it for real.

``--mode post`` (default) probes the ordinary feed-video upload (one multipart
POST to ``/{page}/videos``); ``--mode reel`` probes the three-step Reels flow
(open session → POST bytes to rupload → finish). Both are the calls
``FacebookPublisher`` makes. Use ``social-bot blog attach-video`` to put a clip
on a draft and post it through the pipeline.

Exit codes: 0 uploaded and verified, 1 Graph API error, 2 bad file/config.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time

# Work from a bare checkout too (pytest gets this via the test config).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from social_bot import media, video_spec  # noqa: E402
from social_bot.config import load_config  # noqa: E402
from social_bot.destinations.facebook.api import ApiError, api_from_config  # noqa: E402
from social_bot.drafts import VIDEO_MODES, VIDEO_POST, VIDEO_REEL  # noqa: E402

POLL_SECONDS = 5
POLL_ATTEMPTS = 24


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", type=pathlib.Path, help="the video to upload")
    parser.add_argument("--title", default="", help="video title (optional)")
    parser.add_argument("--description", default="", help="video description (optional)")
    parser.add_argument("--page-id", default="", help="defaults to the configured account_id")
    parser.add_argument(
        "--mode",
        choices=VIDEO_MODES,
        default=VIDEO_POST,
        help="placement: 'post' (page feed video, default) or 'reel' (Reels tab)",
    )
    parser.add_argument(
        "--public",
        action="store_true",
        help="publish for real; default is a draft (admin-only) upload",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        data = args.file.read_bytes()
    except OSError as exc:
        print(f"test_video_upload: cannot read {args.file}: {exc}", file=sys.stderr)
        return 2
    if not data:
        print(f"test_video_upload: {args.file} is empty", file=sys.stderr)
        return 2

    try:
        spec = video_spec.probe(str(args.file))
    except video_spec.SpecError as exc:
        if video_spec.find_ffprobe():
            print(f"test_video_upload: {exc}", file=sys.stderr)
            return 2
        spec = None
        print("test_video_upload: ffprobe not found — limits not checked", file=sys.stderr)
    if spec is not None:
        if args.mode == VIDEO_REEL:
            problems = video_spec.problems(spec)
            if problems:
                print(
                    "test_video_upload: will not publish as a Reel: " + "; ".join(problems),
                    file=sys.stderr,
                )
                return 2
        print(f"spec: {video_spec.summary(spec)}")

    cfg = load_config()
    page_id = args.page_id or str(
        (cfg.get("destinations", {}).get("facebook") or {}).get("account_id") or ""
    )
    if not page_id:
        print(
            "test_video_upload: no page id — set destinations.facebook.account_id", file=sys.stderr
        )
        return 2

    api = api_from_config(cfg)
    size_mb = len(data) / (1024 * 1024)
    digest = hashlib.sha256(data).hexdigest()[:16]
    print(
        f"uploading {args.file.name} as a {args.mode}: {size_mb:.2f} MB, "
        f"sha256:{digest}, page {page_id}, public={bool(args.public)}"
    )
    try:
        if args.mode == VIDEO_POST:
            uploaded = api.create_video_post(
                page_id,
                args.description,
                data,
                filename=args.file.name,
                content_type=media.video_media_type(args.file.name),
                title=args.title,
                published=bool(args.public),
            )
            print(f"upload: {json.dumps(uploaded, ensure_ascii=False)}")
            video_id = str(uploaded.get("id") or "")
            if not video_id:
                print("test_video_upload: no video id from the upload", file=sys.stderr)
                return 1
            permalink = f"https://www.facebook.com/{page_id}/videos/{video_id}/"
        else:
            state = "PUBLISHED" if args.public else "DRAFT"
            session = api.start_reel_upload(page_id)
            video_id = str(session.get("video_id") or "")
            if not video_id:
                print("test_video_upload: no video id from the upload session", file=sys.stderr)
                return 1
            print(f"session: video_id={video_id}")
            print(
                f"upload: {api.upload_reel(video_id, data, upload_url=session.get('upload_url') or '')}"
            )
            finish = api.finish_reel(
                page_id,
                video_id,
                description=args.description,
                title=args.title,
                state=state,
            )
            print(f"finish: {json.dumps(finish, ensure_ascii=False)}")
            permalink = f"https://www.facebook.com/reel/{video_id}/"
    except ApiError as exc:
        print(f"test_video_upload: upload failed: {exc}", file=sys.stderr)
        if exc.code or exc.error_type:
            print(f"  code={exc.code} type={exc.error_type} subcode={exc.subcode}", file=sys.stderr)
        return 1

    status = {}
    for attempt in range(POLL_ATTEMPTS):
        status = api.get(video_id, {"fields": "id,permalink_url,length,status"})
        phase = status.get("status", {})
        print(
            f"  {attempt}: {phase.get('video_status')} "
            f"publishing={phase.get('publishing_phase', {}).get('publish_status') or '—'}"
        )
        if phase.get("video_status") in {"ready", "error"}:
            break
        time.sleep(POLL_SECONDS)
    print(f"video: {json.dumps(status, ensure_ascii=False)}")

    if args.public:
        print(f"PUBLIC: {permalink}")
        return 0

    try:
        public_ids = {
            str(item.get("id"))
            for item in api.get(f"{page_id}/videos", {"fields": "id", "limit": 100}).get("data", [])
        }
    except ApiError as exc:
        print(f"test_video_upload: could not read the public /videos edge: {exc}", file=sys.stderr)
        return 1
    if video_id in public_ids:
        print(
            f"test_video_upload: FAIL — draft video {video_id} IS on the public edge",
            file=sys.stderr,
        )
        return 1
    print(f"draft: {video_id} is not on the page's public /videos edge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
