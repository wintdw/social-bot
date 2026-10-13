"""Advisory lint for the AI-writing tells a caption should avoid (pure logic).

Captions are written by the operator in Claude. This module does not edit a
caption — it *names* the
tells a human reviewer should fix, so a run of posts doesn't converge on one
formula. Warnings are advisory: they are stored on the draft and shown on
/review/{id} whenever a caption is saved; they never block a save or a post.

Two kinds of check: ones that read a single caption (a stock opener, the
antithesis engine, a flat rhythm, the rule of three, a cliché transition, empty
hype), and ones that compare it against the captions most recently written (a
repeated hook or closer) — because the tell is often invisible in one post and
obvious across several.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from difflib import SequenceMatcher

from .caption import leading_masthead

# Similarity at/above which two hooks (or closers) count as "the same move".
_SIMILARITY = 0.72
# Shortest normalized line worth comparing — below this, matches are noise.
_MIN_LINE = 12
# A caption needs at least this many sentences before "flat rhythm" means much.
_MIN_SENTENCES = 5

# Openers that recur across posts and read as a formula rather than a scene.
_STOCK_OPENERS = (
    "ai cũng biết",
    "ai cũng nói",
    "ai cũng nghĩ",
    "chúng ta đều biết",
    "chúng ta đều nghĩ",
    "bạn có biết",
    "bạn có bao giờ",
    "đã bao giờ bạn",
    "hãy tưởng tượng",
    "trong thế giới",
    "có một sự thật",
    "sự thật là",
)

# The antithesis engine: fine once, a tell when a post leans on it.
_ANTITHESIS = (
    re.compile(r"\bmà là\b", re.I),
    re.compile(r"\bkhông nằm ở\b", re.I),
    re.compile(r"\bkhông phải (?:là |hẳn )?[^.\n!?]{0,40}?mà\b", re.I),
)

# Empty hype a caption should never carry.
_HYPE = (
    "cách mạng",
    "đột phá",
    "thay đổi mọi thứ",
    "tốt nhất việt nam",
    "vô song",
    "số một",
)

# Empty transition phrases that pad an idea instead of advancing it. Keep this
# short and deliberately NOT the stock signature phrases ("Hãy tưởng tượng…",
# "Điều quan trọng cần chú ý là…") — those are voice, not filler.
_CLICHE = (
    "về cơ bản",
    "trong bối cảnh hiện nay",
    "có thể nói rằng",
    "không thể phủ nhận rằng",
    "một cách tổng quát",
)

# The rule of three: a comma run of three-plus same-shape items ("nhanh, gọn,
# chính xác"). Ordinals are a real enumeration, not the tell, so skip those.
_ORDINAL_RE = re.compile(r"^\s*(?:thứ\b|một là|hai là|ba là|bốn là|năm là|\d+\s*[.)])", re.I)
_LEADING_CONJ_RE = re.compile(r"^\s*(?:và|hoặc|hay|and)\s+", re.I)
# A "but/tuy nhiên" clause is prose, not a list item, so its presence means the
# comma run is ordinary Vietnamese sentence flow rather than a tricolon.
_ADVERSATIVE_RE = re.compile(r"^\s*(?:nhưng|song|tuy nhiên)\b", re.I)
# Longest a list item may be (words) to still read as a tricolon rather than prose.
_TRICOLON_MAX_WORDS = 3

# Required boilerplate that is not the post's own closing move, so it never
# counts as a repeated closer: the CTA line ("… tại comment") and the source
# credit ("Nguồn: …") — the latter repeats verbatim for a frequent
# source, which would otherwise false-positive on every post from that author.
_BOILERPLATE_RE = re.compile(r"comment|^\s*nguồn\s*:", re.I)

_WORD_RE = re.compile(r"[\W_]+", re.UNICODE)


def _norm(text: str) -> str:
    """Lowercase and strip punctuation/whitespace, for fuzzy comparison."""
    return _WORD_RE.sub(" ", str(text or "").lower()).strip()


def _lines(text: str) -> list[str]:
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def _without_masthead(caption: str) -> str:
    """The caption past its leading masthead line, or unchanged if it has none."""
    masthead = leading_masthead(caption)
    text = str(caption or "")
    if not masthead:
        return text
    return text[text.index(masthead) + len(masthead) :]


def _hook(caption: str) -> str:
    """The caption's opening line (under the masthead) — its first real move."""
    lines = _lines(_without_masthead(caption))
    return lines[0] if lines else ""


