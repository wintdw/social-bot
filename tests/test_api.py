"""Graph API error handling and URL building (no network)."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from social_bot.destinations.facebook.api import (
    ApiError,
    GraphApi,
    check_token,
    token_status_from_debug,
)


class TestGraphApiUrls:
    def test_get_url_embeds_version_and_access_token(self):
        api = GraphApi(token="tok", api_version="v26.0")
        url = api._url("me/accounts")
        assert url == "https://graph.facebook.com/v26.0/me/accounts"

    def test_feed_fields_cover_post_and_timestamp(self):
        from social_bot.destinations.facebook.api import FEED_FIELDS

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
            lambda path, params=None: (_ for _ in ()).throw(ApiError("OAuth expired", code=190)),
        )
        with pytest.raises(ApiError):
            api.managed_pages()


class TestCreatePhotoPost:
    def test_photo_post_uploads_the_bytes_as_a_multipart_source(self, monkeypatch):
        api = GraphApi(token="tok", api_version="v26.0")
        captured = {}

        def fake_post_file(path, fields, *, field, filename, data, content_type):
            captured.update(
                path=path,
                fields=fields,
                field=field,
                filename=filename,
                data=data,
                content_type=content_type,
            )
            return {"id": "999", "post_id": "1148652808337860_999"}

        monkeypatch.setattr(api, "post_file", fake_post_file)
        resp = api.create_photo_post(
            "1148652808337860",
            "hello",
            b"\xff\xd8\xffjpeg",
            filename="p.jpg",
            content_type="image/jpeg",
        )
        assert captured["path"] == "1148652808337860/photos"
        assert captured["fields"] == {"caption": "hello"}
        assert captured["field"] == "source"
        assert captured["filename"] == "p.jpg"
        assert captured["data"] == b"\xff\xd8\xffjpeg"
        assert captured["content_type"] == "image/jpeg"
        assert resp["post_id"] == "1148652808337860_999"

    def test_photo_post_omits_empty_caption(self, monkeypatch):
        api = GraphApi(token="tok", api_version="v26.0")
        captured = {}
        monkeypatch.setattr(
            api, "post_file", lambda path, fields, **kw: captured.update(fields) or {}
        )
        api.create_photo_post("1148652808337860", "", b"jpeg")
        assert captured == {}

    def test_photo_post_private_sets_published_false(self, monkeypatch):
        api = GraphApi(token="tok", api_version="v26.0")
        captured = {}
        monkeypatch.setattr(
            api, "post_file", lambda path, fields, **kw: captured.update(fields) or {}
        )
        api.create_photo_post("1148652808337860", "hello", b"jpeg", published=False)
        assert captured == {"caption": "hello", "published": "false"}


class TestMultipartBody:
    def test_carries_the_fields_then_the_file_part(self):
        from social_bot.destinations.facebook.api import _multipart_body

        body = _multipart_body(
            "B",
            {"caption": "hi", "access_token": "tok"},
            field="source",
            filename="p.jpg",
            data=b"JPEGDATA",
            content_type="image/jpeg",
        )
        assert b'name="caption"\r\n\r\nhi\r\n' in body
        assert b'name="access_token"\r\n\r\ntok\r\n' in body
        assert b'name="source"; filename="p.jpg"' in body
        assert b"Content-Type: image/jpeg" in body
        assert b"JPEGDATA" in body
        assert body.endswith(b"--B--\r\n")


class TestCreatePost:
    def test_status_post_defaults_to_published(self, monkeypatch):
        api = GraphApi(token="tok", api_version="v26.0")
        captured = {}
        monkeypatch.setattr(api, "post", lambda path, params=None: captured.update(params) or {})
        api.create_post("1148652808337860", "hello")
        assert captured == {"message": "hello"}

    def test_private_status_post_sets_published_false(self, monkeypatch):
        api = GraphApi(token="tok", api_version="v26.0")
        captured = {}
        monkeypatch.setattr(api, "post", lambda path, params=None: captured.update(params) or {})
        api.create_post("1148652808337860", "hello", published=False)
        assert captured == {"message": "hello", "published": "false"}


class TestAddComment:
    def test_comment_targets_post_comments_endpoint(self, monkeypatch):
        api = GraphApi(token="tok", api_version="v26.0")
        captured = {}

        def fake_post(path, params=None):
            captured["path"] = path
            captured["params"] = params
            return {"id": "456"}

        monkeypatch.setattr(api, "post", fake_post)
        resp = api.add_comment("123_9", "https://atento.vn/blog/p")
        assert captured["path"] == "123_9/comments"
        assert captured["params"] == {"message": "https://atento.vn/blog/p"}
        assert resp["id"] == "456"


def test_api_requires_token():
    from social_bot.config import DEFAULTS, load_config
    from social_bot.destinations.facebook import api_from_config

    cfg = load_config("/nonexistent/config.yaml")
    assert (
        cfg["destinations"]["facebook"]["token"]
        == DEFAULTS["destinations"]["facebook"]["token"]
        == ""
    )
    with pytest.raises(ValueError):
        api_from_config(cfg, token=None)


class TestPageInfo:
    def test_requests_id_and_name_for_the_configured_page(self, monkeypatch):
        api = GraphApi(token="tok", api_version="v26.0")
        captured = {}

        def fake_get(path, params=None):
            captured["path"] = path
            captured["params"] = params
            return {"id": "1148652808337860", "name": "Atento Education"}

        monkeypatch.setattr(api, "get", fake_get)
        info = api.page_info("1148652808337860")
        assert captured["path"] == "1148652808337860"
        assert captured["params"] == {"fields": "id,name"}
        assert info["name"] == "Atento Education"


class TestDebugTokenEndpoint:
    def test_targets_debug_token_with_input_token(self, monkeypatch):
        api = GraphApi(token="tok", api_version="v26.0")
        captured = {}

        def fake_get(path, params=None):
            captured["path"] = path
            captured["params"] = params
            return {"data": {"is_valid": True, "type": "PAGE"}}

        monkeypatch.setattr(api, "get", fake_get)
        data = api.debug_token()
        assert captured["path"] == "debug_token"
        assert captured["params"] == {"input_token": "tok"}
        assert data == {"is_valid": True, "type": "PAGE"}


class TestTokenStatusFromDebug:
    def test_expiring_token(self):
        now = dt.datetime(2026, 9, 11, tzinfo=dt.UTC)
        expires = dt.datetime.fromtimestamp(1794276741, tz=dt.UTC)
        out = token_status_from_debug(
            {
                "is_valid": True,
                "type": "PAGE",
                "expires_at": 1794276741,
                "scopes": ["pages_read_engagement"],
            },
            now=now,
        )
        assert out["valid"] is True
        assert out["type"] == "PAGE"
        assert out["expires_at"] == expires.isoformat()
        assert out["never_expires"] is False
        assert out["expires_in_days"] == (expires - now).days
        assert out["scopes"] == ["pages_read_engagement"]

    def test_zero_expiry_means_never(self):
        out = token_status_from_debug({"is_valid": True, "expires_at": 0})
        assert out["never_expires"] is True
        assert out["expires_at"] is None
        assert out["expires_in_days"] is None

    def test_invalid_payload_carries_error(self):
        out = token_status_from_debug(
            {"is_valid": False, "error": {"message": "Session has expired", "code": 190}}
        )
        assert out["valid"] is False
        assert out["error"] == "Session has expired"


class TestCheckToken:
    CFG = {
        "destinations": {
            "facebook": {
                "api_version": "v26.0",
                "base_url": "https://graph.facebook.com",
                "timeout_seconds": 30.0,
                "token": "tok",
            }
        }
    }

    def _patch(self, monkeypatch, api):
        monkeypatch.setattr(
            "social_bot.destinations.facebook.api.api_from_config",
            lambda cfg, token=None: api,
        )

    def test_valid_token(self, monkeypatch):
        self._patch(
            monkeypatch, SimpleNamespace(debug_token=lambda: {"is_valid": True, "expires_at": 0})
        )
        out = check_token(self.CFG)
        assert out["valid"] is True
        assert out["never_expires"] is True

    def test_oauth_error_reports_invalid(self, monkeypatch):
        def boom():
            raise ApiError("Session has expired", code=190, error_type="OAuthException")

        self._patch(monkeypatch, SimpleNamespace(debug_token=boom))
        out = check_token(self.CFG)
        assert out["valid"] is False
        assert "expired" in out["error"]

    def test_network_error_leaves_validity_unknown(self, monkeypatch):
        def boom():
            raise ApiError("network error: timed out")

        self._patch(monkeypatch, SimpleNamespace(debug_token=boom))
        out = check_token(self.CFG)
        assert out["valid"] is None
        assert "timed out" in out["error"]

    def test_no_token_raises(self):
        cfg = {"destinations": {"facebook": {**self.CFG["destinations"]["facebook"], "token": ""}}}
        with pytest.raises(ValueError):
            check_token(cfg)
