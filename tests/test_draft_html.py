"""Draft review HTML rendering (pure logic)."""

from __future__ import annotations

import datetime as dt

from social_bot.draft_html import (
    render_draft_html,
    render_drafts_html,
    render_message_html,
)
from social_bot.draft_pipeline import paginate
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

    def test_row_is_titled_by_the_caption_hook(self):
        draft = Draft(
            id="p",
            title="Source headline",
            caption="[Học cùng Atento]\n\nCâu hook mở bài\n\nPhần thân.",
        )
        out = render_drafts_html([draft], generated_at=GENERATED)
        assert 'class="qtitle">Câu hook mở bài</span>' in out
        assert "Source headline" not in out
        assert '<span class="pill">[Học cùng Atento]</span>' in out

    def test_row_falls_back_to_the_source_title_when_unwritten(self):
        draft = Draft(id="p", title="Source headline", state="extracted")
        out = render_drafts_html([draft], generated_at=GENERATED)
        assert 'class="qtitle">Source headline</span>' in out

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


class TestReviewFilters:
    def test_card_shows_source_and_dates(self):
        draft = Draft(
            id="p",
            title="T",
            source="atento-blog",
            created_at="2026-09-10T07:28:25+00:00",
            published="2026-08-17T11:15:38Z",
        )
        out = render_drafts_html([draft], generated_at=GENERATED)
        assert "atento-blog" in out
        assert "<time" in out and "published 2026-08-17" in out

    def test_card_falls_back_to_queue_time_when_undated(self):
        draft = Draft(id="p", title="T", created_at="2026-09-10T07:28:25+00:00")
        out = render_drafts_html([draft], generated_at=GENERATED)
        assert "queued 2026-09-10" in out
        assert "published" not in out

    def test_rfc822_source_date_is_formatted(self):
        draft = Draft(id="p", title="T", published="Sun, 16 Aug 2026 00:00:00 GMT")
        out = render_drafts_html([draft], generated_at=GENERATED)
        # Formatted locally, so only the month is stable across timezones.
        assert "published 2026-08-" in out
        # The machine-readable attribute must be ISO 8601, never raw RFC 822.
        assert 'datetime="2026-08-16T00:00:00+00:00"' in out
        assert "GMT" not in out

    def test_unparseable_date_uses_a_span_not_a_time(self):
        draft = Draft(id="p", title="T", published="sometime")
        out = render_drafts_html([draft], generated_at=GENERATED)
        assert "<span>published sometime</span>" in out

    def test_unparseable_date_is_shown_verbatim(self):
        draft = Draft(id="p", title="T", published="sometime last week")
        out = render_drafts_html([draft], generated_at=GENERATED)
        assert "published sometime last week" in out

    def test_filter_chips_show_counts_and_filtered_total(self):
        out = render_drafts_html(
            [Draft(id="p", state="ai_draft")],
            sources=[("atento-blog", 3), ("seangoedecke", 9)],
            statuses=[("extracted", 4), ("ai_draft", 8)],
            total=12,
            generated_at=GENERATED,
        )
        assert 'class="filter-row"' in out
        assert "Extracted" in out and "AI draft" in out
        assert "seangoedecke" in out
        assert "1 of 12 open draft(s)" in out

    def test_selected_filters_are_marked_and_linked(self):
        out = render_drafts_html(
            [Draft(id="p", state="ai_draft")],
            sources=[("atento-blog", 3), ("seangoedecke", 9)],
            statuses=[("extracted", 4), ("ai_draft", 8)],
            selected_source="atento-blog",
            selected_status="ai_draft",
            total=12,
            generated_at=GENERATED,
        )
        assert 'aria-current="true"' in out
        assert "/review?source=atento-blog&amp;status=ai_draft" in out

    def test_no_filter_bar_without_choices(self):
        out = render_drafts_html([Draft(id="p", title="T")], generated_at=GENERATED)
        assert 'class="filters"' not in out

    def test_active_chip_survives_a_zero_count(self):
        out = render_drafts_html(
            [],
            sources=[("atento-blog", 0), ("seangoedecke", 12)],
            statuses=[("extracted", 0), ("ai_draft", 12)],
            selected_source="atento-blog",
            selected_status="extracted",
            total=12,
            source_total=0,
            status_total=12,
            generated_at=GENERATED,
        )
        assert "No drafts match this filter" in out
        assert "/review?source=atento-blog&amp;status=extracted" in out

    def test_filtered_empty_state_offers_a_clear_link(self):
        out = render_drafts_html(
            [],
            total=5,
            sources=[("a", 5)],
            selected_source="zzz",
            generated_at=GENERATED,
        )
        assert "No drafts match this filter" in out
        assert 'href="/review"' in out