def _closer(caption: str) -> str:
    """The caption's last line that is not required boilerplate — its closing move."""
    lines = [
        line for line in _lines(_without_masthead(caption)) if not _BOILERPLATE_RE.search(line)
    ]
    return lines[-1] if lines else ""


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[.!?…\n]+", text) if part.strip()]


def _is_tricolon(sentence: str) -> bool:
    """True when a sentence lists 3+ short same-shape items (the rule of three)."""
    parts = [_LEADING_CONJ_RE.sub("", part).strip() for part in sentence.split(",")]
    parts = [part for part in parts if part]
    if len(parts) < 3:
        return False
    if any(_ORDINAL_RE.match(part) or _ADVERSATIVE_RE.match(part) for part in parts):
        return False
    return all(len(_norm(part).split()) <= _TRICOLON_MAX_WORDS for part in parts)


def _similar(a: str, b: str) -> bool:
    """True when two lines read as the same move (exact or close)."""
    na, nb = _norm(a), _norm(b)
    if min(len(na), len(nb)) < _MIN_LINE:
        return False
    return na == nb or SequenceMatcher(None, na, nb).ratio() >= _SIMILARITY


def lint_caption(caption: str, *, recent: Iterable[str] = ()) -> list[dict]:
    """Advisory warnings for the AI tells in `caption` ([] when it reads clean).

    `recent` is the captions most recently written, newest first: a hook or
    closer that repeats one of them is the cross-post tell a single caption
    can't reveal. Each warning is ``{"code", "message"}``, deterministic in
    order, and safe to render or to store on a draft.
    """
    warnings: list[dict] = []
    text = str(caption or "")
    if not text.strip():
        return warnings
    recent = [str(other) for other in recent if str(other).strip()]

    hook = _hook(text)
    closer = _closer(text)

    if hook and any(_similar(hook, _hook(other)) for other in recent):
        warnings.append(
            {
                "code": "repeated-hook",
                "message": f"Mở bài trùng với một caption gần đây: “{hook}”. Đổi cách vào bài.",
            }
        )
    if closer and any(_similar(closer, _closer(other)) for other in recent):
        warnings.append(
            {
                "code": "repeated-closer",
                "message": f"Câu chốt trùng với một caption gần đây: “{closer}”. Đổi câu kết.",
            }
        )

    lowered = _norm(hook)
    for opener in _STOCK_OPENERS:
        if lowered.startswith(opener):
            warnings.append(
                {
                    "code": "stock-opener",
                    "message": f"Mở bài bằng công thức quen: “{opener}…”. Vào thẳng một khoảnh khắc cụ thể.",
                }
            )
            break

    if sum(1 for pattern in _ANTITHESIS if pattern.search(text)) >= 2:
        warnings.append(
            {
                "code": "antithesis",
                "message": "Câu đối lập “không phải X mà là Y” xuất hiện nhiều lần — giữ lại một lần cho đắt.",
            }
        )

    lengths = [len(_norm(sentence).split()) for sentence in _sentences(_without_masthead(text))]
    lengths = [length for length in lengths if length]
    if len(lengths) >= _MIN_SENTENCES and max(lengths) - min(lengths) <= 3:
        warnings.append(
            {
                "code": "flat-rhythm",
                "message": "Các câu dài gần bằng nhau — thử một câu ngắn, một câu dài, hoặc một câu cụt.",
            }
        )

    if any(_is_tricolon(sentence) for sentence in _sentences(_without_masthead(text))):
        warnings.append(
            {
                "code": "rule-of-three",
                "message": "Ba vế liệt kê cùng hình dạng (“nhanh, gọn, chính xác”) — rút còn hai vế, hoặc chọn vế đắt nhất.",
            }
        )

    normalized = _norm(text)
    for phrase in _CLICHE:
        if phrase in normalized:
            warnings.append(
                {
                    "code": "cliche",
                    "message": f"Cụm chuyển ý vô nghĩa: “{phrase}”. Cắt thẳng vào ý.",
                }
            )
            break

    for word in _HYPE:
        if word in normalized:
            warnings.append({"code": "hype", "message": f"Tránh hype rỗng: “{word}”."})
            break

    return warnings
