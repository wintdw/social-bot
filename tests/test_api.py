"""Graph API error handling and URL building (no network)."""

from __future__ import annotations

import pytest

from social_bot.api import ApiError, GraphApi


class TestGraphApiUrls:
    def test_get_url_embeds_version_and_access_token(self):
        api = GraphApi(token="tok", api_version="v26.0")
        url = api._url("me/accounts")
        assert url == "https://graph.facebook.com/v26.0/me/accounts"

    def test_feed_fields_cover_post_and_timestamp(self):
        from social_bot.api import FEED_FIELDS

        for field in ("id", "message", "story", "created_time", "permalink_url"):
            assert field in FEED_FIELDS


class TestApiErrorFromPayload:
    def test_error_payload(self):
        body = {
            "error": {
                "message": "An access token is required",
                "type": "OAuthException",
                "code": 104,
                "error_subcode": 123,
                "fbtrace_id": "Abc123",
            }
        }
        err = ApiError.from_payload(body)
        assert err.code == 104
        assert err.error_type == "OAuthException"
        assert err.subcode == 123
        assert "access token is required" in str(err)

    def test_http_status_without_error_body(self):
        err = ApiError.from_payload({}, status=503)
        assert err.code == 503
        assert "503" in str(err)

    def test_non_dict_body(self):
        err = ApiError.from_payload(["not", "a", "dict"], status=400)
        assert err.code == 400


class TestManagedPagesFallback:
    def test_page_token_falls_back_to_owner(self, monkeypatch):
        """A page token has no /me/accounts -> managed_pages() == the page itself."""
        api = GraphApi(token="tok", api_version="v26.0")

        def fake_get(path, params=None):
            if path == "me/accounts":
                raise ApiError(
                    "Tried accessing nonexisting field (accounts)",
                    code=100,
                )
            assert path == "me"
            return {"id": "1148652808337860", "name": "Atento Education"}

        monkeypatch.setattr(api, "get", fake_get)
        pages = api.managed_pages()
        assert pages == [{"id": "1148652808337860", "name": "Atento Education", "category": ""}]

    def test_other_errors_still_raise(self, monkeypatch):
        api = GraphApi(token="tok", api_version="v26.0")
        monkeypatch.setattr(
            api,
            "get",
            lambda path, params=None: (_ for _ in ()).throw(
                ApiError("OAuth expired", code=190)
            ),
        )
        with pytest.raises(ApiError):
            api.managed_pages()


class TestCreatePhotoPost:
    def test_photo_post_targets_photos_with_url_and_caption(self, monkeypatch):
        api = GraphApi(token="tok", api_version="v26.0")
        captured = {}

        def fake_post(path, params=None):
            captured["path"] = path
            captured["params"] = params
            return {"id": "999", "post_id": "1148652808337860_999"}

        monkeypatch.setattr(api, "post", fake_post)
        resp = api.create_photo_post(
            "1148652808337860", "hello", "https://example.com/a.jpg"
        )
        assert captured["path"] == "1148652808337860/photos"
        assert captured["params"] == {
            "url": "https://example.com/a.jpg",
            "caption": "hello",
        }
        assert resp["post_id"] == "1148652808337860_999"

    def test_photo_post_omits_empty_caption(self, monkeypatch):
        api = GraphApi(token="tok", api_version="v26.0")
        captured = {}
        monkeypatch.setattr(
            api, "post", lambda path, params=None: captured.update(params)
        )
        api.create_photo_post("1148652808337860", "", "https://example.com/a.jpg")
        assert captured == {"url": "https://example.com/a.jpg"}

    def test_photo_post_private_sets_published_false(self, monkeypatch):
        api = GraphApi(token="tok", api_version="v26.0")
        captured = {}
        monkeypatch.setattr(
            api, "post", lambda path, params=None: captured.update(params) or {}
        )
        api.create_photo_post(
            "1148652808337860", "hello", "https://example.com/a.jpg", published=False
        )
        assert captured == {
            "url": "https://example.com/a.jpg",
            "caption": "hello",
            "published": "false",
        }


class TestCreatePost:
    def test_status_post_defaults_to_published(self, monkeypatch):
        api = GraphApi(token="tok", api_version="v26.0")
        captured = {}
        monkeypatch.setattr(
            api, "post", lambda path, params=None: captured.update(params) or {}
        )
        api.create_post("1148652808337860", "hello")
        assert captured == {"message": "hello"}

    def test_private_status_post_sets_published_false(self, monkeypatch):
        api = GraphApi(token="tok", api_version="v26.0")
        captured = {}
        monkeypatch.setattr(
            api, "post", lambda path, params=None: captured.update(params) or {}
        )
        api.create_post("1148652808337860", "hello", published=False)
        assert captured == {"message": "hello", "published": "false"}


def test_api_requires_token():
    from social_bot.api import api_from_config
    from social_bot.config import DEFAULTS, load_config

    cfg = load_config("/nonexistent/config.yaml")
    assert cfg["graph"]["token"] == DEFAULTS["graph"]["token"] == ""
    with pytest.raises(ValueError):
        api_from_config(cfg, token=None)
