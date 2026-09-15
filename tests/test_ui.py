"""Shared operator-UI chrome: navigation, badges, notices, layout (pure logic)."""

from __future__ import annotations

from social_bot.ui import badge, favicon_svg, layout, nav_html, notice_html


class TestNav:
    def test_active_link_is_aria_current(self):
        out = nav_html("review")
        assert 'href="/review" aria-current="page"' in out

    def test_only_the_active_link_is_marked(self):
        out = nav_html("review")
        assert 'href="/" aria-current="page"' not in out
        assert 'href="/publish" aria-current="page"' not in out


class TestBadge:
    def test_state_becomes_a_colour_class(self):
        assert 'class="badge badge-ai-draft"' in badge("ai_draft")

    def test_label_is_escaped(self):
        out = badge("<script>")
        assert "<script>" not in out
        assert "&lt;script&gt;" in out


class TestNotice:
    def test_message_is_escaped(self):
        assert "&lt;b&gt;x&lt;/b&gt;" in notice_html("<b>x</b>")

    def test_kind_selects_a_variant(self):
        assert "notice-ok" in notice_html("done", kind="success")
        assert "notice-error" in notice_html("nope", kind="error")
        assert "notice-warn" in notice_html("careful", kind="warning")

    def test_unknown_kind_falls_back_to_plain(self):
        out = notice_html("hi", kind='"><script>')
        assert "<script>" not in out
        assert 'class="notice"' in out

    def test_private_banner(self):
        out = notice_html(private=True)
        assert "Private mode" in out and "unpublished" in out


class TestLayout:
    def test_document_shape(self):
        out = layout("t", "<p>hi</p>", active="dashboard")
        assert out.lstrip().startswith("<!doctype html>")
        assert out.rstrip().endswith("</html>")

    def test_has_a_visible_focus_style(self):
        out = layout("t", "")
        assert ":focus-visible" in out and "outline" in out


class TestFavicon:
    def test_is_a_self_contained_svg(self):
        svg = favicon_svg()
        assert svg.startswith("<svg") and svg.endswith("</svg>")
        assert 'viewBox="0 0 32 32"' in svg

    def test_layout_links_the_svg_icon(self):
        out = layout("t", "")
        assert '<link rel="icon" type="image/svg+xml" href="/favicon.svg">' in out