class TestReviewPagination:
    def _page(self, total, page, per_page):
        drafts = [Draft(id=f"d{i}", title=f"T{i}") for i in range(total)]
        window, info = paginate(drafts, page=page, per_page=per_page)
        return window, info

    def test_no_pager_on_a_single_page(self):
        drafts, info = self._page(3, 1, 10)
        out = render_drafts_html(drafts, page=info, generated_at=GENERATED)
        assert "Page 1 /" not in out

    def test_first_page_links_forward_preserving_filters(self):
        drafts, info = self._page(5, 1, 2)
        out = render_drafts_html(
            drafts,
            page=info,
            sources=[("a", 5)],
            statuses=[("extracted", 5)],
            selected_source="a",
            selected_status="extracted",
            total=5,
            generated_at=GENERATED,
        )
        assert "Page 1 / 3" in out
        assert "source=a&amp;status=extracted&amp;page=2&amp;per_page=2" in out
        assert "← Newer" not in out

    def test_later_page_links_back_and_not_forward(self):
        drafts, info = self._page(5, 3, 2)
        out = render_drafts_html(drafts, page=info, total=5, generated_at=GENERATED)
        assert "Page 3 / 3" in out
        assert "← Newer" in out
        assert "Older →" not in out

    def test_header_counts_matches_not_the_page_size(self):
        drafts, info = self._page(5, 1, 2)
        out = render_drafts_html(
            drafts, page=info, total=5, matched=5, generated_at=GENERATED
        )
        assert "5 open draft(s)" in out
        assert "2 of 5" not in out

    def test_header_shows_filtered_matches_with_paging(self):
        drafts, info = self._page(5, 1, 2)
        out = render_drafts_html(
            drafts,
            page=info,
            total=12,
            matched=5,
            sources=[("a", 5)],
            selected_source="a",
            generated_at=GENERATED,
        )
        assert "5 of 12 open draft(s)" in out


