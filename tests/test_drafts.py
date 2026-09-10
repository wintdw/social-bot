"""Draft model, state machine, and persistence (pure logic)."""

from __future__ import annotations

import json

import pytest

from social_bot.drafts import (
    AI_DRAFT,
    EXTRACTED,
    POSTED,
    REJECTED,
    Draft,
    append_audit,
    find,
    load_drafts,
    save_drafts,
)


def _draft(**kw):
    base = {"id": "post-one", "source": "atento-blog", "url": "https://x/blog/post-one"}
    base.update(kw)
    return Draft(**base)


class TestState:
    def test_apply_rewrite_moves_to_ai_draft(self):
        draft = _draft()
        draft.apply_rewrite(caption="Hello", hashtags=["#a", "#b"], alt_text="alt")
        assert draft.state == AI_DRAFT
        assert draft.caption == "Hello"
        assert draft.hashtags == ["#a", "#b"]
        assert draft.alt_text == "alt"
        assert draft.updated_at  # touched

    def test_cannot_approve_from_extracted(self):
        with pytest.raises(ValueError):
            _draft().approve()

    def test_can_publish_after_rewrite(self):
        draft = _draft()
        draft.apply_rewrite(caption="c")
        assert draft.can_publish()

    def test_mark_posted(self):
        draft = _draft()
        draft.apply_rewrite(caption="c")
        draft.mark_posted(post_id="123_9", permalink="https://www.facebook.com/123_9")
        assert draft.state == POSTED
        assert draft.post_id == "123_9"
        assert draft.permalink.endswith("123_9")
        assert draft.posted_at

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


class TestPersistence:
    def test_round_trip_atomic(self, tmp_path):
        path = tmp_path / "queue.json"
        drafts = [_draft(), _draft(id="post-two")]
        save_drafts(path, drafts)
        loaded = load_drafts(path)
        assert [d.id for d in loaded] == ["post-one", "post-two"]
        assert not (tmp_path / "queue.json.tmp").exists()

    def test_missing_file_is_empty(self, tmp_path):
        assert load_drafts(tmp_path / "nope.json") == []

    def test_from_dict_ignores_unknown_keys(self):
        draft = Draft.from_dict({"id": "x", "title": "t", "legacy": 1})
        assert draft.id == "x" and draft.title == "t"

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
