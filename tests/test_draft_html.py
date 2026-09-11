"""Draft review HTML rendering (pure logic)."""

from __future__ import annotations

import datetime as dt

from social_bot.draft_html import (
    render_draft_html,
    render_drafts_html,
    render_message_html,
)
from social_bot.drafts import Draft

GENERATED = dt.datetime(2026, 9, 10, 12, 0)


class TestRenderDraftsHtml:
    def test_lists_drafts(self):
        draft = Draft(id="post-one", title="Hello & <b>world</b>", state="extracted")
        out = render_drafts_html([draft], generated_at=GENERATED)
        assert "/review/post-one" in out
        assert "Hello &amp; &lt;b&gt;world&lt;/b&gt;" in out
        assert "1 open draft(s)" in out

    def test_empty(self):
        out = render_drafts_html([], generated_at=GENERATED)
        assert "No open drafts" in out
        assert out.lstrip().startswith("<!doctype html>")

    def test_has_scan_button(self):
        out = render_drafts_html([], generated_at=GENERATED)
        assert 'action="/scan"' in out
        assert "Scan sources now" in out

    def test_message_notice_is_escaped(self):
        out = render_drafts_html([], message="<b>Scan started</b>", generated_at=GENERATED)
        assert "&lt;b&gt;Scan started&lt;/b&gt;" in out

    def test_private_mode_notice(self):
        out = render_drafts_html([], private=True, generated_at=GENERATED)
        assert "Private mode" in out and "unpublished" in out

    def test_no_private_notice_by_default(self):
        out = render_drafts_html([], generated_at=GENERATED)
        assert "Private mode" not in out


class TestRenderDraftHtml:
    def test_has_editable_caption_and_actions(self):
        draft = Draft(id="p", title="T", url="https://x/blog/p", caption="Body <x>",
                      state="ai_draft")
        out = render_draft_html(draft, dna="Atento voice", generated_at=GENERATED)
        assert 'id="caption"' in out and 'name="caption"' in out
        assert 'lang="vi"' in out
        assert ">Body &lt;x&gt;</textarea>" in out
        assert "/review/p/publish" in out
        assert "/review/p/reject" in out
        assert "Atento voice" in out

    def test_shows_the_composed_post_text(self):
        draft = Draft(id="p", title="T", caption="Hello", hashtags=["#Atento"],
                      state="ai_draft")
        out = render_draft_html(draft)
        assert 'id="preview-body"' in out and 'id="preview-tags"' in out
        assert 'id="caption-count"' in out
        assert "#Atento" in out

    def test_public_action_is_primary_and_labelled(self):
        out = render_draft_html(Draft(id="p", title="T", caption="Hi"))
        assert 'class="btn-primary"' in out
        assert "Post publicly" in out
        assert "This publishes to the Facebook Page." in out
        assert 'data-private="false"' in out

    def test_private_action_is_labelled_private(self):
        out = render_draft_html(Draft(id="p", title="T", caption="Hi"), private=True)
        assert "Publish privately" in out
        assert "visible to page admins only." in out
        assert 'data-private="true"' in out

    def test_next_draft_link(self):
        out = render_draft_html(Draft(id="p", title="T"), next_id="other")
        assert 'href="/review/other"' in out

    def test_state_badge_is_colour_coded(self):
        out = render_draft_html(Draft(id="p", title="T", state="ai_draft"))
        assert 'class="badge badge-ai-draft"' in out

    def test_message_kind_is_applied(self):
        out = render_draft_html(Draft(id="p", title="T"), message="Posted", message_kind="success")
        assert 'class="notice notice-ok"' in out

    def test_escapes_image_src(self):
        draft = Draft(id="p", title="T", image='x" onerror="alert(1)')
        out = render_draft_html(draft)
        assert 'onerror="alert(1)"' not in out

    def test_private_mode_notice(self):
        out = render_draft_html(Draft(id="p", title="T"), private=True)
        assert "Private mode" in out and "unpublished" in out

    def test_no_private_notice_by_default(self):
        out = render_draft_html(Draft(id="p", title="T"))
        assert "Private mode" not in out


class TestMessageHtml:
    def test_escapes(self):
        out = render_message_html("Oops", "<script>alert(1)</script>")
        assert "<script>" not in out
        assert "&lt;script&gt;" in out
