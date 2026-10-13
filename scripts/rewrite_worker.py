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
    voice menu included), the agent choosing the register, posted back to
    ``POST /api/drafts/{id}/rewrite``.
``caption-voice``
    "Rewrite in this voice" — the same whole rewrite, except the register is the
    one the operator picked (``build_prompt(..., voice_locked=True)``: the contract
    names that key and forbids another). Posted back to the same endpoint, where
    ``receive_rewrite`` re-asserts the pick rather than taking the run's word for it.

**Idea seeds (original posts).** The same worker also fulfils a request for
*original* post ideas ("Generate ideas" on /review, or ``blog ideas --request``).
That is a different input from the source feeds: ``GET /api/ideas`` carries the
theme systems (``ideas.topics_file`` — Elasticsearch, ClickHouse, …), the titles
already queued, the DNA and the recent captions, and a ``requested`` flag the
worker polls. When set, ``build_ideas_prompt`` asks for a batch of angles drawn
from those systems' own architecture, and the result is posted to
``POST /api/ideas`` — each idea lands as an ``extracted`` draft awaiting the
normal rewrite and a human approval. No article is fetched or reposted.

**The operator's own voice.** Before a caption task runs, the worker asks
``social_bot.voice`` for the operator's own messages closest to the draft and
passes them — with the learned ``profile.md`` — into ``build_prompt`` as
``MY VOICE``. The corpus is a local directory of JSONL, searched by BM25 and/or a
vector index (``voice.backend``); the ``vector``/``hybrid`` backends need the
optional ``[voice]`` extra. It is style, not substance: the agent matches the
diction and rhythm and never lifts a fact or a line. Retrieval is an enhancement —
a missing corpus or extra only makes the prompt shorter.

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

from social_bot import voice  # noqa: E402
from social_bot.config import load_config  # noqa: E402
from social_bot.draft_pipeline import rewrite_config  # noqa: E402
from social_bot.drafts import REWRITE_CAPTION_VOICE  # noqa: E402


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


def _my_voice(cfg: dict, draft: dict) -> str:
    """The operator's own voice for one draft, or '' — never fails a rewrite.

    ``voice.examples_block`` already swallows retrieval failures and returns ''
    (voice is an enhancement, like image generation, never a gate). This wrapper
    only makes the *silent* case visible: when the block is switched on but
    nothing came back — an empty corpus, a missing ``[voice]`` extra, or no
    matches — the operator should see why the prompt got shorter.
    """
    if not voice.enabled(cfg):
        return ""
    block = voice.examples_block(cfg, draft)
    if not block:
        print(
            f"[rewriter] no voice examples for {draft.get('id')} "
            "(empty corpus, no matches, or retrieval failed)",
            file=sys.stderr,
            flush=True,
        )
    return block


