"""Caption text conventions shared by the feed and the review queue (pure logic).

A Facebook post has no title field, so a post's title can only be the leading
line of its caption. Every caption the pipeline writes opens with a series
masthead on its own line — "[Học cùng Atento]" and friends — which is a standing
label, not this post's title: the title is the line under it, the hook. A caption
written before the masthead was configured titles itself with its first line.

The feed and the review queue both need the same answers — is there a masthead,
and what is this caption's title line? — so the rule lives here, and the two
views can never disagree.
"""

from __future__ import annotations

import re

# A whole line consisting of one bracketed label, e.g. "[Học cùng Atento]".
_MASTHEAD_RE = re.compile(r"\[[^\]\n]{1,60}\]")

# A derived title is one caption line; keep it short enough to read as one at a
# glance.
TITLE_MAX = 80

_ELLIPSIS = "…"


def _split_first_line(text: str) -> tuple[str, str]:
    """(first line, rest) skipping leading blank lines; ("", "") when empty."""
    lines = str(text or "").splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip()), None)
    if start is None:
        return "", ""
    return lines[start].strip(), "\n".join(lines[start + 1:]).strip("\n")


def _first_line_index(lines: list[str], start: int = 0) -> int | None:
    """Index of the first non-blank line at or after `start`, or None."""
    return next((i for i in range(start, len(lines)) if lines[i].strip()), None)


def leading_masthead(caption: str) -> str:
    """The series masthead on the caption's first non-empty line, or ''."""
    first, _ = _split_first_line(caption)
    return first if _MASTHEAD_RE.fullmatch(first) else ""


def _title_and_body(caption: str) -> tuple[str, str]:
    """(title line, body) — the hook, not the standing masthead.

    A caption opens with its series masthead; the title is the line under it (the
    hook), because the masthead is a label rather than this post's title. A
    caption with no masthead titles itself with its own first line, and one that
    is nothing but a masthead keeps the label (a better title than blanks).
    `body` is everything after the title line, so a row never repeats its title.
    """
    lines = str(caption or "").splitlines()
    first = _first_line_index(lines)
    if first is None:
        return "", ""
    first_line = lines[first].strip()
    if not _MASTHEAD_RE.fullmatch(first_line):
        return first_line, "\n".join(lines[first + 1:]).strip("\n")
    hook = _first_line_index(lines, first + 1)
    if hook is None:
        return first_line, ""
    return lines[hook].strip(), "\n".join(lines[hook + 1:]).strip("\n")


def split_title(caption: str, *, max_len: int = TITLE_MAX) -> tuple[str, str]:
    """(title, body) for a caption: its hook, truncated to `max_len`.

    The title is the line under the leading masthead (or the caption's own first
    line when there is no masthead), so every row is titled by what the post
    actually says. `body` is whatever follows the title line.
    """
    title, body = _title_and_body(caption)
    if len(title) > max_len:
        title = title[: max_len - 1].rstrip() + _ELLIPSIS
    return title, body


def display_title(caption: str, fallback: str = "") -> str:
    """A draft/row title: the caption's hook, else `fallback` (the source title).

    The fallback covers a draft that has no caption yet (still `extracted`), so
    the queue can always label a row with something identifying.
    """
    return split_title(caption)[0] or fallback
