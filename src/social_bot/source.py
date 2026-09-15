"""Source feed parsing (pure logic, no network).

Turns a sitemap or RSS/Atom document into normalized Items the draft pipeline
can queue. Fetching lives in source_api.py so this stays offline-testable.
"""

from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
ATOM_NS = "{http://www.w3.org/2005/Atom}"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

_POSTING_TYPES = ("blogposting", "article", "newsarticle")


@dataclass
class Source:
    name: str
    type: str = "sitemap"
    url: str = ""
    path_prefix: str = ""
    lang: str = ""

    @classmethod
    def from_config(cls, raw: dict) -> Source:
        return cls(
            name=str(raw.get("name", "")),
            type=str(raw.get("type", "sitemap")),
            url=str(raw.get("url", "")),
            path_prefix=str(raw.get("path_prefix", "") or ""),
            lang=str(raw.get("lang", "") or ""),
        )


@dataclass
class Item:
    id: str = ""
    source: str = ""
    url: str = ""
    title: str = ""
    excerpt: str = ""
    image: str = ""
    published: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Item:
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


def slug_of(url: str) -> str:
    """The last path segment of a URL (the stable id we dedupe on)."""
    path = str(url).split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return path.rsplit("/", 1)[-1]


def clean_text(text: str | None, limit: int = 0) -> str:
    """Strip tags, unescape entities, collapse whitespace, optionally truncate."""
    if not text:
        return ""
    plain = html.unescape(_TAG_RE.sub(" ", str(text)))
    plain = _WS_RE.sub(" ", plain).strip()
    if limit and len(plain) > limit:
        plain = plain[: max(0, limit - 1)].rstrip() + "…"
    return plain


