"""Idea seeds: the systems/themes original Atento posts are drawn from (pure).

``sources[]`` are feeds to *repost* — each has a URL, is fetched, and the caption
credits an external author. ``ideas`` is a different input on purpose: a plain
markdown list of systems and architectures (Elasticsearch, ClickHouse, Loki,
Grafana, MySQL, MongoDB, …). Nothing is fetched and nothing is reposted — the
rewriter agent draws *original* Atento posts from each system's own
architecture and documentation, and the app only holds the themes and accepts
the generated ideas as drafts.

This module is pure: it parses that topics file and turns an idea's title into a
stable draft id. No network, no filesystem.
"""

from __future__ import annotations

import re
import unicodedata

# A line's "name | url" separator (optional reference docs). A plain line is a
# theme with no link.
_SEPARATOR = "|"
_BULLET_CHARS = "-*•+"
_NOT_SLUG = re.compile(r"[^a-z0-9]+")


def parse_topics(text: str) -> list[dict]:
    """Parse a topics file into ``[{"name", "url"}]``.

    One theme per line. Blank lines and ``#`` comments are ignored; a leading
    bullet (``-``, ``*``, …) is stripped; an optional ``| <url>`` tail records
    the system's reference docs. Duplicate names are dropped, keeping the first,
    so the same system listed twice does not offer the agent two identical
    themes.
    """
    topics: list[dict] = []
    seen: set[str] = set()
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.lstrip(_BULLET_CHARS).strip()
        if not line:
            continue
        name, _, url = line.partition(_SEPARATOR)
        name = " ".join(name.split())
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        topics.append({"name": name, "url": url.strip()})
    return topics


def slugify(text: str, *, max_length: int = 80) -> str:
    """A URL-safe, stable draft id from an idea title.

    Vietnamese is folded to ASCII (``đ`` -> ``d``, diacritics dropped) so a
    title like *"Vì sao MySQL chọn B+ tree?"* becomes ``vi-sao-mysql-chon-b-tree``
    — a readable id that survives on the filesystem and in a URL.
    """
    text = str(text or "").replace("đ", "d").replace("Đ", "D")
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = _NOT_SLUG.sub("-", folded.lower()).strip("-")
    return slug[:max_length].strip("-")
