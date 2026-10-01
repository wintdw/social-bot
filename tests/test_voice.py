"""Voice retrieval: the operator's own messages as style for the rewriter.

Pure logic only — no network, no embedding model, no lancedb. The vector backends
are exercised manually (`social-bot voice search`); what is pinned here is the
retrieval and rendering that sits above them, plus the guarantee that a failure
degrades to an empty block instead of failing a rewrite.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from social_bot import voice
from social_bot.config import DEFAULTS


def _record(text: str, *, is_me: bool = True, chat: str = "chat", **extra) -> dict:
    return {
        "id": f"r{abs(hash((text, is_me, chat)))}",
        "chat": chat,
        "source": "telegram",
        "author": "Dung Nguyen" if is_me else "Someone",
        "is_me": is_me,
        "timestamp": "2024-03-11T09:00:00",
        "text": text,
        "reply_to": "",
        "chunk_index": 0,
        "chunk_total": 1,
        **extra,
    }


def _write_corpus(
    directory: pathlib.Path, rows: list[dict], name: str = "chat.jsonl"
) -> pathlib.Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def _cfg(tmp_path: pathlib.Path, **overrides) -> dict:
    # Every path is pinned under tmp_path: the shipped defaults point at the real
    # data/voice/ (corpus, index and profile), which a test must never read.
    corpus = overrides.pop("corpus_dir", tmp_path / "normalized")
    profile = overrides.pop("profile_file", tmp_path / "profile.md")
    index = overrides.pop("index_dir", tmp_path / "index")
    # On by default (the DEFAULTS ship it off) and on the dep-free backend: the
    # vector path needs a live embedding model, so it is a manual check — the
    # tests that reach it stub it (see TestSearchBackends).
    settings = {
        **DEFAULTS["voice"],
        "enabled": True,
        "backend": "keyword",
        "corpus_dir": str(corpus),
        "profile_file": str(profile),
        "index_dir": str(index),
        **overrides,
    }
    return {**DEFAULTS, "voice": settings}


class TestFold:
    def test_strips_vietnamese_diacritics(self):
        assert voice.fold("sinh viên") == "sinh vien"
        assert voice.fold("Đọc báo cùng Atento") == "Doc bao cung Atento"

    def test_tokenize_folds_and_lowercases(self):
        assert voice.tokenize("System Design, foundation!") == ["system", "design", "foundation"]

    def test_empty_input(self):
        assert voice.fold("") == ""
        assert voice.tokenize("") == []


class TestBM25:
    def test_ranks_the_matching_document_first(self):
        docs = ["hệ thống phân tán", "nấu ăn tối nay", "hệ thống cần scale"]
        ranked = voice.BM25(docs).top("hệ thống", 2)
        assert [index for index, _ in ranked] == [0, 2]

    def test_unaccented_query_matches_accented_text(self):
        # The whole reason fold() exists: chat is routinely typed without tones.
        docs = ["hệ thống phân tán rất hay", "nấu ăn"]
        assert voice.BM25(docs).top("he thong", 1)[0][0] == 0

    def test_no_match_is_empty(self):
        assert voice.BM25(["một hai ba"]).top("zzz", 3) == []


class TestReciprocalRankFusion:
    def test_a_document_in_both_lists_outranks_one_in_a_single_list(self):
        lexical = [{"id": "a"}, {"id": "b"}]
        semantic = [{"id": "b"}, {"id": "c"}]
        fused = voice.reciprocal_rank_fusion([lexical, semantic], 3)
        assert fused[0]["id"] == "b"

    def test_fuses_without_duplicating_rows(self):
        fused = voice.reciprocal_rank_fusion([[{"id": "a"}], [{"id": "a"}]], 5)
        assert [row["id"] for row in fused] == ["a"]

    def test_empty_lists(self):
        assert voice.reciprocal_rank_fusion([[], []], 3) == []


class TestQueryForDraft:
    def test_title_and_excerpt(self):
        query = voice.query_for_draft({"title": "Event sourcing", "excerpt": "Về cơ chế"})
        assert query == "Event sourcing\nVề cơ chế"

    def test_missing_parts_are_skipped(self):
        assert voice.query_for_draft({"excerpt": "chỉ excerpt"}) == "chỉ excerpt"

    def test_falls_back_to_the_caption(self):
        assert voice.query_for_draft({"caption": "caption cũ"}) == "caption cũ"

    def test_nothing_is_empty(self):
        assert voice.query_for_draft({}) == ""


class TestRecords:
    def test_roundtrip(self):
        row = _record("xin chào")
        record = voice.Record.from_dict(row)
        assert record.text == "xin chào"
        assert record.is_me is True
        assert record.to_dict()["reply_to"] == ""

    def test_load_records_reads_every_jsonl_and_skips_malformed_lines(self, tmp_path):
        directory = tmp_path / "normalized"
        _write_corpus(directory, [_record("một")], name="a.jsonl")
        _write_corpus(directory, [_record("hai")], name="b.jsonl")
        with (directory / "b.jsonl").open("a", encoding="utf-8") as handle:
            handle.write("{not json}\n")
        texts = [record.text for record in voice.load_records(directory)]
        assert texts == ["một", "hai"]

    def test_a_missing_directory_is_empty(self, tmp_path):
        assert voice.load_records(tmp_path / "nope") == []


class TestEnabled:
    def test_off_when_disabled(self, tmp_path):
        _write_corpus(tmp_path / "normalized", [_record("x")])
        assert voice.enabled(_cfg(tmp_path, enabled=False)) is False

    def test_off_when_there_is_no_corpus(self, tmp_path):
        assert voice.enabled(_cfg(tmp_path)) is False

    def test_on_with_a_corpus(self, tmp_path):
        _write_corpus(tmp_path / "normalized", [_record("x")])
        assert voice.enabled(_cfg(tmp_path)) is True


class TestHasVoice:
    def test_a_bare_link_is_not_voice(self):
        assert voice.has_voice("https://lms.atento.vn/courses/system-design") is False
        assert voice.has_voice("www.example.com/xem-nhe") is False

    def test_a_terse_fragment_is_still_voice(self):
        # The terseness IS the voice: only link-only text is dropped, never brevity.
        assert voice.has_voice("ngon ngon") is True
        assert voice.has_voice("hốt") is True

    def test_text_around_a_link_keeps_the_row(self):
        assert voice.has_voice("https://x.dev/a — đọc cái này nhé") is True

    def test_empty(self):
        assert voice.has_voice("") is False


class TestRenderExamples:
    def test_numbers_and_labels_the_hits(self):
        rendered = voice.render_examples(
            [{"is_me": True, "chat": "team", "timestamp": "2024-01-01", "text": "ngon ngon"}]
        )
        assert "[1] (team · me · 2024-01-01)" in rendered
        assert "ngon ngon" in rendered

    def test_names_the_other_side_when_not_me(self):
        rendered = voice.render_examples([{"is_me": False, "author": "Hieu", "text": "ok"}])
        assert "(? · Hieu · )" in rendered

    def test_cap_keeps_at_least_one(self):
        hits = [
            {"is_me": True, "chat": "c", "text": "một hai ba bốn năm sáu"},
            {"is_me": True, "chat": "c", "text": "khác"},
        ]
        assert voice.render_examples(hits, max_chars=1).count("[") == 1


class TestExamplesBlock:
    def test_returns_empty_when_disabled(self, tmp_path):
        _write_corpus(tmp_path / "normalized", [_record("hệ thống phân tán")])
        cfg = _cfg(tmp_path, enabled=False)
        assert voice.examples_block(cfg, {"title": "hệ thống"}) == ""

    def test_returns_empty_without_a_corpus(self, tmp_path):
        assert voice.examples_block(_cfg(tmp_path), {"title": "gì đó"}) == ""

    def test_returns_empty_with_no_matches(self, tmp_path):
        _write_corpus(tmp_path / "normalized", [_record("nấu ăn tối nay")])
        assert voice.examples_block(_cfg(tmp_path), {"title": "kubernetes operator"}) == ""

    def test_query_with_nothing_to_search_is_empty(self, tmp_path):
        _write_corpus(tmp_path / "normalized", [_record("bất kỳ")])
        assert voice.examples_block(_cfg(tmp_path), {}) == ""

    def test_renders_the_profile_and_the_examples(self, tmp_path):
        _write_corpus(tmp_path / "normalized", [_record("hệ thống phân tán cần scale")])
        profile = tmp_path / "profile.md"
        profile.write_text("# Learned profile\n- viết cực ngắn", encoding="utf-8")
        cfg = _cfg(tmp_path, profile_file=str(profile), backend="keyword")
        block = voice.examples_block(cfg, {"title": "hệ thống phân tán"})
        assert "viết cực ngắn" in block
        assert "real messages I wrote" in block
        assert "cần scale" in block

    def test_profile_can_be_switched_off(self, tmp_path):
        _write_corpus(tmp_path / "normalized", [_record("hệ thống phân tán")])
        profile = tmp_path / "profile.md"
        profile.write_text("# Learned profile", encoding="utf-8")
        cfg = _cfg(tmp_path, profile_file=str(profile), include_profile=False, backend="keyword")
        assert "Learned profile" not in voice.examples_block(cfg, {"title": "hệ thống"})

    def test_only_me_drops_the_other_side(self, tmp_path):
        _write_corpus(
            tmp_path / "normalized",
            [_record("hệ thống phân tán", is_me=False, chat="team")],
        )
        cfg = _cfg(tmp_path, backend="keyword")
        assert voice.examples_block(cfg, {"title": "hệ thống"}) == ""

    def test_only_me_off_keeps_the_other_side(self, tmp_path):
        _write_corpus(
            tmp_path / "normalized",
            [_record("hệ thống phân tán", is_me=False, chat="team")],
        )
        cfg = _cfg(tmp_path, backend="keyword", only_me=False)
        assert "hệ thống phân tán" in voice.examples_block(cfg, {"title": "hệ thống"})

    def test_a_retrieval_failure_degrades_to_empty(self, tmp_path, monkeypatch):
        # Voice is an enhancement, never a gate: a broken index must not fail a rewrite.
        _write_corpus(tmp_path / "normalized", [_record("hệ thống")])
        cfg = _cfg(tmp_path, backend="vector")

        def boom(*args, **kwargs):
            raise ImportError("no lancedb")

        monkeypatch.setattr(voice, "search", boom)
        assert voice.examples_block(cfg, {"title": "hệ thống"}) == ""

    def test_a_retrieval_failure_still_attaches_the_profile(self, tmp_path, monkeypatch):
        # The profile needs no retrieval, so a broken index must not cost it too.
        profile = tmp_path / "profile.md"
        profile.write_text("# Learned profile", encoding="utf-8")
        _write_corpus(tmp_path / "normalized", [_record("hệ thống")])
        cfg = _cfg(tmp_path, profile_file=str(profile), backend="vector")

        def boom(*args, **kwargs):
            raise RuntimeError("no index")

        monkeypatch.setattr(voice, "_vector_search", boom)
        assert voice.examples_block(cfg, {"title": "hệ thống"}) == "# Learned profile"

    def test_search_itself_still_raises(self, tmp_path, monkeypatch):
        # The CLI path surfaces the failure; only examples_block swallows it.
        _write_corpus(tmp_path / "normalized", [_record("hệ thống")])
        cfg = _cfg(tmp_path, backend="vector")

        def boom(*args, **kwargs):
            raise RuntimeError("no index")

        monkeypatch.setattr(voice, "_vector_search", boom)
        with pytest.raises(RuntimeError):
            voice.search(cfg, "hệ thống")


class TestSearchKeywordBackend:
    def test_returns_ranked_rows(self, tmp_path):
        _write_corpus(
            tmp_path / "normalized",
            [_record("nấu ăn"), _record("hệ thống phân tán"), _record("hệ thống cần scale")],
        )
        cfg = _cfg(tmp_path, backend="keyword")
        hits = voice.search(cfg, "hệ thống", 2)
        assert len(hits) == 2
        assert all("hệ thống" in hit["text"] for hit in hits)
        assert "_score" in hits[0]

    def test_drops_link_only_rows(self, tmp_path):
        # A shared URL tokenises as "https lms atento system design" and so can
        # outrank real prose — but as a style example it teaches nothing.
        _write_corpus(
            tmp_path / "normalized",
            [
                _record("https://lms.atento.vn/courses/system-design"),
                _record("System Design là cách chọn trade-off"),
            ],
        )
        cfg = _cfg(tmp_path, backend="keyword")
        hits = voice.search(cfg, "system design", 2)
        assert [hit["text"] for hit in hits] == ["System Design là cách chọn trade-off"]


class TestSearchBackends:
    """The dispatch and the relevance gate, with the model-dependent ranker stubbed."""

    def test_hybrid_keeps_rows_the_semantic_ranker_vetted(self, tmp_path, monkeypatch):
        row = _record("hệ thống phân tán")
        _write_corpus(tmp_path / "normalized", [row])
        cfg = _cfg(tmp_path, backend="hybrid")
        calls = {}

        def fake_vector(cfg, query, k):
            calls["k"] = k
            # Same id as the corpus row, so fusion must *merge* the similarity in
            # rather than losing it to whichever list was seen first.
            return [{**row, "_similarity": 0.72}]

        monkeypatch.setattr(voice, "_vector_search", fake_vector)
        hits = voice.search(cfg, "hệ thống", 2)
        assert [hit["text"] for hit in hits] == ["hệ thống phân tán"]
        assert calls["k"] >= 2

    def test_hybrid_drops_a_row_the_vector_ranker_never_vetted(self, tmp_path, monkeypatch):
        # BM25 matched it on a common word alone ("how"), which is exactly the
        # `in CZ we trust` failure: nothing semantic backs it up, so it goes.
        _write_corpus(tmp_path / "normalized", [_record("cái đấy là how rùi")])
        cfg = _cfg(tmp_path, backend="hybrid")
        monkeypatch.setattr(voice, "_vector_search", lambda cfg, query, k: [])
        assert voice.search(cfg, "how llms find a needle", 3) == []

    def test_min_similarity_drops_a_weak_match(self, tmp_path, monkeypatch):
        row = _record("hệ thống phân tán cần scale")
        _write_corpus(tmp_path / "normalized", [row])
        cfg = _cfg(tmp_path, backend="vector")
        monkeypatch.setattr(
            voice, "_vector_search", lambda cfg, query, k: [{**row, "_similarity": 0.42}]
        )
        assert voice.search(cfg, "hệ thống", 3) == []

    def test_a_zero_floor_switches_the_gate_off(self, tmp_path, monkeypatch):
        row = _record("hệ thống phân tán cần scale")
        _write_corpus(tmp_path / "normalized", [row])
        cfg = _cfg(tmp_path, backend="vector", min_similarity=0.0)
        monkeypatch.setattr(
            voice, "_vector_search", lambda cfg, query, k: [{**row, "_similarity": 0.42}]
        )
        assert len(voice.search(cfg, "hệ thống", 3)) == 1

    def test_min_example_words_drops_terse_fragments(self, tmp_path):
        _write_corpus(
            tmp_path / "normalized",
            [_record("hệ thống"), _record("hệ thống phân tán cần scale")],
        )
        cfg = _cfg(tmp_path, backend="keyword")
        hits = voice.search(cfg, "hệ thống", 5)
        assert [hit["text"] for hit in hits] == ["hệ thống phân tán cần scale"]

    def test_vector_backend_overfetches_before_the_gate(self, tmp_path, monkeypatch):
        _write_corpus(tmp_path / "normalized", [_record("x")])
        cfg = _cfg(tmp_path, backend="vector")
        seen = {}

        def fake_vector(cfg, query, k):
            seen["k"] = k
            return [{"id": "v", "text": "câu từ vector", "_similarity": 0.9}]

        monkeypatch.setattr(voice, "_vector_search", fake_vector)
        hits = voice.search(cfg, "x", 3)
        assert hits[0]["text"] == "câu từ vector"
        # It asks for a bigger pool than `top_k` so rows dropped by the gate can
        # still leave the block full.
        assert seen["k"] > 3


class TestStatus:
    def test_counts_records_and_mine(self, tmp_path):
        _write_corpus(
            tmp_path / "normalized",
            [_record("của tôi"), _record("của người khác", is_me=False)],
        )
        snapshot = voice.status(_cfg(tmp_path))
        assert snapshot["records"] == 2
        assert snapshot["mine"] == 1
        assert snapshot["enabled"] is True
