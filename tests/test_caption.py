"""Caption text conventions shared by the feed and the review queue (pure logic)."""

from __future__ import annotations

from social_bot.caption import TITLE_MAX, display_title, leading_masthead, split_title


class TestLeadingMasthead:
    def test_reads_a_masthead_on_the_first_line(self):
        assert leading_masthead("[Học cùng Atento]\n\nNội dung") == "[Học cùng Atento]"

    def test_ignores_a_bracket_that_is_not_the_whole_line(self):
        assert leading_masthead("[draft] mở đầu ở đây") == ""

    def test_empty_without_a_masthead(self):
        assert leading_masthead("Chỉ là một câu hook.") == ""

    def test_empty_caption(self):
        assert leading_masthead("") == ""

    def test_skips_leading_blank_lines(self):
        assert leading_masthead("\n\n[Học cùng Atento]\n\nNội dung") == "[Học cùng Atento]"


class TestSplitTitle:
    def test_the_hook_under_the_masthead_is_the_title(self):
        assert split_title("[Học cùng Atento]\n\nNội dung") == ("Nội dung", "")

    def test_the_masthead_is_not_the_title(self):
        title, _ = split_title("[Học cùng Atento]\n\nCâu hook\n\nThân bài")
        assert title == "Câu hook"

    def test_body_follows_the_title(self):
        assert split_title("[Học cùng Atento]\n\nCâu hook\n\nThân bài") == (
            "Câu hook",
            "Thân bài",
        )

    def test_blank_lines_between_masthead_and_hook_are_skipped(self):
        assert split_title("[Học cùng Atento]\n\n\n\nCâu hook\n\nThân bài") == (
            "Câu hook",
            "Thân bài",
        )

    def test_a_lone_masthead_is_its_own_title(self):
        assert split_title("[Học cùng Atento]") == ("[Học cùng Atento]", "")

    def test_first_line_is_the_title_when_there_is_no_masthead(self):
        assert split_title("Câu hook\n\nThân bài") == ("Câu hook", "Thân bài")

    def test_single_line_has_no_body(self):
        assert split_title("Chỉ một dòng") == ("Chỉ một dòng", "")

    def test_empty_caption(self):
        assert split_title("") == ("", "")

    def test_leading_blank_lines_are_skipped(self):
        assert split_title("\n\n  Câu hook\n\nThân bài") == ("Câu hook", "Thân bài")

    def test_long_first_line_is_truncated_to_the_limit(self):
        title, _ = split_title("x" * (TITLE_MAX + 20))
        assert title == "x" * (TITLE_MAX - 1) + "…"
        assert len(title) == TITLE_MAX

    def test_a_long_hook_is_truncated_under_its_masthead(self):
        title, body = split_title("[Học cùng Atento]\n\n" + "x" * (TITLE_MAX + 20))
        assert title == "x" * (TITLE_MAX - 1) + "…"
        assert body == ""


class TestDisplayTitle:
    def test_prefers_the_caption_hook(self):
        assert display_title("[Học cùng Atento]\n\nCâu hook", "Source headline") == "Câu hook"

    def test_falls_back_to_the_source_title_without_a_caption(self):
        assert display_title("", "Source headline") == "Source headline"

    def test_falls_back_when_the_caption_is_blank(self):
        assert display_title("   \n\n", "Source headline") == "Source headline"
