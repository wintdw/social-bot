"""Advisory caption lint: the AI tells it flags (pure logic, no network)."""

from __future__ import annotations

from social_bot.caption_lint import lint_caption

CLEAN = (
    "[Học cùng Atento]\n\n"
    "Cuộc họp vừa bắt đầu.\n\n"
    "Đối tác hỏi một câu đơn giản về chi phí vận hành, và cả phòng im lặng. "
    "Không ai muốn nhận phần đó.\n\n"
    "Kiến trúc không nằm ở chỗ vẽ ra bao nhiêu service. "
    "Nó nằm ở chỗ biết ai phải chịu trách nhiệm khi mọi thứ đổ vỡ, và điều đó thì "
    "không có bảng vẽ nào trả lời thay bạn được."
)


def _codes(caption: str, recent=()) -> list[str]:
    return [warning["code"] for warning in lint_caption(caption, recent=recent)]


class TestClean:
    def test_empty_caption_has_no_warnings(self):
        assert lint_caption("") == []
        assert lint_caption("   ") == []

    def test_a_varied_caption_has_no_warnings(self):
        assert lint_caption(CLEAN) == []

    def test_every_warning_carries_a_code_and_message(self):
        warnings = lint_caption("Ai cũng biết điều này rồi.\n\nThân bài.")
        assert warnings
        assert all(w["code"] and w["message"] for w in warnings)


class TestSingleCaptionTells:
    def test_flags_a_stock_opener(self):
        assert "stock-opener" in _codes("Ai cũng biết điều này rồi.\n\nThân bài.")

    def test_flags_the_antithesis_engine(self):
        caption = (
            "Đó không phải là vấn đề tốc độ, mà là vấn đề niềm tin.\n\nCái khó không nằm ở code."
        )
        assert "antithesis" in _codes(caption)

    def test_one_antithesis_is_not_enough(self):
        assert "antithesis" not in _codes("Cái khó không nằm ở code.\n\nThân bài dài hơn hẳn.")

    def test_flags_a_flat_rhythm(self):
        caption = "\n".join("Một câu dài đúng bốn từ." for _ in range(5))
        assert "flat-rhythm" in _codes(caption)

    def test_flags_empty_hype(self):
        caption = "Đây là một cuộc cách mạng.\n\nMột câu dài hơn hẳn để nhịp không đều chút nào."
        assert "hype" in _codes(caption)

    def test_flags_the_rule_of_three(self):
        assert "rule-of-three" in _codes("Nó nhanh, gọn, chính xác.")

    def test_an_ordinal_list_is_not_a_tricolon(self):
        caption = "Thứ nhất, thứ hai, thứ ba — ba điều mình học được sau nhiều năm."
        assert "rule-of-three" not in _codes(caption)

    def test_prose_with_commas_is_not_a_tricolon(self):
        caption = "Đối tác hỏi về chi phí, rồi im lặng, và cả phòng nhìn nhau."
        assert "rule-of-three" not in _codes(caption)

    def test_a_but_clause_is_not_a_tricolon(self):
        assert "rule-of-three" not in _codes("Nghe hiển nhiên, nhưng thú thật, mình thấy đúng.")

    def test_flags_a_cliche_transition(self):
        assert "cliche" in _codes("Về cơ bản, vấn đề nằm ở chỗ khác hẳn điều mình tưởng.")


class TestCrossPostTells:
    def test_flags_a_repeated_hook(self):
        recent = ["[Học cùng Atento]\n\nCuộc họp vừa bắt đầu.\n\nThân bài hoàn toàn khác."]
        caption = "[Học cùng Atento]\n\nCuộc họp vừa bắt đầu.\n\nMột thân bài khác nữa."
        assert "repeated-hook" in _codes(caption, recent)

    def test_flags_a_repeated_closer(self):
        recent = ["Mở bài một.\n\nCái khó không nằm ở tốc độ."]
        caption = "Mở bài khác hẳn.\n\nCái khó không nằm ở tốc độ."
        assert "repeated-closer" in _codes(caption, recent)

    def test_the_required_cta_is_not_a_closer(self):
        cta = "\n\nĐọc bài gốc đầy đủ tại comment."
        recent = ["Mở bài một.\n\nChuyện con số thì để sau." + cta]
        caption = "Mở bài hai.\n\nNên mình vẫn giữ nền tảng mở." + cta
        assert "repeated-closer" not in _codes(caption, recent)

    def test_the_source_credit_is_not_a_closer(self):
        # The credit line (DNA §7.3) repeats verbatim for a frequent source; it is
        # boilerplate, not the post's own closing move.
        credit = '\n\nNguồn: Sean Goedecke — "Some post".'
        recent = ["Mở bài một.\n\nChuyện con số thì để sau." + credit]
        caption = "Mở bài hai.\n\nNên mình vẫn giữ nền tảng mở." + credit
        assert "repeated-closer" not in _codes(caption, recent)

    def test_a_real_closer_still_flags_above_the_credit_line(self):
        credit = '\n\nNguồn: Sean Goedecke — "Some post".'
        recent = ["Mở bài một.\n\nCái khó không nằm ở tốc độ." + credit]
        caption = "Mở bài hai.\n\nCái khó không nằm ở tốc độ." + credit
        assert "repeated-closer" in _codes(caption, recent)

    def test_short_lines_are_not_compared(self):
        # Below the comparison floor a match would be noise, not a repeated tell.
        recent = ["Ok."]
        assert "repeated-hook" not in _codes("Ok.\n\nMột thân bài dài hơn hẳn ở đây.", recent)
