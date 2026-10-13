"""Draft model, state machine, and persistence (pure logic)."""

from __future__ import annotations

import json

import pytest

from social_bot.drafts import (
    POSTED,
    Draft,
    append_audit,
    find,
    load_drafts,
    parse_when,
    save_drafts,
)


def _draft(**kw):
    base = {
        "id": "post-one",
        "source": "atento-blog",
        "url": "https://x/blog/post-one",
        "destinations": ["facebook"],
    }
    base.update(kw)
    return Draft(**base)


class TestParseWhen:
    def test_iso_with_offset_and_z(self):
        assert parse_when("2026-09-10T07:28:25+00:00") == parse_when("2026-09-10T07:28:25Z")

    def test_fractional_seconds_and_z(self):
        assert parse_when("2026-08-17T11:15:38.291Z").year == 2026

    def test_rfc822(self):
        parsed = parse_when("Sun, 16 Aug 2026 00:00:00 GMT")
        assert (parsed.year, parsed.month, parsed.day) == (2026, 8, 16)

    def test_naive_is_assumed_utc(self):
        assert parse_when("2026-09-10T07:00:00").utcoffset().total_seconds() == 0

    @pytest.mark.parametrize("bad", ["", "   ", "last Tuesday", None])
    def test_unparseable_is_none(self, bad):
        assert parse_when(bad) is None

    def test_rfc822_and_iso_are_comparable(self):
        assert parse_when("Mon, 10 Aug 2026 00:00:00 GMT") < parse_when("2026-09-01T00:00:00Z")


class TestPersistence:
    def test_round_trip_atomic(self, tmp_path):
        path = tmp_path / "queue.json"
        drafts = [_draft(), _draft(id="post-two")]
        save_drafts(path, drafts)
        loaded = load_drafts(path)
        assert [d.id for d in loaded] == ["post-one", "post-two"]
        assert not (tmp_path / "queue.json.tmp").exists()

    def test_cache_invalidates_on_save(self, tmp_path):
        path = tmp_path / "queue.json"
        save_drafts(path, [_draft(title="one")])
        assert load_drafts(path)[0].title == "one"
        save_drafts(path, [_draft(title="two")])
        assert load_drafts(path)[0].title == "two"

    def test_cache_reflects_external_write(self, tmp_path):
        path = tmp_path / "queue.json"
        save_drafts(path, [_draft(title="one")])
        load_drafts(path)  # warm the cache
        path.write_text(json.dumps([_draft(title="two").to_dict()]), encoding="utf-8")
        assert load_drafts(path)[0].title == "two"

    def test_load_returns_independent_copies(self, tmp_path):
        path = tmp_path / "queue.json"
        save_drafts(path, [_draft(title="one")])
        first = load_drafts(path)
        first[0].title = "mutated"
        assert load_drafts(path)[0].title == "one"

    def test_missing_file_is_empty(self, tmp_path):
        assert load_drafts(tmp_path / "nope.json") == []

    def test_from_dict_ignores_unknown_keys(self):
        draft = Draft.from_dict({"id": "x", "title": "t", "legacy": 1})
        assert draft.id == "x" and draft.title == "t"

    def test_lint_defaults_to_empty_and_round_trips(self):
        assert Draft(id="x").lint == []
        draft = Draft(id="x", lint=[{"code": "hype", "message": "m"}])
        assert Draft.from_dict(draft.to_dict()).lint == [{"code": "hype", "message": "m"}]

    def test_from_dict_migrates_legacy_flat_post_fields(self):
        draft = Draft.from_dict(
            {
                "id": "x",
                "destinations": ["facebook"],
                "state": "posted",
                "post_id": "1_2",
                "permalink": "https://www.facebook.com/1_2",
                "posted_at": "2026-09-10T12:00:00+07:00",
            }
        )
        assert draft.posts["facebook"]["post_id"] == "1_2"
        assert draft.post_id == "1_2"
        assert draft.permalink == "https://www.facebook.com/1_2"
        assert draft.state == POSTED

    def test_queue_order_defaults_and_round_trips(self):
        # A draft that predates the field keeps working: 0 means "default order".
        assert Draft(id="x").queue_order == 0
        draft = Draft(id="x", queue_order=3)
        assert Draft.from_dict(draft.to_dict()).queue_order == 3
        assert Draft.from_dict({"id": "x"}).queue_order == 0

    def test_rank_coerces_rubbish_to_unset(self):
        # A hand-edited queue.json must never break the sort.
        assert Draft(id="x", queue_order=4).rank == 4
        assert Draft(id="x", queue_order=0).rank == 0
        assert Draft(id="x", queue_order=-2).rank == 0
        assert Draft.from_dict({"id": "x", "queue_order": "later"}).rank == 0

    def test_find(self):
        drafts = [_draft(), _draft(id="post-two")]
        assert find(drafts, "post-two").id == "post-two"
        assert find(drafts, "missing") is None

    def test_append_audit(self, tmp_path):
        path = tmp_path / "published.jsonl"
        append_audit(path, {"id": "x", "post_id": "1"})
        append_audit(path, {"id": "y", "post_id": "2"})
        lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        assert [line["id"] for line in lines] == ["x", "y"]

    def test_unicode_preserved(self, tmp_path):
        path = tmp_path / "queue.json"
        save_drafts(path, [_draft(title="Cách luyện Speaking")])
        assert "Cách luyện Speaking" in path.read_text(encoding="utf-8")
