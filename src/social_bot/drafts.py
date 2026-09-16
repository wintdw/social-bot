"""Draft model, state machine, and persistence (pure logic).

A draft moves: extracted -> ai_draft -> posted (or rejected). The AI rewrite
(via Command Code) fills in the caption fields; a human approves on the review
page, which triggers the publish. Nothing here talks to the network.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
from dataclasses import asdict, dataclass, field
from email.utils import parsedate_to_datetime

EXTRACTED = "extracted"
AI_DRAFT = "ai_draft"
APPROVED = "approved"
POSTED = "posted"
REJECTED = "rejected"

STATES = (EXTRACTED, AI_DRAFT, APPROVED, POSTED, REJECTED)

# What a pending rewriter request asks for (``Draft.rewrite_mode``): the whole
# rewrite (caption + image prompt), or *only* a fresh image prompt for a post
# whose caption is already settled — often already approved and queued.
REWRITE_CAPTION = "caption"
REWRITE_IMAGE = "image"
REWRITE_MODES = (REWRITE_CAPTION, REWRITE_IMAGE)

# States a draft can be published from (an explicit human click implies approval).
_PUBLISHABLE = (AI_DRAFT, APPROVED)
# States a rewrite may land on (re-running the agent is fine).
_REWRITABLE = (EXTRACTED, AI_DRAFT)
# States an *image-prompt* rewrite may land on. Wider than _REWRITABLE: an
# approved draft's caption is what the human approved, but its picture is not part
# of that approval, so a queued post can still be re-imaged. Done drafts (posted,
# rejected) are not — nothing would ever see the new prompt.
_REIMAGEABLE = (EXTRACTED, AI_DRAFT, APPROVED)


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def parse_when(value: str) -> dt.datetime | None:
    """Parse an item timestamp into an aware datetime, or None.

    Sources date their items several ways — Atom/JSON-LD use ISO 8601, RSS
    pubDate uses RFC 822 — and some omit the date entirely. Naive timestamps are
    assumed UTC so every result is comparable.
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


