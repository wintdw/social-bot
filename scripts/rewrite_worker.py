"""Run the Command Code rewriter for drafts requested from /review.

The operator app never runs an AI agent itself: the buttons on /review/{id} only
*mark* the draft. This host-side worker polls ``GET /api/rewrite-queue``, runs the
Command Code CLI headlessly for each request (``commandcode -p``), and posts the
result back — which clears the request. A failure is posted to
``POST /api/drafts/{id}/rewrite-error`` so the draft page can show it, instead of
the request waiting forever.

Two kinds of request ride that one queue, told apart by the draft's
``rewrite_mode``:

``caption``
    "Rewrite with Command Code" — the whole rewrite (``build_prompt``, the DNA and
    voice menu included), posted back to ``POST /api/drafts/{id}/rewrite``.
``image``
    "Regenerate image prompt" — the caption is already settled, only a fresh
    ``image_prompt`` is wanted (``build_image_prompt``, a much smaller task), posted
    back to ``POST /api/drafts/{id}/image-prompt``, which stores it and leaves the
    caption, the operator's chosen ``image_style`` and the draft's state alone.
    Nothing is rendered: the operator presses "Regenerate image" when it reads right.

**Why a worker and not the app.** Command Code and its auth live on the host (the
container image is python-slim with no Node), and keeping the agent outside the
web process keeps its permission model where a human can see it. Headless runs
need no ``--yolo``: the rewriter only *reads* the brief and *prints* JSON, so the
default permissions (reads free, writes/shell blocked) are enough — nothing is
written and no shell runs.

    python scripts/rewrite_worker.py              # poll forever
    python scripts/rewrite_worker.py --once        # drain the queue and exit
    python scripts/rewrite_worker.py --draft <id>  # one requested draft
    python scripts/rewrite_worker.py --dry-run     # print prompts, call nothing

Exit codes: 0 ok, 1 a run/HTTP failure, 2 usage/config error.
"""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

# Work from a bare checkout too (pytest gets this via the test config).
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from social_bot.config import load_config  # noqa: E402
from social_bot.draft_pipeline import rewrite_config  # noqa: E402
from social_bot.drafts import REWRITE_IMAGE  # noqa: E402


class WorkerError(Exception):
    """A run or HTTP failure the worker reports back and keeps going from."""


