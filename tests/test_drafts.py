"""Draft model, state machine, and persistence (pure logic)."""

from __future__ import annotations

import json

import pytest

from social_bot.drafts import (
    AI_DRAFT,
    APPROVED,
    POSTED,
    REJECTED,
    REWRITE_CAPTION,
    REWRITE_IMAGE,
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
            voice="technical",
        )
        assert draft.state == AI_DRAFT
        assert draft.caption == "Hello"
        assert draft.hashtags == ["#a", "#b"]
        assert draft.image_prompt == "a long ledger"
        assert draft.image_style == "sketch"
        assert draft.voice == "technical"
        assert draft.updated_at  # touched

    def test_apply_rewrite_clears_a_pending_rewrite_request(self):
        draft = _draft(rewrite_requested_at="2026-09-10T08:00:00+00:00", rewrite_error="boom")
        draft.apply_rewrite(caption="Hello")
        assert draft.rewrite_requested_at == ""
        assert draft.rewrite_error == ""

    def test_apply_rewrite_clears_the_request_kind_too(self):
        draft = _draft(rewrite_requested_at="2026-09-10T08:00:00+00:00", rewrite_mode=REWRITE_IMAGE)
        draft.apply_rewrite(caption="Hello")
        assert draft.rewrite_kind() == ""


class TestImagePromptRewrite:
    """A prompt-only rewrite touches the picture, never the caption or the state."""

    def test_apply_image_prompt_keeps_the_caption_the_style_and_the_state(self):
        draft = _draft(
            state=APPROVED,
            caption="Caption đã duyệt",
            hashtags=["#Atento"],
            voice="technical",
            image_prompt="a hand-carved wooden chair",
            image_style="editorial",
        )
        draft.apply_image_prompt(image_prompt="a labelled diagram")
        assert draft.image_prompt == "a labelled diagram"
        # The treatment is the operator's pick, saved with the request: a
        # prompt-only rewrite writes the subject, it does not move the style.
        assert draft.image_style == "editorial"
        assert draft.caption == "Caption đã duyệt"
        assert draft.hashtags == ["#Atento"]
        assert draft.voice == "technical"
        assert draft.state == APPROVED  # still queued to post
        assert draft.updated_at  # touched

    def test_apply_image_prompt_clears_only_its_own_request(self):
        draft = _draft(rewrite_requested_at="2026-09-10T08:00:00+00:00", rewrite_mode=REWRITE_IMAGE)
        draft.apply_image_prompt(image_prompt="x")
        assert draft.rewrite_requested_at == ""
        assert draft.rewrite_mode == ""

    def test_a_later_caption_request_survives_a_slow_image_prompt(self):
        # The worker can post back after the operator asked for something else.
        draft = _draft(
            rewrite_requested_at="2026-09-10T08:00:00+00:00", rewrite_mode=REWRITE_CAPTION
        )
        draft.apply_image_prompt(image_prompt="x")
        assert draft.rewrite_requested_at == "2026-09-10T08:00:00+00:00"
        assert draft.image_prompt == "x"

    def test_rewrite_kind_reads_the_mode_and_defaults_to_caption(self):
        assert _draft().rewrite_kind() == ""
        # A mode with no timestamp is not a pending request.
        assert _draft(rewrite_mode=REWRITE_IMAGE).rewrite_kind() == ""
        # A request written before the field existed — or with a mode this build
        # does not know — reads as the full rewrite it was.
        stamp = "2026-09-10T08:00:00+00:00"
        assert _draft(rewrite_requested_at=stamp).rewrite_kind() == REWRITE_CAPTION
        assert (
            _draft(rewrite_requested_at=stamp, rewrite_mode="nonsense").rewrite_kind()
            == REWRITE_CAPTION
        )
        assert (
            _draft(rewrite_requested_at=stamp, rewrite_mode=REWRITE_IMAGE).rewrite_kind()
            == REWRITE_IMAGE
        )

    def test_re_imaging_is_wider_than_a_caption_rewrite(self):
        approved = _draft(state=APPROVED)
        assert approved.can_request_image_prompt()
        assert not approved.can_receive_rewrite()
        assert _draft(state=AI_DRAFT).can_request_image_prompt()

    def test_a_done_draft_cannot_be_re_imaged(self):
        assert not _draft(state=POSTED).can_request_image_prompt()
        assert not _draft(state=REJECTED).can_request_image_prompt()

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

    def test_unapprove_returns_a_queued_draft_to_ai_draft(self):
        draft = _draft()
        draft.apply_rewrite(caption="c")
        draft.approve()
        draft.unapprove()
        assert draft.state == AI_DRAFT
        assert draft.can_publish()  # still publishable, just no longer queued
        assert draft.can_receive_rewrite()  # and editable again

    def test_unapprove_drops_the_manual_queue_position(self):
        draft = _draft(queue_order=3)
        draft.apply_rewrite(caption="c")
        draft.approve()
        draft.unapprove()
        assert draft.rank == 0

    @pytest.mark.parametrize("state", [None, POSTED, REJECTED])
    def test_cannot_unapprove_a_draft_that_is_not_approved(self, state):
        draft = _draft()
        draft.apply_rewrite(caption="c")
        if state is not None:
            draft.state = state
        with pytest.raises(ValueError):
            draft.unapprove()

    def test_cannot_unapprove_a_partially_posted_draft(self):
        # One destination is live: pulling the draft would leave the rest of the
        # targets unpostable, so the approval stands.
        draft = _draft(destinations=["facebook", "linkedin"])
        draft.apply_rewrite(caption="c")
        draft.approve()
        draft.mark_posted("facebook", post_id="1_2")
        assert draft.state == APPROVED  # linkedin still pending
        with pytest.raises(ValueError):
            draft.unapprove()

    def test_a_private_send_can_still_be_unapproved(self):
        draft = _draft()
        draft.apply_rewrite(caption="c")
        draft.approve()
        draft.mark_posted("facebook", post_id="1_2", private=True)
        draft.unapprove()
        assert draft.state == AI_DRAFT

    def test_can_publish_after_rewrite(self):
        draft = _draft()
        draft.apply_rewrite(caption="c")
        assert draft.can_publish()

    def test_mark_posted(self):
        draft = _draft()
        draft.apply_rewrite(caption="c")
        draft.mark_posted("facebook", post_id="123_9", permalink="https://www.facebook.com/123_9")
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

    def test_voice_defaults_to_empty_and_round_trips(self):
        assert Draft(id="x").voice == ""
        draft = Draft(id="x", voice="funny")
        assert Draft.from_dict(draft.to_dict()).voice == "funny"

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