def build_prompt(
    payload: dict, draft: dict, *, voice_locked: bool = False, my_voice: str = ""
) -> str:
    """The single self-contained task handed to one headless Command Code run.

    Everything rides in the prompt (the DNA, the voice menu, the recent captions,
    the draft) so the run needs no tools and no network: it only reads its input
    and prints the rewrite JSON, which the worker parses and posts back.

    ``voice_locked`` is "Rewrite in this voice": the operator picked a register on
    /review/{id}, so the caption's voice is not the agent's to choose — the menu
    stays (the chosen register's own brief and samples *are* the text it writes
    from), but the contract names that one key and a hard rule forbids substituting
    another. Absent a key on the draft there is nothing to hold, so the wording
    falls back to the free choice.

    ``my_voice`` is the operator's *own* voice — the learned ``profile.md`` plus
    the real messages they wrote that are closest to this draft
    (``voice.examples_block``). It is style, never substance: the section is added
    only when there is something to add, and the hard rules say to copy the
    diction and rhythm, not the facts.

    The division of labour, once all four are in the prompt: the **DNA** owns the
    structure and the output contract, the **voice menu** owns which register,
    ``MY VOICE`` owns how the sentences actually sound, and the **draft** owns the
    facts.
    """
    voices = payload.get("voices") or {}
    voice_block = (
        "\n\n".join(f"### voice: {key}\n{text}" for key, text in voices.items() if text)
        or "(no voice menu configured)"
    )
    locked_voice = str(draft.get("voice") or "").strip() if voice_locked else ""
    voice_contract = (
        f'  "voice":        exactly "{locked_voice}" — the reviewer chose it; do not pick another'
        if locked_voice
        else '  "voice":        exactly one of: ' + _bullet_list(payload.get("voice_choices"))
    )
    voice_rule = (
        f'- Write in the reviewer\'s chosen voice "{locked_voice}" — do not '
        "substitute another register from the menu.\n"
        if locked_voice
        else ""
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
    # The operator's own voice, when there is any: omitted entirely otherwise, so a
    # run without a corpus reads exactly as it did before this existed.
    my_voice_rule = (
        "- Match the VOICE of the real messages in MY VOICE below — diction, "
        "rhythm, teencode level, address terms — but they are style only: never "
        "reuse their facts, and never copy a line verbatim.\n"
        if my_voice
        else ""
    )
    my_voice_block = (
        f"=== MY VOICE (match the voice, not the content) ===\n{my_voice}\n\n" if my_voice else ""
    )
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
        f"{voice_contract}\n\n"
        "Hard rules:\n"
        f"- Pick exactly ONE masthead, verbatim, as line 1 — from: "
        f"{_bullet_list(mastheads.get('choices'))} (default "
        f"{mastheads.get('default') or 'none'}).\n"
        "- Write in ONE voice only; do not mix registers.\n"
        "- Name the product the post is about (MongoDB, Kafka, ClickHouse…) "
        "plainly and early, once, when the draft centres on one — a reader must "
        "not have to guess it from feature names (writeConcern, ISR…).\n"
        f"{voice_rule}"
        f"{my_voice_rule}"
        "- Do NOT imitate the recent captions' openers, closers, or vocabulary.\n"
        "- No hype, no invented facts, no engagement bait, no domain in the caption.\n\n"
        "=== RECENT CAPTIONS (avoid repeating) ===\n"
        f"{recent_block}\n\n"
        "=== BRAND BRIEF (Atento DNA) ===\n"
        f"{payload.get('dna') or '(no DNA configured)'}\n\n"
        "=== VOICE MENU (pick one key) ===\n"
        f"{voice_block}\n\n"
        f"{my_voice_block}"
        "=== DRAFT TO REWRITE ===\n"
        f"{json.dumps(draft, ensure_ascii=False, indent=2)}\n"
        "=== IMAGE ===\n"
        "Do not write an image prompt. The post uses the source article's own cover "
        "image, or a code-drawn diagram the operator renders with `blog diagram`; "
        "for a few posts — and only when a drawn figure really explains the idea — "
        "the operator may draw an illustration with the `anatomy` skill instead. "
        "You never choose and never describe the image.\n"
    )