def _auth_header(cfg: dict) -> dict[str, str]:
    """HTTP basic auth for the deployed UI, when credentials.yaml supplies it.

    The app itself is unauthenticated (it sits behind nginx), so this is only
    needed when ``rewrite.api_base`` points at the public host rather than
    localhost. An unused Authorization header is harmless.
    """
    site = cfg.get("site") or {}
    user = str(site.get("user") or "").strip()
    password = str(site.get("password") or "").strip()
    if not (user and password):
        return {}
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _request_json(cfg: dict, method: str, url: str, payload: dict | None = None) -> dict:
    """One JSON request against the operator app; raises WorkerError on failure."""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    for name, value in _auth_header(cfg).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=30.0) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace").strip()
        raise WorkerError(f"{method} {url} -> HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise WorkerError(f"{method} {url} failed: {exc}") from exc


def _bullet_list(values) -> str:
    return ", ".join(str(value) for value in (values or [])) or "(none configured)"


def _style_block(payload: dict) -> str:
    """Every configured treatment's own brief, as prompt headings.

    The briefs, not just their key names: a prompt has to *serve* the style it
    picks, and a name alone cannot say what that style draws.
    """
    briefs = payload.get("image_style_briefs") or {}
    return (
        "\n\n".join(f"### image_style: {key}\n{text}" for key, text in briefs.items() if text)
        or "(no treatment briefs configured — follow the DNA §9.2 table)"
    )


def _recent_images_block(payload: dict) -> str:
    """The image prompts already written, newest first — what not to repeat."""
    recent = payload.get("recent_images") or []
    return (
        "\n".join(
            f"- [{item.get('image_style') or 'default'}] {item.get('image_prompt')}"
            for item in recent
            if item.get("image_prompt")
        )
        or "(none)"
    )


def build_prompt(payload: dict, draft: dict) -> str:
    """The single self-contained task handed to one headless Command Code run.

    Everything rides in the prompt (the DNA, the voice menu, the recent captions,
    the draft) so the run needs no tools and no network: it only reads its input
    and prints the rewrite JSON, which the worker parses and posts back.
    """
    voices = payload.get("voices") or {}
    voice_block = (
        "\n\n".join(f"### voice: {key}\n{text}" for key, text in voices.items() if text)
        or "(no voice menu configured)"
    )
    recent = payload.get("recent") or []
    recent_block = (
        "\n\n".join(
            f"--- recent caption ({item.get('id')}) ---\n{item.get('caption', '')}"
            for item in recent
            if item.get("caption")
        )
        or "(none)"
    )
    mastheads = payload.get("mastheads") or {}
    style_block = _style_block(payload)
    recent_images_block = _recent_images_block(payload)
    return (
        "You are the Atento rewriter. Rewrite exactly ONE draft into a Facebook "
        "Page caption, following the brand brief and the chosen voice below.\n\n"
        "Reply with ONLY a single JSON object — no prose, no markdown fence — with "
        "exactly these keys:\n"
        '  "caption":      Vietnamese text (no hashtags, no URL/domain inside it). '
        "Line 1 is ONE series masthead, then a blank line, then the hook; the call "
        "to action goes at the end.\n"
        '  "hashtags":     array of 2-4 strings, each starting with "#", including '
        "#Atento and #fromfoundationtoexcellence plus one topic tag.\n"
        '  "cta":          reviewer-only note; the same call to action must appear '
        "in the caption.\n"
        '  "commentary":   2-4 sentences for the reviewer: voice, format/hook, '
        "drama level, anything to confirm.\n"
        '  "image_prompt": English; ONE concrete visual concept for this post, '
        "written to serve the image_style you chose — read that style's brief "
        "below (it says what the style draws, and `diagram` says how to name its "
        "labels). Also the image's alt text.\n"
        '  "image_style":  exactly one of: '
        f"{_bullet_list(payload.get('image_styles'))}\n"
        '  "voice":        exactly one of: '
        f"{_bullet_list(payload.get('voice_choices'))}\n\n"
        "Hard rules:\n"
        f"- Pick exactly ONE masthead, verbatim, as line 1 — from: "
        f"{_bullet_list(mastheads.get('choices'))} (default "
        f"{mastheads.get('default') or 'none'}).\n"
        "- Write in ONE voice only; do not mix registers.\n"
        "- Do NOT imitate the recent captions' openers, closers, or vocabulary.\n"
        "- Do NOT reuse a subject or a composition from the recent images — pick "
        "something different for THIS post's idea.\n"
        "- No hype, no invented facts, no engagement bait, no domain in the caption.\n\n"
        "=== RECENT CAPTIONS (avoid repeating) ===\n"
        f"{recent_block}\n\n"
        "=== RECENT IMAGES (avoid repeating these subjects) ===\n"
        f"{recent_images_block}\n\n"
        "=== BRAND BRIEF (Atento DNA) ===\n"
        f"{payload.get('dna') or '(no DNA configured)'}\n\n"
        "=== VOICE MENU (pick one key) ===\n"
        f"{voice_block}\n\n"
        "=== IMAGE STYLE BRIEFS (write the image_prompt to serve the one you pick) ===\n"
        f"{style_block}\n\n"
        "=== DRAFT TO REWRITE ===\n"
        f"{json.dumps(draft, ensure_ascii=False, indent=2)}\n"
    )


def build_image_prompt(payload: dict, draft: dict) -> str:
    """The task for a *prompt-only* rewrite: a fresh image prompt, caption untouched.

    Much smaller than ``build_prompt``: the caption is not being rewritten, so the
    DNA, the voice menu and the masthead choices are all beside the point. What
    matters is what the picture must be — the treatment briefs, the subjects
    already used, and this post's own caption — which is exactly the pair the
    caption rewrite was missing when it illustrated three posts the same way.

    The treatment is **not** the agent's to pick here, unlike ``build_prompt``: the
    operator chose it on /review/{id} and it is the post's own ``image_style``, so
    the task is to write a subject that serves *that* brief. The result carries no
    ``image_style`` at all — ``receive_image_prompt`` would ignore one — and asking
    for it only invited the agent to overrule the pick.
    """
    return (
        "You are the Atento image rewriter. Write a NEW image prompt for exactly ONE "
        "post. Its caption is already written and approved: do not rewrite it, quote "
        "it, or comment on it.\n\n"
        "The image style is already chosen for this post — it is the `image_style` "
        "field in the post below — so do NOT pick one. Write the prompt for that "
        "style, serving its brief (it says what the style draws, and `diagram` says "
        "how to name its labels).\n\n"
        "Reply with ONLY a single JSON object — no prose, no markdown fence — with "
        "exactly this one key:\n"
        '  "image_prompt": English; ONE concrete visual concept for this post, '
        "written to serve the post's image_style. Also the image's alt text.\n\n"
        "Hard rules:\n"
        "- Depict THIS post's idea as something you can see, not a paraphrase of the "
        "caption.\n"
        "- Serve the post's image_style brief; do not restate or contradict it, and "
        "do not send an image_style of your own.\n"
        "- Do NOT reuse a subject or a composition from the recent images below.\n\n"
        "=== RECENT IMAGES (avoid repeating these subjects) ===\n"
        f"{_recent_images_block(payload)}\n\n"
        "=== IMAGE STYLE BRIEFS (write the image_prompt to serve the post's own) ===\n"
        f"{_style_block(payload)}\n\n"
        "=== POST (its image is being redone) ===\n"
        f"{json.dumps(draft, ensure_ascii=False, indent=2)}\n"
    )


def extract_json(text: str) -> dict:
    """The rewrite object from the model's final text (tolerates a code fence)."""
    text = str(text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    try:
        parsed = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise WorkerError("the rewriter returned no JSON object") from None
        try:
            parsed = json.loads(text[start : end + 1])
        except ValueError as exc:
            raise WorkerError(f"could not parse the rewriter output: {exc}") from exc
    if not isinstance(parsed, dict):
        raise WorkerError("the rewriter output was not a JSON object")
    return parsed


def run_commandcode(settings: dict, prompt: str) -> dict:
    """Run one headless Command Code rewrite and return the parsed JSON.

    The prompt is piped on stdin (``-p`` with no query argument) so a long
    self-contained task needs no shell quoting. Reads are free in headless mode,
    so no ``--yolo``: the run cannot write files or run shell commands.
    """
    command = str(settings.get("command") or "commandcode").strip() or "commandcode"
    args = [
        command,
        "-p",
        "--output-format",
        "json",
        "--skip-onboarding",
        "--max-turns",
        str(int(settings.get("max_turns", 40))),
        "-t",  # auto-trust the project so an unattended run never blocks
    ]
    model = str(settings.get("model") or "").strip()
    if model:
        args += ["-m", model]
    try:
        proc = subprocess.run(
            args,
            input=prompt,
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=float(settings.get("timeout_seconds", 600.0)),
        )
    except FileNotFoundError as exc:
        raise WorkerError(f"command not found: {command!r} ({exc})") from exc
    except subprocess.TimeoutExpired as exc:
        raise WorkerError(f"{command} timed out after {settings.get('timeout_seconds')}s") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = " / ".join(detail[-3:]) if detail else "no output"
        raise WorkerError(f"{command} exited {proc.returncode}: {tail}")

    final, subtype = "", "success"
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            frame = json.loads(line)
        except ValueError:
            continue  # progress/warning noise; the result line is the one we want
        if isinstance(frame, dict) and frame.get("type") == "result":
            subtype = str(frame.get("subtype") or "success")
            final = str(frame.get("finalText") or "")
    if subtype != "success":
        raise WorkerError(f"the rewriter run ended early ({subtype})")
    return extract_json(final)


def process_once(cfg: dict, *, draft_id: str = "", dry_run: bool = False) -> int:
    """Handle every pending request once; returns how many were rewritten."""
    settings = rewrite_config(cfg)
    base = str(settings.get("api_base") or "").rstrip("/")
    payload = _request_json(cfg, "GET", f"{base}/api/rewrite-queue")
    drafts = payload.get("drafts") or []
    if draft_id:
        drafts = [draft for draft in drafts if draft.get("id") == draft_id]
        if not drafts:
            raise WorkerError(f"draft {draft_id!r} is not in the rewrite queue")
    if not drafts:
        return 0

    done = 0
    for draft in drafts:
        ident = str(draft.get("id") or "")
        # Two kinds of request share this queue: a full rewrite, and a prompt-only
        # one ("the caption is fine, the picture is not"), which is the same run
        # with a smaller prompt and a different endpoint to post back to.
        image_only = draft.get("rewrite_mode") == REWRITE_IMAGE
        prompt = build_image_prompt(payload, draft) if image_only else build_prompt(payload, draft)
        task = f"a new image prompt for {ident}" if image_only else ident
        endpoint = "image-prompt" if image_only else "rewrite"
        if dry_run:
            print(f"[rewriter] would rewrite {task} ({len(prompt)} chars of prompt)")
            continue
        print(f"[rewriter] rewriting {task}…", flush=True)
        try:
            rewrite = run_commandcode(settings, prompt)
            _request_json(cfg, "POST", f"{base}/api/drafts/{ident}/{endpoint}", rewrite)
            print(
                f"[rewriter] {ident}: {'image prompt' if image_only else 'rewrite'} posted",
                flush=True,
            )
            done += 1
        except WorkerError as exc:
            print(f"[rewriter] {ident} failed: {exc}", file=sys.stderr, flush=True)
            try:
                _request_json(
                    cfg, "POST", f"{base}/api/drafts/{ident}/rewrite-error", {"error": str(exc)}
                )
            except WorkerError as post_exc:
                print(f"[rewriter] could not record the failure: {post_exc}", file=sys.stderr)
    return done


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="rewrite_worker",
        description="Run the Command Code rewriter for drafts requested on /review.",
        epilog="Exit codes: 0 ok, 1 a run/HTTP failure, 2 usage/config error.",
    )
    parser.add_argument("--config", help="path to config.yaml (default: project root)")
    parser.add_argument("--draft", default="", help="rewrite only this draft id")
    parser.add_argument("--once", action="store_true", help="drain the queue and exit")
    parser.add_argument("--dry-run", action="store_true", help="print what would run; call nothing")
    args = parser.parse_args(argv[1:])

    try:
        cfg = load_config(args.config)
    except Exception as exc:  # a bad config is a usage error, not a crash
        print(f"rewrite_worker: {exc}", file=sys.stderr)
        return 2

    settings = rewrite_config(cfg)
    if not settings:
        print("rewrite_worker: no `rewrite` block in config", file=sys.stderr)
        return 2

    if args.draft or args.once or args.dry_run:
        try:
            count = process_once(cfg, draft_id=args.draft, dry_run=args.dry_run)
        except WorkerError as exc:
            print(f"rewrite_worker: {exc}", file=sys.stderr)
            return 1
        if not args.dry_run:
            print(f"rewrite_worker: {count} rewrite(s) posted")
        return 0

    poll = float(settings.get("poll_seconds", 15.0))
    base = str(settings.get("api_base") or "").rstrip("/")
    print(
        f"[rewriter] worker up: polling {base}/api/rewrite-queue every {poll:g}s",
        flush=True,
    )
    while True:
        try:
            process_once(cfg)
        except WorkerError as exc:  # a transient HTTP failure: log and keep polling
            print(f"[rewriter] {exc}", file=sys.stderr, flush=True)
        time.sleep(poll)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
