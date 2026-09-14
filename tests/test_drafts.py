"""Draft model, state machine, and persistence (pure logic)."""

from __future__ import annotations

import json

import pytest

from social_bot.drafts import (
    AI_DRAFT,
    APPROVED,
    EXTRACTED,
    POSTED,
    REJECTED,
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


class TestState:
    def test_apply_rewrite_moves_to_ai_draft(self):
        draft = _draft()
        draft.apply_rewrite(
            caption="Hello",
            hashtags=["#a", "#b"],
            image_prompt="a long ledger",
            image_style="sketch",
        )
        assert draft.state == AI_DRAFT
        assert draft.caption == "Hello"
        assert draft.hashtags == ["#a", "#b"]
        assert draft.image_prompt == "a long ledger"
        assert draft.image_style == "sketch"
        assert draft.updated_at  # touched

    def test_cannot_approve_from_extracted(self):
        with pytest.raises(ValueError):
            _draft().approve()

    def test_approve_moves_to_approved(self):
        draft = _draft()
        draft.apply_rewrite(caption="c")
        draft.approve()
        assert draft.state == APPROVED
        assert draft.can_publish()  # still publishable, now by the scheduler

    def test_cannot_approve_a_posted_draft(self):
        draft = _draft()
        draft.apply_rewrite(caption="c")
        draft.mark_posted("facebook", post_id="1_2")
        with pytest.raises(ValueError):
            draft.approve()

    def test_can_publish_after_rewrite(self):
        draft = _draft()
        draft.apply_rewrite(caption="c")
        assert draft.can_publish()

    def test_mark_posted(self):
        draft = _draft()
        draft.apply_rewrite(caption="c")
        draft.mark_posted(
            "facebook", post_id="123_9", permalink="https://www.facebook.com/123_9"
        )
        assert draft.state == POSTED
        assert draft.post_id == "123_9"
        assert draft.permalink.endswith("123_9")
        assert draft.posted_at
        assert draft.posts["facebook"]["post_id"] == "123_9"

    def test_per_destination_records(self):
        draft = _draft(destinations=["facebook", "linkedin"])
        draft.apply_rewrite(caption="c")
        draft.mark_posted("facebook", post_id="1_2", permalink="u1")
        assert draft.state == AI_DRAFT  # not fully posted until every target is done
        assert draft.pending_destinations() == ["linkedin"]
        draft.mark_posted("linkedin", post_id="li1", permalink="u2")
        assert draft.state == POSTED
        assert draft.posted_destinations() == ["facebook", "linkedin"]
        assert draft.post_id == "1_2"  # facebook preferred for the flat accessor
        assert draft.posts["linkedin"]["permalink"] == "u2"

    def test_private_send_does_not_complete_the_draft(self):
        draft = _draft()
        draft.apply_rewrite(caption="c")
        draft.mark_posted("facebook", post_id="1_2", private=True)
        assert draft.state == AI_DRAFT
        assert draft.post_id == ""  # private records are not "posted"
        assert draft.pending_destinations() == ["facebook"]

    def test_reject(self):
        draft = _draft()
        draft.reject()
        assert draft.state == REJECTED
        assert not draft.can_publish()

    def test_body_falls_back_to_title(self):
        assert _draft(title="Title only").body == "Title only"
        draft = _draft(title="Title")
        draft.apply_rewrite(caption="Caption")
        assert draft.body == "Caption"

    def test_post_text_appends_hashtags(self):
        draft = _draft()
        draft.apply_rewrite(caption="Caption", hashtags=["#a", "#b"])
        assert draft.post_text == "Caption\n\n#a #b"

    def test_post_text_without_hashtags(self):
        assert _draft(title="Only title").post_text == "Only title"


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

    def test_cache_reflects_external_rewrite(self, tmp_path):
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