def build_ideas_prompt(payload: dict) -> str:
    """The task for one headless run that proposes *original* post ideas.

    ``payload`` is ``GET /api/ideas``: the theme systems (``topics``, each an
    architecture to draw from), the titles already queued (``existing``) so nothing
    repeats, the DNA (which owns the content pillars) and the recent captions.
    There is nothing to fetch — the systems are well known, and the run draws on
    its own knowledge of each one's architecture and official documentation. Each
    idea is asked to be **approachable** (a reader who knows the basics can follow
    it), go deep in **one** spot, and start from a **real, familiar problem** — not
    a surface "what is X" and not an internals tour.
    """
    per_run = max(1, int(payload.get("per_run") or 3))
    topics = payload.get("topics") or []
    topics_block = (
        "\n".join(
            f"- {topic.get('name')}" + (f"  (docs: {topic.get('url')})" if topic.get("url") else "")
            for topic in topics
            if topic.get("name")
        )
        or "(no themes configured)"
    )
    existing_block = "\n".join(f"- {title}" for title in payload.get("existing") or []) or "(none)"
    recent = payload.get("recent") or []
    recent_block = (
        "\n\n".join(
            f"--- recent caption ({item.get('id')}) ---\n{item.get('caption', '')}"
            for item in recent
            if item.get("caption")
        )
        or "(none)"
    )
    return (
        "You are the Atento idea generator. Propose original Facebook Page post "
        f"ideas for the Atento Education page — exactly {per_run} of them.\n\n"
        "These are ORIGINAL posts, not summaries of an article: each idea takes "
        "ONE system below, digs into a single aspect of it, and explains that "
        "aspect through a real problem readers have met. Use your own knowledge "
        "of each system's architecture and official documentation; do not invent "
        "facts, version numbers, or benchmarks.\n\n"
        "Reply with ONLY a single JSON object — no prose, no markdown fence — "
        "with exactly these keys:\n"
        f'  "ideas": an array of exactly {per_run} objects, each '
        '{"topic": "one theme below, verbatim", "title": "the post\'s hook/angle", '
        '"excerpt": "1-3 sentences: the familiar problem it starts from, the single '
        'aspect it explains, and what the reader takes away"}.\n\n'
        "Hard rules:\n"
        "- One system per idea, and `topic` must be one of the themes below, "
        "verbatim.\n"
        "- Aim at a wide audience: a reader who knows the basics must be able to "
        "follow the post without a deep infrastructure dive.\n"
        "- Go deep in ONE spot only — a single mechanism, trade-off, or failure "
        "mode, not a survey of several. Skip the textbook 'X là gì'.\n"
        "- Anchor each idea in a real, familiar problem — a production incident, "
        "a bill that spiked, a slow query, a migration gone wrong, a page that "
        "felt broken — so the reader recognises their own situation before the "
        "mechanism is named.\n"
        "- `title` is the hook that would be the post's opening line: concrete, "
        "specific, and naming the system (MongoDB, Kafka, …) so a reader knows "
        "what it is about; no hype, no clickbait, no 'Bạn có biết…'.\n"
        "- Do NOT repeat any title already queued, and do not imitate the recent "
        "captions' openers, closers, or vocabulary.\n"
        "- No invented statistics, quotes, or achievements.\n\n"
        "=== THEME SYSTEMS (draw from these) ===\n"
        f"{topics_block}\n\n"
        "=== BRAND BRIEF (Atento DNA — the content pillars live here) ===\n"
        f"{payload.get('dna') or '(no DNA configured)'}\n\n"
        "=== IDEAS ALREADY QUEUED (do not repeat) ===\n"
        f"{existing_block}\n\n"
        "=== RECENT CAPTIONS (avoid repeating their angles) ===\n"
        f"{recent_block}\n"
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
        # Two kinds of request share this queue: a full rewrite and the same
        # rewrite in a voice the operator picked.
        voice_locked = draft.get("rewrite_mode") == REWRITE_CAPTION_VOICE
        my_voice = _my_voice(cfg, draft)
        prompt = build_prompt(payload, draft, voice_locked=voice_locked, my_voice=my_voice)
        if dry_run:
            extra = f", {len(my_voice)} chars of voice" if my_voice else ", no voice examples"
            print(f"[rewriter] would rewrite {ident} ({len(prompt)} chars of prompt{extra})")
            continue
        print(f"[rewriter] rewriting {ident}…", flush=True)
        try:
            rewrite = run_commandcode(settings, prompt)
            _request_json(cfg, "POST", f"{base}/api/drafts/{ident}/rewrite", rewrite)
            print(f"[rewriter] {ident}: rewrite posted", flush=True)
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


def process_ideas_once(cfg: dict, *, dry_run: bool = False) -> int:
    """Propose a batch of original post ideas if one was requested.

    Polls ``GET /api/ideas``; when its ``requested`` flag is set, runs one headless
    ``build_ideas_prompt`` and posts the proposed ideas to ``POST /api/ideas``
    (queued as ``extracted`` drafts). A failure goes to ``POST /api/ideas/error``
    so the request does not wait forever. Returns how many ideas were queued.
    """
    settings = rewrite_config(cfg)
    base = str(settings.get("api_base") or "").rstrip("/")
    payload = _request_json(cfg, "GET", f"{base}/api/ideas")
    if not payload.get("requested"):
        return 0
    prompt = build_ideas_prompt(payload)
    if dry_run:
        print(f"[rewriter] would propose ideas ({len(prompt)} chars of prompt)")
        return 0
    print("[rewriter] proposing ideas…", flush=True)
    try:
        result = run_commandcode(settings, prompt)
        ideas = result.get("ideas") if isinstance(result, dict) else None
        if not isinstance(ideas, list) or not ideas:
            raise WorkerError("the idea run returned no `ideas` array")
        response = _request_json(cfg, "POST", f"{base}/api/ideas", {"ideas": ideas})
        added = int(response.get("added", 0) or 0)
        print(f"[rewriter] ideas: queued {added} draft(s)", flush=True)
        return added
    except WorkerError as exc:
        print(f"[rewriter] idea generation failed: {exc}", file=sys.stderr, flush=True)
        try:
            _request_json(cfg, "POST", f"{base}/api/ideas/error", {"error": str(exc)})
        except WorkerError as post_exc:
            print(f"[rewriter] could not record the failure: {post_exc}", file=sys.stderr)
        return 0


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
            ideas = 0 if args.draft else process_ideas_once(cfg, dry_run=args.dry_run)
        except WorkerError as exc:
            print(f"rewrite_worker: {exc}", file=sys.stderr)
            return 1
        if not args.dry_run:
            print(f"rewrite_worker: {count} rewrite(s) posted, {ideas} idea(s) queued")
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
            process_ideas_once(cfg)
        except WorkerError as exc:  # a transient HTTP failure: log and keep polling
            print(f"[rewriter] {exc}", file=sys.stderr, flush=True)
        time.sleep(poll)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
