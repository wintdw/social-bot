"""HTTP client for source feeds, over the standard library.

Kept apart from source.py (pure parsing) so the parse logic is testable
offline. Retries with backoff because the blog host is intermittently flaky.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request

UA = "social-bot/0.1 (+content pipeline)"


class SourceError(Exception):
    """A source fetch failure (network, HTTP, or encoding)."""


class SourceClient:
    def __init__(
        self,
        timeout: float = 30.0,
        retries: int = 2,
        user_agent: str = UA,
    ) -> None:
        self.timeout = float(timeout)
        self.retries = int(retries)
        self.user_agent = user_agent

    @classmethod
    def from_config(cls, cfg: dict) -> SourceClient:
        blog = cfg.get("blog", {})
        return cls(
            timeout=blog.get("timeout_seconds", 30.0),
            retries=blog.get("retries", 2),
            user_agent=str(blog.get("user_agent") or UA),
        )

    def get_text(self, url: str) -> str:
        """Fetch a source document as UTF-8 text, retrying transient failures."""
        last: SourceError | None = None
        for attempt in range(self.retries + 1):
            try:
                return self._once(url)
            except SourceError as exc:
                last = exc
                if attempt < self.retries:
                    time.sleep(2**attempt)
        raise last if last else SourceError(f"failed to fetch {url}")

    def _once(self, url: str) -> str:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/xml,text/xml,application/rss+xml,*/*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise SourceError(f"HTTP {exc.code} fetching {url}") from exc
        except urllib.error.URLError as exc:
            raise SourceError(f"network error fetching {url}: {exc.reason}") from exc
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SourceError(f"non-UTF-8 response from {url}") from exc
