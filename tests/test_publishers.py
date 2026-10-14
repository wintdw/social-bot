"""Destination publishers (Graph API stubbed — no network)."""

from __future__ import annotations

import base64
import copy
import json

import pytest

from social_bot.config import DEFAULTS
from social_bot.destinations import PublisherError, publisher_for
from social_bot.destinations.facebook import FacebookPublisher
from social_bot.destinations.facebook import publisher as pub_mod
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

    def create_photo_post(
        self, page_id, caption, data, *, filename="", content_type="", published=True
    ):
        self.photo = (page_id, caption, data, filename, content_type, published)
        return {"id": "9", "post_id": "123_9"}

    def create_post(self, page_id, message, link=None, published=True):
        self.status = (page_id, message, link, published)
        return {"id": "123_8"}

    def add_comment(self, post_id, message):
        self.comment = (post_id, message)
        return {"id": "456"}


@pytest.fixture
def fake_image(monkeypatch):
    """Stand in for the image store: publish must upload whatever it returns."""
    monkeypatch.setattr(
        pub_mod.media, "load", lambda cfg, url, **kw: (b"IMGDATA", "x.jpg", "image/jpeg")
    )


def _draft(**kw):
    base = {"id": "p", "title": "Title", "url": "https://atento.vn/blog/p"}
    base.update(kw)
    return Draft(**base)


class TestFacebookPublisher:
    def test_photo_path(self, monkeypatch, fake_image):
        fake = FakeApi()
        monkeypatch.setattr(pub_mod, "api_from_config", lambda cfg, token: fake)
        monkeypatch.setattr(pub_mod.time, "sleep", lambda s: None)
        draft = _draft(image="https://img/x.jpg")
        draft.caption = "Caption"
        draft.state = "ai_draft"
        result = FacebookPublisher(_cfg()).publish(draft)
        assert fake.photo == ("123", "Caption", b"IMGDATA", "x.jpg", "image/jpeg", True)
        assert result.destination == "facebook"
        assert result.post_id == "123_9"
        assert result.permalink == "https://www.facebook.com/123_9"
        assert result.private is False

    def test_link_fallback_without_image(self, monkeypatch):
        fake = FakeApi()
        monkeypatch.setattr(pub_mod, "api_from_config", lambda cfg, token: fake)
        monkeypatch.setattr(pub_mod.time, "sleep", lambda s: None)
        draft = _draft()
        draft.caption = "Caption"
        draft.state = "ai_draft"
        FacebookPublisher(_cfg()).publish(draft)
        assert fake.status == ("123", "Caption", "https://atento.vn/blog/p", True)

    def test_hashtags_appended_to_caption(self, monkeypatch, fake_image):
        fake = FakeApi()
        monkeypatch.setattr(pub_mod, "api_from_config", lambda cfg, token: fake)
        monkeypatch.setattr(pub_mod.time, "sleep", lambda s: None)
        draft = _draft(image="https://img/x.jpg")
        draft.caption = "Caption"
        draft.state = "ai_draft"
        draft.hashtags = ["#a", "#b"]
        FacebookPublisher(_cfg()).publish(draft)
        assert fake.photo == ("123", "Caption\n\n#a #b", b"IMGDATA", "x.jpg", "image/jpeg", True)

    def test_private_mode_sends_unpublished(self, monkeypatch, fake_image):
        cfg = _cfg()
        cfg["publish"]["private"] = True
        fake = FakeApi()
        monkeypatch.setattr(pub_mod, "api_from_config", lambda cfg, token: fake)
        monkeypatch.setattr(pub_mod.time, "sleep", lambda s: None)
        draft = _draft(image="https://img/x.jpg")
        draft.caption = "Caption"
        draft.state = "ai_draft"
        result = FacebookPublisher(cfg).publish(draft)
        assert fake.photo == ("123", "Caption", b"IMGDATA", "x.jpg", "image/jpeg", False)
        assert result.private is True

    def test_photo_post_adds_url_as_first_comment(self, monkeypatch, fake_image):
        fake = FakeApi()
        monkeypatch.setattr(pub_mod, "api_from_config", lambda cfg, token: fake)
        monkeypatch.setattr(pub_mod.time, "sleep", lambda s: None)
        draft = _draft(image="https://img/x.jpg")
        draft.caption = "Caption"
        draft.state = "ai_draft"
        FacebookPublisher(_cfg()).publish(draft)
        assert fake.comment == ("123_9", "https://atento.vn/blog/p")

    def test_an_unreadable_image_fails_the_publish(self, monkeypatch):
        from social_bot import media

        fake = FakeApi()
        monkeypatch.setattr(pub_mod, "api_from_config", lambda cfg, token: fake)
        monkeypatch.setattr(
            pub_mod.media,
            "load",
            lambda cfg, url, **kw: (_ for _ in ()).throw(media.MediaError("gone")),
        )
        draft = _draft(image="https://img/x.jpg")
        draft.caption = "Caption"
        draft.state = "ai_draft"
        with pytest.raises(PublisherError):
            FacebookPublisher(_cfg()).publish(draft)

    def test_private_mode_status_post(self, monkeypatch):
        cfg = _cfg()
        cfg["publish"]["private"] = True
        fake = FakeApi()
        monkeypatch.setattr(pub_mod, "api_from_config", lambda cfg, token: fake)
        monkeypatch.setattr(pub_mod.time, "sleep", lambda s: None)
        draft = _draft()
        draft.caption = "Caption"
        draft.state = "ai_draft"
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
        draft.caption = "Caption"
        draft.state = "ai_draft"
        FacebookPublisher(_cfg()).publish(draft)
        assert fake.comment == ("123_8", "https://atento.vn/blog/p")

    def test_no_url_skips_comment(self, monkeypatch):
        fake = FakeApi()
        monkeypatch.setattr(pub_mod, "api_from_config", lambda cfg, token: fake)
        monkeypatch.setattr(pub_mod.time, "sleep", lambda s: None)
        draft = _draft(url="")
        draft.caption = "Caption"
        draft.state = "ai_draft"
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
        draft.caption = "Caption"
        draft.state = "ai_draft"
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