def _text(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    return (child.text or "").strip() if child is not None else ""


def parse_sitemap(
    xml_text: str,
    path_prefix: str = "",
    *,
    source_name: str = "",
    excerpt_chars: int = 0,
) -> list[Item]:
    """Parse a sitemap's <loc> entries whose URL contains `path_prefix`.

    Returns items ordered by <lastmod> descending (entries without a lastmod
    sort last, in document order). Ids are the URL slug — dates here are
    unreliable, so the slug is the dedupe key.
    """
    root = ET.fromstring(xml_text)
    found: list[tuple[str, str]] = []  # (published, url)
    for node in root.iter(f"{SITEMAP_NS}url"):
        loc = _text(node, f"{SITEMAP_NS}loc")
        if not loc:
            continue
        if path_prefix and path_prefix not in loc:
            continue
        found.append((_text(node, f"{SITEMAP_NS}lastmod"), loc))
    found.sort(key=lambda pair: pair[0], reverse=True)
    return [
        Item(
            id=slug_of(url),
            source=source_name,
            url=url,
            published=published,
        )
        for published, url in found
    ]


def parse_rss(
    xml_text: str,
    *,
    source_name: str = "",
    excerpt_chars: int = 0,
) -> list[Item]:
    """Parse an RSS 2.0 or Atom document into Items (document order)."""
    root = ET.fromstring(xml_text)
    items: list[Item] = []

    for node in root.iter("item"):  # RSS 2.0
        url = _text(node, "link") or _text(node, "guid")
        if not url:
            continue
        image = ""
        enclosure = node.find("enclosure")
        if enclosure is not None and str(enclosure.get("type", "")).startswith("image"):
            image = enclosure.get("url", "")
        items.append(
            Item(
                id=slug_of(url),
                source=source_name,
                url=url,
                title=clean_text(_text(node, "title")),
                excerpt=clean_text(_text(node, "description"), excerpt_chars),
                image=image,
                published=_text(node, "pubDate"),
            )
        )
    if items:
        return items

    for node in root.iter(f"{ATOM_NS}entry"):  # Atom
        url = ""
        image = ""
        for link in node.findall(f"{ATOM_NS}link"):
            rel = link.get("rel", "alternate")
            if rel == "enclosure" and not image:
                image = link.get("href", "")
            elif rel in ("alternate", "") and not url:
                url = link.get("href", "")
        if not url:
            continue
        summary = _text(node, f"{ATOM_NS}summary") or _text(node, f"{ATOM_NS}content")
        items.append(
            Item(
                id=slug_of(url),
                source=source_name,
                url=url,
                title=clean_text(_text(node, f"{ATOM_NS}title")),
                excerpt=clean_text(summary, excerpt_chars),
                image=image,
                published=_text(node, f"{ATOM_NS}published") or _text(node, f"{ATOM_NS}updated"),
            )
        )
    return items


def parse_source(source: Source, xml_text: str, *, excerpt_chars: int = 0) -> list[Item]:
    """Dispatch to the parser for the source's type."""
    if source.type == "rss":
        return parse_rss(xml_text, source_name=source.name, excerpt_chars=excerpt_chars)
    if source.type == "index":
        return parse_index(
            xml_text,
            base_url=source.url,
            path_prefix=source.path_prefix,
            source_name=source.name,
            excerpt_chars=excerpt_chars,
        )
    return parse_sitemap(
        xml_text,
        source.path_prefix,
        source_name=source.name,
        excerpt_chars=excerpt_chars,
    )


class _PostParser(HTMLParser):
    """Collect the bits of a post/listing page we enrich a draft from."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.jsonld: list[str] = []
        self.links: list[str] = []
        self.canonical: str = ""
        self.title: str = ""
        self._in_jsonld = False
        self._jsonld_buf: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = {key.lower(): value for key, value in attrs if value is not None}
        if tag == "script" and attributes.get("type") == "application/ld+json":
            self._in_jsonld = True
            self._jsonld_buf = []
        elif tag == "meta":
            key = attributes.get("property") or attributes.get("name")
            if key and "content" in attributes:
                self.meta.setdefault(key.lower(), attributes["content"])
        elif tag == "link" and attributes.get("rel") == "canonical":
            self.canonical = attributes.get("href", "")
        elif tag == "a" and attributes.get("href"):
            self.links.append(attributes["href"])
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            self.jsonld.append("".join(self._jsonld_buf))
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_jsonld:
            self._jsonld_buf.append(data)
        elif self._in_title:
            self.title += data


def _walk_jsonld(data: Any):
    if isinstance(data, dict):
        yield data
        for value in data.get("@graph") or []:
            yield from _walk_jsonld(value)
    elif isinstance(data, list):
        for value in data:
            yield from _walk_jsonld(value)


def _first_posting(blocks: list[str]) -> dict:
    for block in blocks:
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for node in _walk_jsonld(data):
            if isinstance(node, dict) and str(node.get("@type", "")).lower() in _POSTING_TYPES:
                return node
    return {}


def _first_image(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("url", ""))
    if isinstance(value, list):
        for entry in value:
            image = _first_image(entry)
            if image:
                return image
    return ""


def parse_blog_posting(
    html_text: str,
    url: str,
    *,
    source_name: str = "",
    excerpt_chars: int = 0,
) -> Item:
    """Enrich a post from its page: JSON-LD BlogPosting, then og/meta fallback."""
    parser = _PostParser()
    parser.feed(html_text)
    posting = _first_posting(parser.jsonld)
    title = posting.get("headline") or posting.get("name")
    excerpt = posting.get("description")
    image = _first_image(posting.get("image"))
    published = posting.get("datePublished")
    meta = parser.meta
    return Item(
        id=slug_of(url),
        source=source_name,
        url=parser.canonical or url,
        title=clean_text(title or meta.get("og:title") or parser.title),
        excerpt=clean_text(
            excerpt or meta.get("og:description") or meta.get("description"), excerpt_chars
        ),
        image=str(image or meta.get("og:image", "")),
        published=str(published or meta.get("article:published_time", "")),
    )


def _item_list_entries(node: Any) -> list:
    """JSON-LD ItemList entries, whether at the node or under mainEntity."""
    if not isinstance(node, dict):
        return []
    if isinstance(node.get("itemListElement"), list):
        return node["itemListElement"]
    main = node.get("mainEntity")
    if isinstance(main, dict) and isinstance(main.get("itemListElement"), list):
        return main["itemListElement"]
    return []


def parse_index(
    html_text: str,
    *,
    base_url: str = "",
    path_prefix: str = "/blog/",
    source_name: str = "",
    excerpt_chars: int = 0,
) -> list[Item]:
    """Detect posts from a listing page's JSON-LD ItemList (anchor fallback).

    Used when a site publishes no feed and its sitemap omits posts — it reads
    the site's own structured data, not CSS-scraped markup.
    """
    parser = _PostParser()
    parser.feed(html_text)

    items: list[Item] = []
    seen: set[str] = set()

    def _add(url: str, title: str = "") -> None:
        if not url or (path_prefix and path_prefix not in url):
            return
        slug = slug_of(url)
        if not slug or slug in seen:
            return
        seen.add(slug)
        items.append(Item(id=slug, source=source_name, url=url, title=clean_text(title)))

    for block in parser.jsonld:
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for node in _walk_jsonld(data):
            for entry in _item_list_entries(node):
                if not isinstance(entry, dict):
                    continue
                url = entry.get("url") or (
                    entry.get("item") if isinstance(entry.get("item"), str) else ""
                )
                _add(str(url), str(entry.get("name", "")))

    if not items:  # fallback: post links in the markup
        for href in parser.links:
            _add(urljoin(base_url, href))

    return items
