"""Minimal Facebook Graph API client over the standard library.

The Graph API is plain HTTPS + JSON, so no browser and no third-party HTTP
dependency: urllib.request handles GET (feed reads) and form-encoded POST
(status/link posts and photo posts from a public image URL). Access is
token-based — see README for how to mint a Page access token with the right
permissions.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .config import resolve_token

UA = "social-bot/0.1 (Graph API client)"

# Permissions the page token needs (granted on the token, not in this code):
#   pages_read_engagement  -> read the page feed
#   pages_manage_posts     -> post to the page
#   pages_show_list        -> `whoami` lists the pages the token can manage

FEED_FIELDS = "id,created_time,message,story,permalink_url,status_type,from{name,id}"


class ApiError(Exception):
    """A Graph API error: HTTP failure or an FB error payload."""

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        error_type: str | None = None,
        subcode: int | None = None,
        fbtrace: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.error_type = error_type
        self.subcode = subcode
        self.fbtrace = fbtrace

    @classmethod
    def from_payload(cls, body: dict, *, status: int | None = None) -> "ApiError":
        """Build an ApiError from a decoded Graph API error response."""
        err = body.get("error", {}) if isinstance(body, dict) else {}
        message = (
            err.get("message")
            or (body.get("message") if isinstance(body, dict) else None)
            or "unknown error"
        )
        if status and not err:
            message = f"HTTP {status}: {message}"
        return cls(
            str(message),
            code=err.get("code") or status,
            error_type=err.get("type"),
            subcode=err.get("error_subcode"),
            fbtrace=err.get("fbtrace_id"),
        )


def api_from_config(cfg: dict, token: str | None = None) -> "GraphApi":
    """Build a GraphApi from config, resolving the token (flag/env/credentials)."""
    graph = cfg["graph"]
    tok = resolve_token(token, cfg)
    if not tok:
        raise ValueError(
            "no access token: set SOCIAL_BOT_TOKEN, pass --token, "
            "or fill graph.token in credentials.yaml"
        )
    return GraphApi(
        token=tok,
        api_version=graph["api_version"],
        base_url=graph["base_url"],
        timeout=float(graph["timeout_seconds"]),
    )


class GraphApi:
    def __init__(
        self,
        token: str,
        api_version: str,
        base_url: str = "https://graph.facebook.com",
        timeout: float = 30.0,
    ) -> None:
        self.token = token
        self.api_version = api_version
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # -- HTTP plumbing -------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{self.api_version}/{path.lstrip('/')}"

    def _request(self, method: str, path: str, params: dict | None = None) -> Any:
        url = self._url(path)
        payload = dict(params or {})
        if method == "GET":
            payload["access_token"] = self.token
            url = f"{url}?{urllib.parse.urlencode(payload)}"
            data = None
        else:
            payload["access_token"] = self.token
            data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "User-Agent": UA,
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                status = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
        except urllib.error.URLError as exc:
            raise ApiError(f"network error: {exc.reason}") from exc
        try:
            body = json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError as exc:
            raise ApiError(f"non-JSON response (HTTP {status})") from exc
        if (isinstance(body, dict) and "error" in body) or status >= 400:
            raise ApiError.from_payload(body if isinstance(body, dict) else {}, status=status)
        return body

    def get(self, path: str, params: dict | None = None) -> Any:
        return self._request("GET", path, params)

    def post(self, path: str, params: dict | None = None) -> Any:
        return self._request("POST", path, params)

    # -- Endpoints ------------------------------------------------------

    def me(self) -> dict:
        """The token's owner (user or page)."""
        return self.get("me", {"fields": "id,name"})

    def managed_pages(self) -> list[dict]:
        """Pages the token can manage.

        A *user* token lists its pages via ``/me/accounts``. A *page* token has
        no such endpoint (the token owner *is* the page), so when the API
        rejects the field we fall back to the owner itself.
        """
        try:
            data = self.get("me/accounts", {"fields": "id,name,category"})
            return data.get("data", [])
        except ApiError as exc:
            if exc.code != 100:  # 100 = "Tried accessing nonexisting field (accounts)"
                raise
            me = self.me()
            return [{"id": me.get("id"), "name": me.get("name"), "category": ""}]

    def page_feed(self, page_id: str, limit: int = 10) -> list[dict]:
        """The page's own feed, newest first."""
        data = self.get(
            f"{page_id}/feed",
            {"fields": FEED_FIELDS, "limit": limit},
        )
        return data.get("data", [])

    def create_post(
        self,
        page_id: str,
        message: str,
        link: str | None = None,
        published: bool = True,
    ) -> dict:
        """Create a status (or link) post on the page; returns the response.

        ``published=False`` creates an unpublished post (visible to page admins
        only) — the Graph API's "private mode" for testing without going public.
        """
        params: dict[str, Any] = {"message": message}
        if link:
            params["link"] = link
        if not published:
            params["published"] = "false"
        return self.post(f"{page_id}/feed", params)

    def create_photo_post(
        self,
        page_id: str,
        caption: str,
        url: str,
        published: bool = True,
    ) -> dict:
        """Publish a photo to the page from a publicly reachable image URL.

        Graph fetches the image itself, so no multipart upload and no extra
        dependency. The response carries both the photo id (``id``) and the
        feed post id (``post_id``); use ``post_id`` for the permalink.
        ``published=False`` uploads the photo without publishing it.
        """
        params: dict[str, Any] = {"url": url}
        if caption:
            params["caption"] = caption
        if not published:
            params["published"] = "false"
        return self.post(f"{page_id}/photos", params)