class TestLinkedInPublisher:
    def test_describe_and_configured(self):
        publisher = LinkedInPublisher(_cfg())
        assert publisher.describe(_draft()) == "POST http://host.docker.internal:8082/post"
        assert publisher.configured() is True

    def test_publish_posts_caption_to_gateway(self, monkeypatch):
        from social_bot.destinations.linkedin import publisher as li_mod

        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"ok": true, "post_urn": "urn:li:share:1", "permalink": "https://x/1"}'

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data)
            captured["timeout"] = timeout
            return FakeResponse()

        monkeypatch.setattr(li_mod.urllib.request, "urlopen", fake_urlopen)
        draft = _draft()
        draft.caption = "Hello"
        draft.state = "ai_draft"
        draft.hashtags = ["#a"]
        result = LinkedInPublisher(_cfg()).publish(draft)
        assert captured["url"] == "http://host.docker.internal:8082/post"
        assert captured["body"] == {
            "text": "Hello\n\n#a",
            "visibility": "PUBLIC",
            "comment": "https://atento.vn/blog/p",
        }
        assert result.post_id == "urn:li:share:1"
        assert result.permalink == "https://x/1"

    def test_publish_raises_on_gateway_error(self, monkeypatch):
        import io
        import urllib.error

        from social_bot.destinations.linkedin import publisher as li_mod

        def fake_urlopen(request, timeout=None):
            raise urllib.error.HTTPError(
                request.full_url, 502, "bad gateway", {}, io.BytesIO(b'{"ok": false}')
            )

        monkeypatch.setattr(li_mod.urllib.request, "urlopen", fake_urlopen)
        draft = _draft()
        draft.caption = "Hi"
        draft.state = "ai_draft"
        with pytest.raises(PublisherError):
            LinkedInPublisher(_cfg()).publish(draft)

    def test_gateway_timeout_is_a_publisher_error(self, monkeypatch):
        from social_bot.destinations.linkedin import publisher as li_mod

        class SlowResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                raise TimeoutError("timed out")

        monkeypatch.setattr(
            li_mod.urllib.request, "urlopen", lambda request, timeout=None: SlowResponse()
        )
        draft = _draft()
        draft.caption = "Hi"
        draft.state = "ai_draft"
        with pytest.raises(PublisherError, match="did not respond"):
            LinkedInPublisher(_cfg()).publish(draft)

    def test_publish_sends_image_bytes_as_base64(self, monkeypatch, fake_image):
        from social_bot.destinations.linkedin import publisher as li_mod

        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"ok": true, "post_urn": "urn:li:share:2", "permalink": "https://x/2"}'

        def fake_urlopen(request, timeout=None):
            captured["body"] = json.loads(request.data)
            return FakeResponse()

        monkeypatch.setattr(li_mod.urllib.request, "urlopen", fake_urlopen)
        draft = _draft(image="https://img/x.jpg")
        draft.caption = "Hello"
        draft.state = "ai_draft"
        result = LinkedInPublisher(_cfg()).publish(draft)
        assert captured["body"]["text"] == "Hello"
        assert captured["body"]["image_content_type"] == "image/jpeg"
        assert base64.b64decode(captured["body"]["image_base64"]) == b"IMGDATA"
        assert result.post_id == "urn:li:share:2"

    def test_publish_without_image_omits_image_fields(self, monkeypatch):
        from social_bot.destinations.linkedin import publisher as li_mod

        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"ok": true, "post_urn": "urn:li:share:1", "permalink": "https://x/1"}'

        def fake_urlopen(request, timeout=None):
            captured["body"] = json.loads(request.data)
            return FakeResponse()

        monkeypatch.setattr(li_mod.urllib.request, "urlopen", fake_urlopen)
        draft = _draft()
        draft.caption = "Hello"
        draft.state = "ai_draft"
        LinkedInPublisher(_cfg()).publish(draft)
        assert captured["body"] == {
            "text": "Hello",
            "visibility": "PUBLIC",
            "comment": "https://atento.vn/blog/p",
        }

    def test_the_source_link_rides_as_the_first_comment(self, monkeypatch):
        """The caption's CTA points at the comment, so the URL goes out as `comment`.

        An idea draft has no source page, so it has no link to comment.
        """
        from social_bot.destinations.linkedin import publisher as li_mod

        bodies = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"ok": true, "post_urn": "urn:li:share:9", "permalink": "https://x/9"}'

        def fake_urlopen(request, timeout=None):
            bodies.append(json.loads(request.data))
            return FakeResponse()

        monkeypatch.setattr(li_mod.urllib.request, "urlopen", fake_urlopen)
        draft = _draft()
        draft.caption = "Hello"
        draft.state = "ai_draft"
        LinkedInPublisher(_cfg()).publish(draft)
        assert bodies[0]["comment"] == "https://atento.vn/blog/p"

        idea = _draft(url="", title="", caption="Original idea")
        idea.state = "ai_draft"
        LinkedInPublisher(_cfg()).publish(idea)
        assert "comment" not in bodies[1]

    def test_image_only_draft_can_publish(self, monkeypatch, fake_image):
        from social_bot.destinations.linkedin import publisher as li_mod

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"ok": true, "post_urn": "urn:li:share:3", "permalink": ""}'

        monkeypatch.setattr(
            li_mod.urllib.request, "urlopen", lambda request, timeout=None: FakeResponse()
        )
        draft = _draft(title="", caption="", image="https://img/x.jpg")
        result = LinkedInPublisher(_cfg()).publish(draft)
        assert result.post_id == "urn:li:share:3"

    def test_an_unreadable_image_fails_the_linkedin_publish(self, monkeypatch):
        from social_bot import media
        from social_bot.destinations.linkedin import publisher as li_mod

        monkeypatch.setattr(
            li_mod.media,
            "load",
            lambda cfg, url, **kw: (_ for _ in ()).throw(media.MediaError("gone")),
        )
        draft = _draft(image="https://img/x.jpg")
        draft.caption = "Hello"
        draft.state = "ai_draft"
        with pytest.raises(PublisherError):
            LinkedInPublisher(_cfg()).publish(draft)

    def test_publisher_for_known(self):
        assert isinstance(publisher_for("facebook", _cfg()), FacebookPublisher)
        assert isinstance(publisher_for("linkedin", _cfg()), LinkedInPublisher)

    def test_publisher_for_unknown(self):
        with pytest.raises(PublisherError):
            publisher_for("mastodon", _cfg())