class TestReviewSearch:
    def test_search_form_is_a_get_form(self):
        out = render_drafts_html([Draft(id="p", title="T")], generated_at=GENERATED)
        assert 'method="get" action="/review"' in out
        assert 'name="q"' in out and 'name="sort"' in out
        assert "Newest first" in out and "Oldest first" in out

    def test_search_form_preserves_the_active_filters(self):
        out = render_drafts_html(
            [Draft(id="p", title="T")],
            sources=[("a", 5)],
            statuses=[("ai_draft", 5)],
            selected_source="a",
            selected_status="ai_draft",
            q="kafka",
            generated_at=GENERATED,
        )
        assert '<input type="hidden" name="source" value="a">' in out
        assert '<input type="hidden" name="status" value="ai_draft">' in out
        assert 'value="kafka"' in out

    def test_search_term_is_escaped(self):
        out = render_drafts_html(
            [Draft(id="p", title="T")], q='"><script>', generated_at=GENERATED
        )
        assert "<script>" not in out

    def test_search_narrows_the_header_count(self):
        out = render_drafts_html(
            [Draft(id="p", title="T")], total=61, matched=2, q="kafka", generated_at=GENERATED
        )
        assert "2 of 61 open draft(s)" in out

    def test_filter_links_keep_the_search(self):
        out = render_drafts_html(
            [Draft(id="p", title="T")],
            sources=[("a", 5)],
            selected_source="a",
            q="kafka",
            generated_at=GENERATED,
        )
        assert "q=kafka" in out

    def test_selected_sort_is_marked(self):
        out = render_drafts_html(
            [Draft(id="p", title="T")], sort="oldest", generated_at=GENERATED
        )
        assert '<option value="oldest" selected>' in out
        assert '<option value="newest">' in out


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

    def test_image_prompt_is_editable_in_english(self):
        draft = Draft(
            id="p", title="T", image_prompt="a lone tree", state="ai_draft"
        )
        out = render_draft_html(draft)
        assert 'id="image_prompt"' in out and 'name="image_prompt"' in out
        assert 'value="a lone tree"' in out

    def test_image_prompt_is_the_image_alt(self):
        draft = Draft(
            id="p", title="T", image="https://img/x.jpg", image_prompt="a lone tree"
        )
        out = render_draft_html(draft)
        assert 'alt="a lone tree"' in out

    def test_alt_falls_back_to_the_title_without_a_prompt(self):
        out = render_draft_html(Draft(id="p", title="Title", image="https://img/x.jpg"))
        assert 'alt="Title"' in out

    def test_image_prompt_field_is_escaped(self):
        draft = Draft(id="p", title="T", image_prompt='x" onfocus="alert(1)')
        out = render_draft_html(draft)
        assert 'onfocus="alert(1)"' not in out

    def test_detail_titles_the_hook_and_keeps_the_source_title_in_the_rail(self):
        draft = Draft(
            id="p",
            title="Source headline",
            url="https://x/blog/p",
            caption="[Học cùng Atento]\n\nCâu hook mở bài\n\nPhần thân.",
            state="ai_draft",
        )
        out = render_draft_html(draft, generated_at=GENERATED)
        assert "<h1>Câu hook mở bài</h1>" in out
        # The source's own title stays visible, as provenance.
        assert "<p>Source headline</p>" in out

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
        assert "This publishes to Facebook." in out
        assert 'data-private="false"' in out

    def test_public_action_lists_multiple_destinations(self):
        draft = Draft(
            id="p", title="T", caption="Hi", destinations=["facebook", "linkedin"]
        )
        out = render_draft_html(draft)
        assert "This publishes to Facebook, LinkedIn." in out

    def test_posted_line_is_per_destination(self):
        draft = Draft(
            id="p",
            title="T",
            caption="Hi",
            state="posted",
            destinations=["facebook", "linkedin"],
            posts={
                "facebook": {"post_id": "1_2", "permalink": "https://x/fb", "posted_at": "now"},
                "linkedin": {"post_id": "li1", "permalink": "https://x/li", "posted_at": "now"},
            },
        )
        out = render_draft_html(draft)
        assert "Already posted to Facebook: https://x/fb" in out
        assert "Already posted to LinkedIn: https://x/li" in out

    def test_private_action_is_labelled_private(self):
        out = render_draft_html(Draft(id="p", title="T", caption="Hi"), private=True)
        assert "Publish privately" in out
        assert "visible to page admins only." in out
        assert 'data-private="true"' in out

    def test_save_button_saves_without_posting(self):
        out = render_draft_html(Draft(id="p", title="T", caption="Hi"))
        assert 'formaction="/review/p/save"' in out
        assert 'name="save"' in out
        assert ">Save</button>" in out

    def test_no_dry_run_button(self):
        out = render_draft_html(Draft(id="p", title="T", caption="Hi"))
        assert "Dry run" not in out

    def test_next_draft_link(self):
        out = render_draft_html(Draft(id="p", title="T"), next_id="other")
        assert 'href="/review/other"' in out

    def test_source_date_is_formatted_not_raw(self):
        # RSS pubDate is RFC 822; the header must not leak the raw string.
        out = render_draft_html(
            Draft(id="p", title="T", published="Thu, 10 Sep 2026 00:00:00 GMT")
        )
        assert "GMT" not in out
        assert "published 2026-09-10" in out

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

    def test_image_button_when_enabled(self):
        out = render_draft_html(Draft(id="p", title="T"), image_enabled=True)
        assert 'action="/review/p/image"' in out
        assert "Generate image" in out

    def test_image_button_regenerates_when_image_present(self):
        out = render_draft_html(
            Draft(id="p", title="T", image="https://img/x.jpg"), image_enabled=True
        )
        assert "Regenerate image" in out

    def test_no_image_button_unless_enabled(self):
        out = render_draft_html(Draft(id="p", title="T"))
        assert "/review/p/image" not in out

    def test_image_running_note_when_missing(self):
        out = render_draft_html(
            Draft(id="p", title="T"), image_status={"status": "running"}
        )
        assert "Generating the image in the background" in out

    def test_image_error_note_is_shown_and_escaped(self):
        out = render_draft_html(
            Draft(id="p", title="T"),
            image_status={"status": "error", "error": "<b>HTTP 520</b>"},
        )
        assert "Image generation failed" in out
        assert "&lt;b&gt;HTTP 520&lt;/b&gt;" in out

    def test_image_note_when_not_started(self):
        out = render_draft_html(Draft(id="p", title="T"), image_enabled=True)
        assert "No image yet" in out
        assert "Generate image” below" in out

    def test_no_image_note_when_image_ready(self):
        out = render_draft_html(
            Draft(id="p", title="T", image="https://img/x.jpg"),
            image_status={"status": "error", "error": "stale"},
        )
        assert "Image generation failed" not in out
        assert "No image yet" not in out
        assert "Generating the image in the background" not in out

    def test_private_mode_notice(self):
        out = render_draft_html(Draft(id="p", title="T"), private=True)
        assert "Private mode" in out and "unpublished" in out

    def test_no_private_notice_by_default(self):
        out = render_draft_html(Draft(id="p", title="T"))
        assert "Private mode" not in out

    def test_approve_and_schedule_button_when_scheduling(self):
        out = render_draft_html(
            Draft(id="p", title="T", caption="Hi", state="ai_draft"),
            scheduling=True,
            next_post="2026-09-11 09:00",
        )
        assert 'name="approve"' in out
        assert 'form="publish-form"' in out  # carries the caption/hashtag edits
        assert "Approve &amp; schedule" in out
        assert "2026-09-11 09:00" in out

    def test_no_approve_button_without_scheduling(self):
        out = render_draft_html(Draft(id="p", title="T", caption="Hi", state="ai_draft"))
        assert 'name="approve"' not in out
        assert "Approve &amp; schedule" not in out

    def test_no_approve_button_for_an_extracted_draft(self):
        out = render_draft_html(Draft(id="p", title="T"), scheduling=True)
        assert 'name="approve"' not in out

    def test_approved_draft_shows_waiting_note_without_button(self):
        out = render_draft_html(
            Draft(id="p", title="T", caption="Hi", state="approved"),
            scheduling=True,
            next_post="2026-09-11 09:00",
        )
        assert 'name="approve"' not in out
        assert "waiting for" in out
        assert "2026-09-11 09:00" in out

    def test_approved_draft_notes_a_posting_pause(self):
        out = render_draft_html(
            Draft(id="p", title="T", caption="Hi", state="approved"),
            scheduling=True,
            next_post="2026-09-11 09:00",
            posting_paused=True,
        )
        assert "posting is paused" in out

    def test_approve_note_notes_a_posting_pause(self):
        out = render_draft_html(
            Draft(id="p", title="T", caption="Hi", state="ai_draft"),
            scheduling=True,
            next_post="2026-09-11 09:00",
            posting_paused=True,
        )
        assert 'name="approve"' in out
        assert "paused, so it sends when you resume" in out

    def test_review_list_has_post_approved_now_when_scheduling(self):
        out = render_drafts_html([], scheduling=True, generated_at=GENERATED)
        assert 'action="/publish/run"' in out
        assert "Post approved now" in out

    def test_review_list_hides_post_approved_now_by_default(self):
        out = render_drafts_html([], generated_at=GENERATED)
        assert 'action="/publish/run"' not in out


class TestMessageHtml:
    def test_escapes(self):
        out = render_message_html("Oops", "<script>alert(1)</script>")
        assert "<script>" not in out
        assert "&lt;script&gt;" in out
