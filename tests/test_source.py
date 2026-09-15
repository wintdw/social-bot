"""Source parsing (sitemap / RSS / Atom) — pure logic, no network."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from social_bot.source import (
    Source,
    clean_text,
    parse_blog_posting,
    parse_index,
    parse_rss,
    parse_sitemap,
    parse_source,
    slug_of,
)

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://atento.vn</loc></url>
<url><loc>https://atento.vn/blog</loc></url>
<url><loc>https://atento.vn/blog/old-post</loc><lastmod>2026-07-01T00:00:00.000Z</lastmod></url>
<url><loc>https://atento.vn/blog/new-post</loc><lastmod>2026-08-18T10:18:01.169Z</lastmod></url>
<url><loc>https://atento.vn/event/foo</loc><lastmod>2026-09-07T00:00:00.000Z</lastmod></url>
</urlset>"""

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Example feed</title>
<item>
  <title>Post &amp; One</title>
  <link>https://example.com/blog/post-one</link>
  <description><![CDATA[<p>Hello <b>world</b>.</p>]]></description>
  <pubDate>Mon, 18 Aug 2026 10:18:01 GMT</pubDate>
  <enclosure url="https://example.com/img1.jpg" type="image/jpeg"/>
</item>
<item>
  <title>Post Two</title>
  <link>https://example.com/blog/post-two</link>
  <description>Plain text summary</description>
</item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom feed</title>
  <entry>
    <title>Atom One</title>
    <link rel="alternate" href="https://example.com/blog/atom-one"/>
    <link rel="enclosure" href="https://example.com/a.jpg"/>
    <summary>Summary one</summary>
    <published>2026-08-18T10:00:00Z</published>
  </entry>
