"""Pipeline orchestration: scan, rewrite intake, publish (no network)."""

from __future__ import annotations

import copy
import json

import pytest

from social_bot import draft_pipeline as pipeline
from social_bot.config import DEFAULTS
from social_bot.drafts import AI_DRAFT, EXTRACTED, POSTED, REJECTED, Draft
from social_bot.source_api import SourceError

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://atento.vn/blog/post-one</loc><lastmod>2026-08-18T10:00:00Z</lastmod></url>
<url><loc>https://atento.vn/blog/post-two</loc><lastmod>2026-08-17T10:00:00Z</lastmod></url>
</urlset>"""

SOURCE_URL = "https://atento.vn/sitemap.xml"

POST_HTML = (
    "<html><head>"
    '<meta property="og:image" content="https://img/og.jpg">'
    '<script type="application/ld+json">'
    '{"@type":"BlogPosting","headline":"Post headline","description":"A summary",'
    '"image":"https://img/cover.jpg","datePublished":"2026-08-18T10:00:00Z"}'
    "</script></head></html>"
)


class FakeClient:
    def __init__(self, docs=None, fail=None):
        self.docs = docs if docs is not None else {SOURCE_URL: SITEMAP}
        self.fail = set(fail or [])
        self.calls = 0

    def get_text(self, url):
        self.calls += 1
        if url in self.fail:
            raise SourceError(f"boom {url}")
        return self.docs.get(url, POST_HTML)


class FakePublisher:
    def __init__(self):
        self.published = []

    def describe(self, draft):
        return "POST /123/photos" if draft.image else "POST /123/feed"

    def publish(self, draft):
        self.published.append(draft.id)
        return {
            "destination": "facebook",
            "post_id": "123_9",
            "permalink": "https://www.facebook.com/123_9",
        }


def _cfg(tmp_path):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["review"]["dir"] = str(tmp_path / "review")
    cfg["publish"]["dir"] = str(tmp_path / "publish")
    cfg["graph"]["page_id"] = "123"
    # Force a sitemap source so the fixtures below stay about the pipeline.
    cfg["sources"] = [
        {
            "name": "atento-blog",
            "type": "sitemap",
            "url": SOURCE_URL,
            "path_prefix": "/blog/",
            "lang": "vi",
        }
    ]
    return cfg


def _seed_draft(tmp_path, **kw):
    cfg = _cfg(tmp_path)
    draft = Draft(
        id=kw.get("id", "post-one"),
        source="atento-blog",
        url="https://atento.vn/blog/post-one",
        title=kw.get("title", "Title"),
        destinations=["facebook"],
    )
    if "state" in kw:
        draft.state = kw["state"]
    if kw.get("caption"):
        draft.caption = kw["caption"]
        draft.state = AI_DRAFT
    pipeline.save_drafts(pipeline.queue_path(cfg), [draft])
    return cfg


class TestScanSources:
    def test_adds_new_drafts_then_dedupes(self, tmp_path):
        cfg = _cfg(tmp_path)
        client = FakeClient()
        first = pipeline.scan_sources(cfg, client=client)
        assert first["added"] == 2
        assert {i["id"] for i in first["items"]} == {"post-one", "post-two"}
        draft = pipeline.get_draft(cfg, "post-one")
        assert draft.state == EXTRACTED
        assert draft.title == "Post headline"  # enriched from the post page
        assert draft.image == "https://img/cover.jpg"

        second = pipeline.scan_sources(cfg, client=client)
        assert second["added"] == 0
        assert second["total_drafts"] == 2

    def test_enrichment_failure_keeps_bare_item(self, tmp_path):
        cfg = _cfg(tmp_path)
        xml = (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://atento.vn/blog/flaky</loc></url></urlset>"
        )
        client = FakeClient(
            {SOURCE_URL: xml}, fail=["https://atento.vn/blog/flaky"]
        )
        result = pipeline.scan_sources(cfg, client=client)
        assert result["added"] == 1
        assert pipeline.get_draft(cfg, "flaky").title == ""
        assert result["errors"][0]["error"].startswith("enrich")

    def test_limit_caps_per_source(self, tmp_path):
        cfg = _cfg(tmp_path)
        result = pipeline.scan_sources(cfg, client=FakeClient(), limit=1)
        assert result["added"] == 1

    def test_index_source(self, tmp_path):
        cfg = _cfg(tmp_path)
        index_url = "https://atento.vn/blog"
        cfg["sources"][0] = {
            "name": "atento-blog",
            "type": "index",
            "url": index_url,
            "path_prefix": "/blog/",
            "lang": "vi",
        }
        index_html = (
            '<html><head><script type="application/ld+json">'
            '{"@type":"CollectionPage","mainEntity":{"@type":"ItemList",'
            '"itemListElement":[{"@type":"ListItem","name":"Listing title",'
            '"url":"https://atento.vn/blog/post-one"}]}}</script></head></html>'
        )
        result = pipeline.scan_sources(cfg, client=FakeClient({index_url: index_html}))
        assert [i["id"] for i in result["items"]] == ["post-one"]
        draft = pipeline.get_draft(cfg, "post-one")
        assert draft.title == "Post headline"  # post page headline wins over the listing
        assert draft.image == "https://img/cover.jpg"  # enriched from the post page

    def test_source_failure_is_recorded_not_raised(self, tmp_path):
        cfg = _cfg(tmp_path)
        result = pipeline.scan_sources(cfg, client=FakeClient(fail=[SOURCE_URL]))
        assert result["added"] == 0
        assert result["errors"][0]["source"] == "atento-blog"

    def test_missing_lastmod_orders_last(self, tmp_path):
        xml = (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://atento.vn/blog/no-date</loc></url>"
            "<url><loc>https://atento.vn/blog/dated</loc>"
            "<lastmod>2026-08-18T00:00:00Z</lastmod></url></urlset>"
        )
        cfg = _cfg(tmp_path)
        result = pipeline.scan_sources(cfg, client=FakeClient({SOURCE_URL: xml}))
        assert [i["id"] for i in result["items"]] == ["dated", "no-date"]


class TestRewriteIntake:
    def test_receive_rewrite(self, tmp_path):
        cfg = _seed_draft(tmp_path)
        draft = pipeline.receive_rewrite(
            cfg, "post-one", {"caption": "Hello", "hashtags": ["#a"], "alt_text": "alt"}
        )
        assert draft.state == AI_DRAFT
        assert draft.caption == "Hello"

    def test_edit_splits_hashtags(self, tmp_path):
        cfg = _seed_draft(tmp_path)
        pipeline.receive_rewrite(cfg, "post-one", {"caption": "c"})
        draft = pipeline.edit_draft(cfg, "post-one", caption="edited", hashtags="#a, #b")
        assert draft.caption == "edited"
        assert draft.hashtags == ["#a", "#b"]

    def test_reject(self, tmp_path):
        cfg = _seed_draft(tmp_path)
        assert pipeline.reject_draft(cfg, "post-one").state == REJECTED

    def test_unknown_draft_raises(self, tmp_path):
        with pytest.raises(ValueError):
            pipeline.receive_rewrite(_cfg(tmp_path), "nope", {"caption": "x"})


class TestPublish:
    def test_dry_run_does_not_publish(self, tmp_path, monkeypatch, capsys):
        cfg = _seed_draft(tmp_path, caption="Hello")
        fake = FakePublisher()
        monkeypatch.setattr(pipeline, "publisher_for", lambda name, cfg, token=None: fake)
        result = pipeline.publish_draft(cfg, "post-one", dry_run=True)
        assert result["dry_run"] is True
        assert fake.published == []
        assert pipeline.get_draft(cfg, "post-one").state == AI_DRAFT
        assert "dry-run: would POST /123/feed" in capsys.readouterr().out

    def test_publish_marks_posted_and_audits(self, tmp_path, monkeypatch):
        cfg = _seed_draft(tmp_path, caption="Hello")
        fake = FakePublisher()
        monkeypatch.setattr(pipeline, "publisher_for", lambda name, cfg, token=None: fake)
        result = pipeline.publish_draft(cfg, "post-one")
        assert fake.published == ["post-one"]
        assert result["results"][0]["post_id"] == "123_9"
        draft = pipeline.get_draft(cfg, "post-one")
        assert draft.state == POSTED
        audit = pipeline.published_path(cfg).read_text(encoding="utf-8").splitlines()
        assert json.loads(audit[0])["post_id"] == "123_9"

    def test_cannot_publish_from_extracted(self, tmp_path):
        cfg = _seed_draft(tmp_path)  # state EXTRACTED
        with pytest.raises(ValueError):
            pipeline.publish_draft(cfg, "post-one")

    def test_disabled_publishing_raises(self, tmp_path):
        cfg = _seed_draft(tmp_path, caption="Hello")
        cfg["publish"]["enabled"] = False
        with pytest.raises(ValueError):
            pipeline.publish_draft(cfg, "post-one")

    def test_daily_cap(self, tmp_path, monkeypatch):
        cfg = _seed_draft(tmp_path, caption="Hello")
        cfg["publish"]["max_per_day"] = 1
        fake = FakePublisher()
        monkeypatch.setattr(pipeline, "publisher_for", lambda name, cfg, token=None: fake)
        pipeline.publish_draft(cfg, "post-one")  # hits the cap
        pipeline.save_drafts(
            pipeline.queue_path(cfg), [Draft(id="post-two", state=AI_DRAFT, caption="x",
                                             destinations=["facebook"])]
        )
        with pytest.raises(ValueError):
            pipeline.publish_draft(cfg, "post-two")


class PrivatePublisher(FakePublisher):
    """A publisher that reports its send as private (unpublished)."""

    def describe(self, draft):
        return super().describe(draft) + " (unpublished)"

    def publish(self, draft):
        self.published.append(draft.id)
        return {
            "destination": "facebook",
            "post_id": "123_77",
            "permalink": "https://www.facebook.com/123_77",
            "private": True,
        }


class TestPublishPrivate:
    def test_private_send_keeps_draft_and_audits(self, tmp_path, monkeypatch):
        cfg = _seed_draft(tmp_path, caption="Hello")
        fake = PrivatePublisher()
        monkeypatch.setattr(pipeline, "publisher_for", lambda name, cfg, token=None: fake)
        result = pipeline.publish_draft(cfg, "post-one")
        assert result["private"] is True
        assert result["results"][0]["post_id"] == "123_77"
        assert fake.published == ["post-one"]
        # The draft stays reviewable so it can be posted publicly later.
        assert pipeline.get_draft(cfg, "post-one").state == AI_DRAFT
        audit = pipeline.published_path(cfg).read_text(encoding="utf-8").splitlines()
        record = json.loads(audit[0])
        assert record["private"] is True
        assert record["post_id"] == "123_77"

    def test_private_sends_do_not_consume_the_daily_cap(self, tmp_path, monkeypatch):
        cfg = _seed_draft(tmp_path, caption="Hello")
        cfg["publish"]["max_per_day"] = 1
        fake = PrivatePublisher()
        monkeypatch.setattr(pipeline, "publisher_for", lambda name, cfg, token=None: fake)
        pipeline.publish_draft(cfg, "post-one")
        pipeline.publish_draft(cfg, "post-one")  # would raise if private counted
        assert len(fake.published) == 2

    def test_dry_run_private_mentions_unpublished(self, tmp_path, monkeypatch, capsys):
        cfg = _seed_draft(tmp_path, caption="Hello")
        monkeypatch.setattr(
            pipeline, "publisher_for", lambda name, cfg, token=None: PrivatePublisher()
        )
        pipeline.publish_draft(cfg, "post-one", dry_run=True)
        assert "dry-run: would POST /123/feed (unpublished)" in capsys.readouterr().out

    def test_status_reports_private_mode(self, tmp_path, monkeypatch):
        cfg = _seed_draft(tmp_path, caption="Hello")
        cfg["publish"]["private"] = True
        monkeypatch.setattr(
            pipeline, "publisher_for", lambda name, cfg, token=None: PrivatePublisher()
        )
        pipeline.publish_draft(cfg, "post-one")
        snapshot = pipeline.status(cfg)
        assert snapshot["publish"]["private"] is True
        assert snapshot["published"]["private"] == 1
        assert snapshot["drafts"]["open"] == 1  # still in the queue


class TestDna:
    def test_reads_file(self, tmp_path):
        dna = tmp_path / "dna.md"
        dna.write_text("Atento voice", encoding="utf-8")
        cfg = _cfg(tmp_path)
        cfg["publish"]["dna_file"] = str(dna)
        assert pipeline.dna_text(cfg) == "Atento voice"

    def test_absent_is_empty(self, tmp_path):
        cfg = _cfg(tmp_path)
        cfg["publish"]["dna_file"] = str(tmp_path / "nope.md")
        assert pipeline.dna_text(cfg) == ""

    def test_unset_is_empty(self, tmp_path):
        assert pipeline.dna_text(_cfg(tmp_path)) == ""


class TestStatus:
    def test_counts_after_scan(self, tmp_path):
        cfg = _cfg(tmp_path)
        pipeline.scan_sources(cfg, client=FakeClient())
        snapshot = pipeline.status(cfg)
        assert snapshot["seen"] == 2
        assert snapshot["drafts"]["total"] == 2
        assert snapshot["drafts"]["open"] == 2
        assert snapshot["drafts"]["by_state"]["extracted"] == 2
        assert snapshot["sources"][0]["name"] == "atento-blog"
        assert snapshot["publish"]["destinations"] == ["facebook"]
        assert snapshot["publish"]["dna_file_set"] is False

    def test_recent_posted(self, tmp_path, monkeypatch):
        cfg = _seed_draft(tmp_path, caption="Hello")
        monkeypatch.setattr(
            pipeline, "publisher_for", lambda name, cfg, token=None: FakePublisher()
        )
        pipeline.publish_draft(cfg, "post-one")
        snapshot = pipeline.status(cfg)
        assert snapshot["published"]["total"] == 1
        assert snapshot["published"]["recent"][0]["post_id"] == "123_9"
        assert snapshot["drafts"]["by_state"]["posted"] == 1
        assert snapshot["drafts"]["open"] == 0
