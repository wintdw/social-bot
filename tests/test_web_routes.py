"""`serve` route smoke tests (skipped without the [server] test extras).

The handlers are the one part of web.py that pure tests cannot reach, and it is
the largest module. These are smoke tests, not a second full suite: they prove
every page renders, the JSON endpoints answer, and a state change persists.
"""

from __future__ import annotations

import importlib.util

import pytest

pytest.importorskip("fastapi")
if importlib.util.find_spec("httpx2") is None:  # starlette prefers httpx2
    pytest.importorskip("httpx")

import yaml
from fastapi.testclient import TestClient

from social_bot import web


@pytest.fixture
def client(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "feed": {"dir": str(tmp_path / "feed")},
                "review": {"dir": str(tmp_path / "review")},
                "publish": {"dir": str(tmp_path / "publish")},
            }
        ),
        encoding="utf-8",
    )
    # /api/status and /status read the sibling LinkedIn gateway; stub it so the
    # suite never touches the network.
    monkeypatch.setattr(
        web,
        "linkedin_status",
        lambda cfg, timeout=None: {"ok": False, "error": "stubbed"},
    )
    app = web.create_app(
        config_path=str(config_path),
        refresh_at=["07:00"],
        scan_at=["06:00"],
        post_at=[],
    )
    with TestClient(app) as test_client:
        yield test_client


def test_liveness_and_favicon(client):
    assert client.get("/live").json() == {"status": "alive"}
    favicon = client.get("/favicon.svg")
    assert favicon.status_code == 200
    assert "svg" in favicon.headers["content-type"]


def test_operator_pages_render(client):
    for path in ("/", "/review", "/queue", "/publish", "/status"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "Social Content Factory" in response.text


def test_json_endpoints(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    status = client.get("/api/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["linkedin"]["ok"] is False
    assert "drafts" in payload and "post" in payload

    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"


def test_health_flags_a_broken_gateway(client, monkeypatch):
    """The health check (and its metrics) must not shrug at a dead destination."""
    monkeypatch.setattr(
        web,
        "linkedin_status",
        lambda cfg, timeout=None: {
            "configured": True,
            "ok": False,
            "error": "linkedin: cannot reach the gateway: refused",
        },
    )
    health = client.get("/health")
    assert health.status_code == 503
    payload = health.json()
    assert payload["status"] == "degraded"
    assert any(issue["kind"] == "linkedin_gateway_down" for issue in payload["issues"])

    metrics = client.get("/metrics")
    assert "social_bot_health_ok 0" in metrics.text
    assert 'social_bot_issue{kind="linkedin_gateway_down"} 1.0' in metrics.text

    status = client.get("/api/status").json()
    assert status["health"]["status"] == "degraded"

    # This is the path the blackbox probe watches: an unhealthy pipeline must
    # fail it, so the existing HTTP-probe alert fires without a second rule.
    ready = client.get("/ready")
    assert ready.status_code == 503
    assert "pipeline_ok" in ready.json()["failed"]


def test_ready_counts_a_live_poster(tmp_path, monkeypatch):
    """Timed posting is optional, but when on, its loop is part of readiness."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "feed": {"dir": str(tmp_path / "feed")},
                "review": {"dir": str(tmp_path / "review")},
                "publish": {"dir": str(tmp_path / "publish")},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        web, "linkedin_status", lambda cfg, timeout=None: {"ok": False, "error": "stubbed"}
    )
    app = web.create_app(
        config_path=str(config_path),
        refresh_at=["07:00"],
        scan_at=["06:00"],
        post_at=["20:00"],
    )
    with TestClient(app) as test_client:
        ready = test_client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["checks"]["schedulers_alive"] is True


def test_pause_and_resume_round_trip(client):
    paused = client.post("/publish/pause")
    assert paused.status_code == 200
    assert paused.json()["paused"] is True
    assert client.get("/api/status").json()["post"]["paused"] is True

    resumed = client.post("/publish/resume")
    assert resumed.status_code == 200
    assert resumed.json()["paused"] is False
    assert client.get("/api/status").json()["post"]["paused"] is False


def test_queue_reset_redirects(client):
    response = client.post("/queue/reset", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/")


def test_missing_media_and_draft_are_404(client):
    assert client.get("/videos/nope.mp4").status_code == 404
    assert client.get("/images/nope.png").status_code == 404
    assert client.get("/review/missing").status_code == 404
