"""Destination publishers (Graph API stubbed — no network)."""

from __future__ import annotations

import copy

import pytest

from social_bot.config import DEFAULTS
from social_bot.destinations import PublisherError, publisher_for
from social_bot.destinations.facebook import publisher as pub_mod
from social_bot.destinations.facebook import FacebookPublisher
from social_bot.destinations.linkedin import LinkedInPublisher
from social_bot.drafts import Draft


def _cfg():
    cfg = copy.deepcopy(DEFAULTS)
    cfg["destinations"]["facebook"]["account_id"] = "123"
    return cfg


class FakeApi:
    def __init__(self):
        self.photo = None
        self.status = None
        self.comment = None

    def create_photo_post(self, page_id, caption, url, published=True):
        self.photo = (page_id, caption, url, published)
        return {"id": "9", "post_id": "123_9"}

    def create_post(self, page_id, message, link=None, published=True):
        self.status = (page_id, message, link, published)
        return {"id": "123_8"}

    def add_comment(self, post_id, message):
        self.comment = (post_id, message)
        return {"id": "456"}


def _draft(**kw):
    base = {"id": "p", "title": "Title", "url": "https://atento.vn/blog/p"}
    base.update(kw)
    return Draft(**base)


class TestFacebookPublisher:
    def test_photo_path(self, monkeypatch):
        fake = FakeApi()
        monkeypatch.setattr(pub_mod, "api_from_config", lambda cfg, token: fake)
        monkeypatch.setattr(pub_mod.time, "sleep", lambda s: None)
        draft = _draft(image="https://img/x.jpg")
        draft.apply_rewrite(caption="Caption")
        result = FacebookPublisher(_cfg()).publish(draft)
        assert fake.photo == ("123", "Caption", "https://img/x.jpg", True)
        assert result.destination == "facebook"
        assert result.post_id == "123_9"
        assert result.permalink == "https://www.facebook.com/123_9"
        assert result.private is False

    def test_link_fallback_without_image(self, monkeypatch):
        fake = FakeApi()
        monkeypatch.setattr(pub_mod, "api_from_config", lambda cfg, token: fake)
        monkeypatch.setattr(pub_mod.time, "sleep", lambda s: None)
        draft = _draft()
        draft.apply_rewrite(caption="Caption")
        FacebookPublisher(_cfg()).publish(draft)
        assert fake.status == ("123", "Caption", "https://atento.vn/blog/p", True)

    def test_hashtags_appended_to_caption(self, monkeypatch):
        fake = FakeApi()
        monkeypatch.setattr(pub_mod, "api_from_config", lambda cfg, token: fake)
        monkeypatch.setattr(pub_mod.time, "sleep", lambda s: None)
        draft = _draft(image="https://img/x.jpg")
        draft.apply_rewrite(caption="Caption", hashtags=["#a", "#b"])
        FacebookPublisher(_cfg()).publish(draft)
        assert fake.photo == ("123", "Caption\n\n#a #b", "https://img/x.jpg", True)

    def test_private_mode_sends_unpublished(self, monkeypatch):
        cfg = _cfg()
        cfg["publish"]["private"] = True
        fake = FakeApi()
        monkeypatch.setattr(pub_mod, "api_from_config", lambda cfg, token: fake)
        monkeypatch.setattr(pub_mod.time, "sleep", lambda s: None)
        draft = _draft(image="https://img/x.jpg")
        draft.apply_rewrite(caption="Caption")
        result = FacebookPublisher(cfg).publish(draft)
        assert fake.photo == ("123", "Caption", "https://img/x.jpg", False)
        assert result.private is True

    def test_private_mode_status_post(self, monkeypatch):
        cfg = _cfg()
        cfg["publish"]["private"] = True
        fake = FakeApi()
        monkeypatch.setattr(pub_mod, "api_from_config", lambda cfg, token: fake)
        monkeypatch.setattr(pub_mod.time, "sleep", lambda s: None)
        draft = _draft()
        draft.apply_rewrite(caption="Caption")
        FacebookPublisher(cfg).publish(draft)
        assert fake.status == ("123", "Caption", "https://atento.vn/blog/p", False)

    def test_private_mode_describe(self):
        cfg = _cfg()
        cfg["publish"]["private"] = True
        publisher = FacebookPublisher(cfg)
        assert publisher.describe(_draft(image="x")) == "POST /123/photos (unpublished)"
        assert publisher.describe(_draft()) == "POST /123/feed (unpublished)"

    def test_describe(self):
        publisher = FacebookPublisher(_cfg())
        assert publisher.describe(_draft(image="x")) == "POST /123/photos"
        assert publisher.describe(_draft()) == "POST /123/feed"

    def test_link_post_adds_url_as_first_comment(self, monkeypatch):
        fake = FakeApi()
        monkeypatch.setattr(pub_mod, "api_from_config", lambda cfg, token: fake)
        monkeypatch.setattr(pub_mod.time, "sleep", lambda s: None)
        draft = _draft()
        draft.apply_rewrite(caption="Caption")
        FacebookPublisher(_cfg()).publish(draft)
        assert fake.comment == ("123_8", "https://atento.vn/blog/p")

    def test_photo_post_adds_url_as_first_comment(self, monkeypatch):
        fake = FakeApi()
        monkeypatch.setattr(pub_mod, "api_from_config", lambda cfg, token: fake)
        monkeypatch.setattr(pub_mod.time, "sleep", lambda s: None)
        draft = _draft(image="https://img/x.jpg")
        draft.apply_rewrite(caption="Caption")
        FacebookPublisher(_cfg()).publish(draft)
        assert fake.comment == ("123_9", "https://atento.vn/blog/p")

    def test_no_url_skips_comment(self, monkeypatch):
        fake = FakeApi()
        monkeypatch.setattr(pub_mod, "api_from_config", lambda cfg, token: fake)
        monkeypatch.setattr(pub_mod.time, "sleep", lambda s: None)
        draft = _draft(url="")
        draft.apply_rewrite(caption="Caption")
        FacebookPublisher(_cfg()).publish(draft)
        assert fake.comment is None

    def test_comment_failure_does_not_fail_publish(self, monkeypatch):
        from social_bot.destinations.facebook.api import ApiError

        fake = FakeApi()

        def failing_comment(post_id, message):
            raise ApiError("comment failed", code=200)

        fake.add_comment = failing_comment
        monkeypatch.setattr(pub_mod, "api_from_config", lambda cfg, token: fake)
        monkeypatch.setattr(pub_mod.time, "sleep", lambda s: None)
        draft = _draft()
        draft.apply_rewrite(caption="Caption")
        result = FacebookPublisher(_cfg()).publish(draft)
        assert result.post_id == "123_8"

    def test_missing_page_id_raises(self):
        cfg = _cfg()
        cfg["destinations"]["facebook"]["account_id"] = ""
        with pytest.raises(ValueError):
            FacebookPublisher(cfg).describe(_draft())

    def test_configured_needs_token_and_account(self, monkeypatch):
        monkeypatch.delenv("SOCIAL_BOT_TOKEN", raising=False)
        monkeypatch.delenv("SOCIAL_BOT_FACEBOOK_TOKEN", raising=False)
        cfg = _cfg()
        cfg["destinations"]["facebook"]["token"] = "tok"
        assert FacebookPublisher(cfg).configured() is True
        cfg["destinations"]["facebook"]["account_id"] = ""
        assert FacebookPublisher(cfg).configured() is False


class TestLinkedInAndRegistry:
    def test_linkedin_stub_raises(self):
        with pytest.raises(PublisherError):
            LinkedInPublisher(_cfg()).publish(_draft())

    def test_linkedin_describe_and_configured(self):
        publisher = LinkedInPublisher(_cfg())
        assert publisher.describe(_draft()) == "POST https://api.linkedin.com/rest/posts"
        assert publisher.configured() is False

    def test_publisher_for_known(self):
        assert isinstance(publisher_for("facebook", _cfg()), FacebookPublisher)
        assert isinstance(publisher_for("linkedin", _cfg()), LinkedInPublisher)

    def test_publisher_for_unknown(self):
        with pytest.raises(PublisherError):
            publisher_for("mastodon", _cfg())