@dataclass
class Draft:
    id: str
    source: str = ""
    url: str = ""
    title: str = ""
    excerpt: str = ""
    image: str = ""
    # The image the source post itself published, captured at scan time and
    # never written by image generation — so /review/{id} can always put the
    # source's own cover back after a generated one replaced it.
    source_image: str = ""
    published: str = ""
    lang: str = ""
    state: str = EXTRACTED
    # Filled in by the AI rewrite (POST /api/drafts/{id}/rewrite).
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)
    cta: str = ""
    commentary: str = ""
    # A concrete English visual concept for the generated image — also the
    # image's alt text. The rewriter knows the article, so it gives a far better
    # subject than the raw title/excerpt (which is why every auto-prompt image
    # looked alike). Optional: image_gen falls back to the title when this is
    # empty. Editable on /review/{id}.
    image_prompt: str = ""
    # The visual treatment for the image (image_gen.styles key), chosen per post
    # by the rewriter by content and tone — like the masthead (DNA §9.2). Empty
    # or unknown falls back to image_gen.default_style at generation time.
    # Overridable on /review/{id}.
    image_style: str = ""
    # The voice/register key (publish.voices), chosen per post by the rewriter by
    # content — like the masthead and image_style (DNA §3). Empty or unknown falls
    # back to publish.default_voice when the API delivers the voice menu.
    # Overridable on /review/{id}.
    voice: str = ""
    # A human asked the rewriter worker to rewrite this draft (the "Rewrite with
    # Command Code" button on /review/{id}). An ISO timestamp while the request
    # is open; the whole thing is the host-side worker's queue. Cleared when a
    # rewrite lands (apply_rewrite) or the request is cancelled. `rewrite_error`
    # carries the worker's last failure, so the operator can see why nothing
    # came back instead of a request that waits forever.
    rewrite_requested_at: str = ""
    rewrite_error: str = ""
    # What that open request asks for (REWRITE_CAPTION / REWRITE_IMAGE); empty
    # when nothing is pending. One flag + one kind rather than a flag per kind, so
    # "a caption rewrite and an image rewrite are both pending" cannot exist.
    rewrite_mode: str = ""
    # Advisory AI-tell warnings from caption_lint, written at rewrite/edit time
    # and shown on /review/{id}. Never blocks a rewrite or a post; empty when the
    # caption reads clean. Each entry is {"code", "message"}.
    lint: list[dict] = field(default_factory=list)
    # Publish bookkeeping. `posts` is keyed by destination name, one record per
    # platform the draft has been sent to, so a multi-destination draft keeps
    # each platform's own post_id/permalink/time:
    #   {destination: {"post_id", "permalink", "posted_at", "private"}}
    destinations: list[str] = field(default_factory=list)
    posts: dict[str, dict] = field(default_factory=dict)
    # Manual position in the post queue. 0 = unset: the draft sorts by the
    # default rule (oldest source date first). Set by the Post queue tab's
    # queue; only consulted for approved drafts (see draft_pipeline._queue_key).
    queue_order: int = 0
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Draft:
        data = dict(data)
        # Migrate pre-destinations drafts: the flat post_id/permalink/posted_at
        # become the first destination's record.
        if "posts" not in data:
            legacy = {
                "post_id": data.get("post_id", ""),
                "permalink": data.get("permalink", ""),
                "posted_at": data.get("posted_at", ""),
            }
            if any(legacy.values()):
                destination = (data.get("destinations") or ["facebook"])[0]
                data["posts"] = {destination: {**legacy, "private": False}}
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})

    # -- state -----------------------------------------------------------

    def can_receive_rewrite(self) -> bool:
        return self.state in _REWRITABLE

    def can_request_image_prompt(self) -> bool:
        """Whether a prompt-only rewrite may land on this draft (see _REIMAGEABLE)."""
        return self.state in _REIMAGEABLE

    def rewrite_kind(self) -> str:
        """What the open rewriter request asks for ("" when nothing is pending).

        A request written before this field existed has no mode and reads as a
        full rewrite, which is what it was.
        """
        if not self.rewrite_requested_at:
            return ""
        return self.rewrite_mode if self.rewrite_mode in REWRITE_MODES else REWRITE_CAPTION

    def can_publish(self) -> bool:
        return self.state in _PUBLISHABLE

    def apply_rewrite(
        self,
        *,
        caption: str = "",
        hashtags: list[str] | None = None,
        cta: str = "",
        commentary: str = "",
        image_prompt: str = "",
        image_style: str = "",
        voice: str = "",
    ) -> None:
        if caption:
            self.caption = caption
        if hashtags is not None:
            self.hashtags = [str(tag) for tag in hashtags]
        if cta:
            self.cta = cta
        if commentary:
            self.commentary = commentary
        if image_prompt:
            self.image_prompt = image_prompt
        if image_style:
            self.image_style = image_style
        if voice:
            self.voice = voice
        # A rewrite fulfils any pending rewriter-worker request.
        self.rewrite_requested_at = ""
        self.rewrite_mode = ""
        self.rewrite_error = ""
        self.state = AI_DRAFT
        self.touch()

    def apply_image_prompt(self, *, image_prompt: str = "") -> None:
        """Store a prompt-only rewrite: the image prompt, and nothing else.

        Unlike ``apply_rewrite`` this leaves the caption, the rest of the rewrite
        fields, the ``image_style`` treatment and — crucially — the *state* alone,
        so re-imaging an approved draft cannot un-queue the post a human already
        approved. The treatment is the operator's: it was saved from the compose
        form when they asked, and the agent writes the prompt to serve it.
        """
        if image_prompt:
            self.image_prompt = image_prompt
        # Clear this request only. A caption rewrite the operator asked for in the
        # meantime stays pending (and would overwrite the prompt anyway).
        if self.rewrite_kind() == REWRITE_IMAGE:
            self.rewrite_requested_at = ""
            self.rewrite_mode = ""
        self.rewrite_error = ""
        self.touch()

    def approve(self) -> None:
        if not self.can_publish():
            raise ValueError(f"draft {self.id!r} in state {self.state!r} cannot be approved")
        self.state = APPROVED
        self.touch()

    def unapprove(self) -> None:
        """Pull an approved draft back out of the post queue.

        Approval is reversible right up to the send: this returns a queued draft
        to ``ai_draft`` so the poster no longer sees it, while it stays on
        /review for further edits, a rewrite, or another approval. The manual
        queue position is dropped with it, so a later re-approval lands at the
        end of the queue rather than resurrecting a stale rank. A draft already
        posted publicly cannot be un-approved — a send cannot be undone.
        """
        if self.state != APPROVED:
            raise ValueError(f"draft {self.id!r} in state {self.state!r} is not approved")
        if self.posted_destinations():
            raise ValueError(f"draft {self.id!r} has already been posted; it cannot be un-approved")
        self.state = AI_DRAFT
        self.queue_order = 0
        self.touch()

    def reject(self) -> None:
        self.state = REJECTED
        self.touch()

    def record_post(
        self,
        destination: str,
        *,
        post_id: str = "",
        permalink: str = "",
        private: bool = False,
    ) -> None:
        """Record the result of a send to one destination."""
        self.posts[destination] = {
            "post_id": str(post_id),
            "permalink": str(permalink),
            "posted_at": now_iso(),
            "private": bool(private),
        }
        self.touch()

    def mark_posted(
        self,
        destination: str,
        *,
        post_id: str = "",
        permalink: str = "",
        private: bool = False,
    ) -> None:
        """Record a send; flip to POSTED once every target has a public post.

        A private send (``publish.private``) is recorded but never completes the
        draft, so it stays in the queue for a later public send.
        """
        self.record_post(destination, post_id=post_id, permalink=permalink, private=private)
        if not private and self.is_fully_posted():
            self.state = POSTED

    def posted_destinations(self) -> list[str]:
        """Destinations with a *public* post record."""
        return [name for name, record in self.posts.items() if not record.get("private")]

    def pending_destinations(self) -> list[str]:
        """Target destinations that still have no public post."""
        done = set(self.posted_destinations())
        return [name for name in self.destinations if name not in done]

    def is_fully_posted(self) -> bool:
        return bool(self.destinations) and not self.pending_destinations()

    # Flat access to the *primary* posted destination (facebook preferred), so
    # single-destination code and templates keep working. Private records are
    # ignored — a private send leaves the draft "not posted", as before.
    @property
    def post_id(self) -> str:
        return self._first_public_post("post_id")

    @property
    def permalink(self) -> str:
        return self._first_public_post("permalink")

    @property
    def posted_at(self) -> str:
        return self._first_public_post("posted_at")

    def _first_public_post(self, field: str) -> str:
        public = self.posted_destinations()
        if not public:
            return ""
        if "facebook" in public:
            public = ["facebook"] + [name for name in public if name != "facebook"]
        return str(self.posts[public[0]].get(field, "") or "")

    def touch(self) -> None:
        self.updated_at = now_iso()

    @property
    def rank(self) -> int:
        """The manual queue position as a safe non-negative int (0 = unset).

        A hand-edited ``queue_order`` must never break the queue sort, so
        anything non-numeric falls back to 0 (the default order).
        """
        try:
            return max(0, int(self.queue_order or 0))
        except (TypeError, ValueError):
            return 0

    @property
    def body(self) -> str:
        """The text to publish: the AI caption, falling back to the title."""
        return self.caption or self.title

    @property
    def post_text(self) -> str:
        """The caption with hashtags appended — the exact text that gets posted."""
        tags = " ".join(tag for tag in self.hashtags if tag)
        if not tags:
            return self.body
        return f"{self.body}\n\n{tags}" if self.body else tags