</feed>"""


class TestSlugOf:
    def test_last_segment(self):
        assert slug_of("https://atento.vn/blog/code-gioi") == "code-gioi"

    def test_trailing_slash_and_query(self):
        assert slug_of("https://atento.vn/blog/post/?utm=1") == "post"


class TestCleanText:
    def test_strips_tags_and_unescapes(self):
        assert clean_text("<p>Hello <b>world</b> &amp; co</p>") == "Hello world & co"

    def test_truncates_with_ellipsis(self):
        out = clean_text("abcdefghij", 5)
        assert out.endswith("…") and len(out) == 5


class TestParseSitemap:
    def test_filters_to_prefix_and_orders_by_lastmod(self):
        items = parse_sitemap(SITEMAP, "/blog/", source_name="atento-blog")
        assert [i.id for i in items] == ["new-post", "old-post"]
        assert items[0].url == "https://atento.vn/blog/new-post"
        assert items[0].published == "2026-08-18T10:18:01.169Z"
        assert items[0].source == "atento-blog"

    def test_no_prefix_keeps_everything(self):
        items = parse_sitemap(SITEMAP)
        urls = {i.url for i in items}
        assert "https://atento.vn/event/foo" in urls
        assert "https://atento.vn/blog/new-post" in urls


class TestParseRss:
    def test_rss_items(self):
        items = parse_rss(RSS, source_name="feed")
        assert [i.id for i in items] == ["post-one", "post-two"]
        first = items[0]
        assert first.title == "Post & One"
        assert first.excerpt == "Hello world ."
        assert first.image == "https://example.com/img1.jpg"
        assert first.published == "Mon, 18 Aug 2026 10:18:01 GMT"
        assert items[1].image == ""

    def test_atom_entries(self):
        items = parse_rss(ATOM, source_name="feed")
        assert len(items) == 1
        assert items[0].id == "atom-one"
        assert items[0].url == "https://example.com/blog/atom-one"
        assert items[0].image == "https://example.com/a.jpg"
        assert items[0].excerpt == "Summary one"

    def test_excerpt_truncation(self):
        items = parse_rss(RSS, excerpt_chars=5)
        assert items[1].excerpt.endswith("…")


class TestParseSource:
    def test_dispatch_sitemap(self):
        src = Source(name="s", type="sitemap", url="u", path_prefix="/blog/")
        assert [i.id for i in parse_source(src, SITEMAP)] == ["new-post", "old-post"]

    def test_dispatch_rss(self):
        src = Source(name="s", type="rss", url="u")
        assert [i.id for i in parse_source(src, RSS)] == ["post-one", "post-two"]

    def test_from_config_defaults(self):
        src = Source.from_config({"name": "n", "url": "https://x", "path_prefix": "/b/"})
        assert src.type == "sitemap" and src.name == "n"

    def test_bad_xml_raises(self):
        with pytest.raises(ET.ParseError):
            parse_sitemap("not xml", "/blog/")


POST_HTML = """<html><head>
<link rel="canonical" href="https://atento.vn/blog/canon">
<meta property="og:title" content="OG title">
<meta property="og:description" content="OG desc">
<meta property="og:image" content="https://img/og.jpg">
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
 {"@type":"BreadcrumbList"},
 {"@type":"BlogPosting","headline":"JSON-LD headline","description":"JSON-LD summary",
  "image":["https://img/cover.jpg"],"datePublished":"2026-08-18T10:00:00Z"}
]}
</script></head><body></body></html>"""

OG_ONLY = """<html><head>
<meta property="og:title" content="Only OG">
<meta property="og:description" content="Desc only">
<meta property="og:image" content="https://img/x.jpg">
<meta property="article:published_time" content="2026-08-18T10:00:00Z">
<title>Fallback title</title></head></html>"""


class TestParseBlogPosting:
    def test_prefers_jsonld_and_canonical(self):
        item = parse_blog_posting(POST_HTML, "https://atento.vn/blog/post-x", source_name="s")
        assert item.title == "JSON-LD headline"
        assert item.excerpt == "JSON-LD summary"
        assert item.image == "https://img/cover.jpg"
        assert item.published == "2026-08-18T10:00:00Z"
        assert item.url == "https://atento.vn/blog/canon"
        assert item.id == "post-x"  # id follows the fetched url, not the canonical

    def test_og_fallback_without_jsonld(self):
        item = parse_blog_posting(OG_ONLY, "https://example.com/blog/p")
        assert item.title == "Only OG"
        assert item.excerpt == "Desc only"
        assert item.image == "https://img/x.jpg"
        assert item.published == "2026-08-18T10:00:00Z"

    def test_excerpt_truncation(self):
        item = parse_blog_posting(POST_HTML, "https://x/p", excerpt_chars=5)
        assert item.excerpt.endswith("…")


INDEX_HTML = """<html><head><script type="application/ld+json">
{"@type":"CollectionPage","name":"Blog Atento","mainEntity":{"@type":"ItemList","itemListElement":[
 {"@type":"ListItem","position":1,"name":"First","url":"https://atento.vn/blog/first"},
 {"@type":"ListItem","position":2,"name":"Second","url":"https://atento.vn/blog/second"}
]}}</script></head><body>
<a href="/blog/first">First</a><a href="/about">About</a>
</body></html>"""

ANCHOR_ONLY = (
    '<html><body><a href="/blog/one">One</a>'
    '<a href="/blog/two">Two</a><a href="/about">x</a></body></html>'
)


class TestParseIndex:
    def test_reads_item_list(self):
        items = parse_index(INDEX_HTML, base_url="https://atento.vn/blog", source_name="s")
        assert [i.id for i in items] == ["first", "second"]
        assert items[0].title == "First"

    def test_anchor_fallback_is_absolute(self):
        items = parse_index(ANCHOR_ONLY, base_url="https://atento.vn/blog", source_name="s")
        assert {i.id for i in items} == {"one", "two"}
        assert items[0].url == "https://atento.vn/blog/one"

    def test_filters_by_prefix(self):
        items = parse_index(INDEX_HTML, base_url="https://atento.vn", path_prefix="/blog/")
        assert [i.id for i in items] == ["first", "second"]

    def test_empty_when_nothing_matches(self):
        assert parse_index("<html></html>", base_url="https://x") == []