def find(drafts: list[Draft], draft_id: str) -> Draft | None:
    for draft in drafts:
        if draft.id == draft_id:
            return draft
    return None


# Decoded queue JSON keyed by path, validated against (mtime_ns, size). Every
# request used to re-read and re-parse the whole file; on a warm queue that is
# the dominant cost of /review, /api/drafts and /status. The cached value is the
# raw decoded JSON, never Draft objects, so each caller still gets its own
# mutable copies (publish mutates and re-saves them).
_QUEUE_CACHE: dict[str, tuple[int, int, list[dict]]] = {}


def _read_queue(path: pathlib.Path) -> list[dict]:
    try:
        stat = path.stat()
        key = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return json.loads(path.read_text(encoding="utf-8"))
    cached = _QUEUE_CACHE.get(str(path))
    if cached is not None and cached[0] == key[0] and cached[1] == key[1]:
        return cached[2]
    raw = json.loads(path.read_text(encoding="utf-8"))
    _QUEUE_CACHE[str(path)] = (key[0], key[1], raw)
    return raw


def load_drafts(path) -> list[Draft]:
    path = pathlib.Path(path)
    if not path.exists():
        return []
    return [Draft.from_dict(entry) for entry in _read_queue(path)]


def save_drafts(path, drafts: list[Draft]) -> None:
    """Write the queue atomically (temp file + rename)."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps([d.to_dict() for d in drafts], indent=2, ensure_ascii=False)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)
    _QUEUE_CACHE.pop(str(path), None)


def append_audit(path, record: dict) -> None:
    """Append one JSON line to the publish audit log."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
