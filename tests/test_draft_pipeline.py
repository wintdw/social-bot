"""Pipeline orchestration: scan, rewrite intake, publish (no network)."""

from __future__ import annotations

import copy
import datetime as dt
import json

import pytest

from social_bot import draft_pipeline as pipeline
from social_bot.config import DEFAULTS
from social_bot.drafts import AI_DRAFT, APPROVED, EXTRACTED, POSTED, REJECTED, Draft
from social_bot.image_gen import DEFAULT_BASE_URL
from social_bot.publishers import PublisherError
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
        source=kw.get("source", "atento-blog"),
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


HOC = "[Học cùng Atento]"
DOC_BAO = "[Đọc báo cùng Atento]"
MOI_NGAY = "[Mỗi ngày 1 kiến thức mới]"


def _set_mastheads(cfg, *, choices=(HOC, DOC_BAO, MOI_NGAY), default=DOC_BAO):
    """Configure publish.mastheads on a test config."""
    cfg["publish"]["mastheads"] = {
        "choices": list(choices),
        "default": default,
    }
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

    def test_receive_rewrite_prepends_the_default(self, tmp_path):
        cfg = _set_mastheads(_seed_draft(tmp_path))
        draft = pipeline.receive_rewrite(cfg, "post-one", {"caption": "Hello"})
        assert draft.caption == f"{DOC_BAO}\n\nHello"
        assert draft.post_text.startswith(DOC_BAO)

    def test_keeps_the_rewriters_chosen_masthead(self, tmp_path):
        """A post the rewriter judged worth learning keeps [Học] whatever its source."""
        cfg = _set_mastheads(_seed_draft(tmp_path, source="seangoedecke"))
        draft = pipeline.receive_rewrite(cfg, "post-one", {"caption": f"{HOC}\n\nHello"})
        assert draft.caption == f"{HOC}\n\nHello"

    def test_receive_rewrite_does_not_double_the_masthead(self, tmp_path):
        cfg = _set_mastheads(_seed_draft(tmp_path))
        draft = pipeline.receive_rewrite(cfg, "post-one", {"caption": f"{DOC_BAO}\n\nHello"})
        assert draft.caption == f"{DOC_BAO}\n\nHello"
        assert draft.caption.count(DOC_BAO) == 1

    def test_unset_mastheads_leave_the_caption_alone(self, tmp_path):
        cfg = _seed_draft(tmp_path)  # DEFAULTS: no mastheads configured
        draft = pipeline.receive_rewrite(cfg, "post-one", {"caption": "Hello"})
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


class TestApplyMasthead:
    def _seed(self, tmp_path, drafts, **mastheads):
        cfg = _set_mastheads(_cfg(tmp_path), **mastheads)
        pipeline.save_drafts(pipeline.queue_path(cfg), drafts)
        return cfg

    def test_fills_the_default_when_missing(self, tmp_path):
        cfg = self._seed(
            tmp_path,
            [
                Draft(id="own", source="atento-blog", state=AI_DRAFT, caption="Bài của Atento"),
                Draft(id="ext", source="seangoedecke", state=AI_DRAFT, caption="Bài ngoài"),
            ],
        )
        result = pipeline.apply_masthead(cfg)
        assert result["updated"] == 2
        assert result["masthead"] == DOC_BAO
        assert pipeline.get_draft(cfg, "own").caption == f"{DOC_BAO}\n\nBài của Atento"
        assert pipeline.get_draft(cfg, "ext").caption == f"{DOC_BAO}\n\nBài ngoài"

    def test_never_replaces_a_chosen_label(self, tmp_path):
        """A label is a content judgment — the backfill must not overrule it."""
        cfg = self._seed(
            tmp_path,
            [
                Draft(
                    id="ext",
                    source="seangoedecke",
                    state=AI_DRAFT,
                    caption=f"{HOC}\n\nBài đáng học",
                )
            ],
        )
        assert pipeline.apply_masthead(cfg)["updated"] == 0
        assert pipeline.get_draft(cfg, "ext").caption == f"{HOC}\n\nBài đáng học"

    def test_is_idempotent(self, tmp_path):
        cfg = self._seed(
            tmp_path,
            [Draft(id="ext", source="seangoedecke", state=AI_DRAFT, caption="Hello")],
        )
        assert pipeline.apply_masthead(cfg)["updated"] == 1
        assert pipeline.apply_masthead(cfg)["updated"] == 0
        assert pipeline.get_draft(cfg, "ext").caption == f"{DOC_BAO}\n\nHello"

    def test_never_touches_the_image(self, tmp_path):
        cfg = self._seed(
            tmp_path,
            [
                Draft(
                    id="ext",
                    source="seangoedecke",
                    state=AI_DRAFT,
                    caption="Hello",
                    image="https://img/a.jpg",
                )
            ],
        )
        pipeline.apply_masthead(cfg)
        assert pipeline.get_draft(cfg, "ext").image == "https://img/a.jpg"

    def test_skips_captionless_and_closed_drafts(self, tmp_path):
        cfg = self._seed(
            tmp_path,
            [
                Draft(id="none", source="seangoedecke", state=AI_DRAFT, caption=""),
                Draft(id="posted", source="seangoedecke", state=POSTED, caption="Old"),
                Draft(id="ok", source="seangoedecke", state=AI_DRAFT, caption="Hello"),
            ],
        )
        result = pipeline.apply_masthead(cfg)
        assert result["ids"] == ["ok"]
        assert pipeline.get_draft(cfg, "posted").caption == "Old"

    def test_only_selected_drafts(self, tmp_path):
        cfg = self._seed(
            tmp_path,
            [
                Draft(id="a", source="seangoedecke", state=AI_DRAFT, caption="A"),
                Draft(id="b", source="seangoedecke", state=AI_DRAFT, caption="B"),
            ],
        )
        result = pipeline.apply_masthead(cfg, draft_ids=["b"])
        assert result["ids"] == ["b"]
        assert pipeline.get_draft(cfg, "a").caption == "A"

    def test_unknown_draft_raises(self, tmp_path):
        cfg = self._seed(
            tmp_path, [Draft(id="a", source="seangoedecke", state=AI_DRAFT, caption="A")]
        )
        with pytest.raises(ValueError):
            pipeline.apply_masthead(cfg, draft_ids=["nope"])

    def test_limit_caps_updates(self, tmp_path):
        cfg = self._seed(
            tmp_path,
            [
                Draft(id=f"d{i}", source="seangoedecke", state=AI_DRAFT, caption="x")
                for i in range(3)
            ],
        )
        assert pipeline.apply_masthead(cfg, limit=2)["updated"] == 2
        assert pipeline.apply_masthead(cfg)["updated"] == 1

    def test_unconfigured_raises(self, tmp_path):
        cfg = _cfg(tmp_path)  # DEFAULTS: no mastheads
        pipeline.save_drafts(
            pipeline.queue_path(cfg), [Draft(id="a", state=AI_DRAFT, caption="A")]
        )
        with pytest.raises(ValueError):
            pipeline.apply_masthead(cfg)


class TestQueueListing:
    def _seed(self, tmp_path, drafts):
        cfg = _cfg(tmp_path)
        pipeline.save_drafts(pipeline.queue_path(cfg), drafts)
        return cfg

    def test_list_drafts_is_newest_first(self, tmp_path):
        cfg = self._seed(
            tmp_path,
            [
                Draft(id="old", state=EXTRACTED, created_at="2026-09-01T07:00:00+00:00"),
                Draft(id="new", state=EXTRACTED, created_at="2026-09-10T07:00:00+00:00"),
                Draft(id="mid", state=EXTRACTED, created_at="2026-09-05T07:00:00+00:00"),
            ],
        )
        assert [d.id for d in pipeline.list_drafts(cfg, pipeline.OPEN_STATES)] == [
            "new",
            "mid",
            "old",
        ]

    def test_sorts_by_source_date_not_queue_time(self, tmp_path):
        """A scan queues a batch within seconds — created_at is near-useless."""
        cfg = self._seed(
            tmp_path,
            [
                Draft(
                    id="old-post",
                    state=EXTRACTED,
                    published="2026-08-01T00:00:00Z",
                    created_at="2026-09-11T15:20:10+00:00",
                ),
                Draft(
                    id="new-post",
                    state=EXTRACTED,
                    published="2026-09-10T00:00:00Z",
                    created_at="2026-09-11T15:20:00+00:00",
                ),
            ],
        )
        assert [d.id for d in pipeline.list_drafts(cfg, pipeline.OPEN_STATES)] == [
            "new-post",
            "old-post",
        ]

    def test_rfc822_source_dates_sort_correctly(self, tmp_path):
        cfg = self._seed(
            tmp_path,
            [
                Draft(id="aug", state=EXTRACTED, published="Sun, 16 Aug 2026 00:00:00 GMT"),
                Draft(id="sep", state=EXTRACTED, published="Tue, 08 Sep 2026 00:00:00 GMT"),
            ],
        )
        assert [d.id for d in pipeline.list_drafts(cfg, pipeline.OPEN_STATES)] == ["sep", "aug"]

    def test_unparseable_date_falls_back_to_queue_time(self, tmp_path):
        cfg = self._seed(
            tmp_path,
            [
                Draft(
                    id="bad-date",
                    state=EXTRACTED,
                    published="last Tuesday",
                    created_at="2026-09-10T12:00:00+00:00",
                ),
                Draft(id="dated", state=EXTRACTED, published="2026-09-01T00:00:00Z"),
            ],
        )
        # The undated item falls back to its (newer) queue time and sorts first.
        assert [d.id for d in pipeline.list_drafts(cfg, pipeline.OPEN_STATES)] == [
            "bad-date",
            "dated",
        ]

    def test_updated_at_is_the_fallback_sort_key(self, tmp_path):
        cfg = self._seed(
            tmp_path,
            [
                Draft(id="a", state=EXTRACTED, updated_at="2026-09-02T00:00:00+00:00"),
                Draft(id="b", state=EXTRACTED, updated_at="2026-09-03T00:00:00+00:00"),
            ],
        )
        assert [d.id for d in pipeline.list_drafts(cfg, pipeline.OPEN_STATES)] == ["b", "a"]

    def test_state_filter_still_applies(self, tmp_path):
        cfg = self._seed(
            tmp_path,
            [
                Draft(id="e", state=EXTRACTED, created_at="2026-09-02T00:00:00+00:00"),
                Draft(id="p", state=POSTED, created_at="2026-09-03T00:00:00+00:00"),
            ],
        )
        assert [d.id for d in pipeline.list_drafts(cfg, pipeline.OPEN_STATES)] == ["e"]

    def test_filter_drafts_by_source_and_state(self):
        drafts = [
            Draft(id="1", source="a", state=EXTRACTED),
            Draft(id="2", source="a", state=AI_DRAFT),
            Draft(id="3", source="b", state=EXTRACTED),
        ]
        assert [d.id for d in pipeline.filter_drafts(drafts, source="a")] == ["1", "2"]
        assert [d.id for d in pipeline.filter_drafts(drafts, state=EXTRACTED)] == ["1", "3"]
        assert [d.id for d in pipeline.filter_drafts(drafts, source="a", state=AI_DRAFT)] == ["2"]
        assert [d.id for d in pipeline.filter_drafts(drafts)] == ["1", "2", "3"]
        assert pipeline.filter_drafts(drafts, source="nope") == []


class TestPaginate:
    def test_no_per_page_returns_everything(self):
        page, info = pipeline.paginate([1, 2, 3], page=1, per_page=0)
        assert page == [1, 2, 3]
        assert info == {
            "page": 1,
            "per_page": 3,
            "total": 3,
            "pages": 1,
            "has_prev": False,
            "has_next": False,
        }

    def test_slices_into_pages(self):
        page, info = pipeline.paginate(list(range(5)), page=2, per_page=2)
        assert page == [2, 3]
        assert (info["total"], info["pages"]) == (5, 3)
        assert info["has_prev"] and info["has_next"]

    def test_last_page_has_no_next(self):
        page, info = pipeline.paginate(list(range(5)), page=3, per_page=2)
        assert page == [4]
        assert info["has_prev"] is True and info["has_next"] is False

    def test_page_clamped_to_bounds(self):
        page, info = pipeline.paginate(list(range(3)), page=99, per_page=2)
        assert page == [2]
        assert info["page"] == 2
        assert pipeline.paginate(list(range(3)), page=0, per_page=2)[1]["page"] == 1

    def test_empty_list_is_a_single_page(self):
        page, info = pipeline.paginate([], page=1, per_page=10)
        assert page == []
        assert (info["total"], info["pages"]) == (0, 1)


class TestFileCaches:
    def test_published_log_cache_invalidates_on_append(self, tmp_path):
        cfg = _cfg(tmp_path)
        assert pipeline.list_published(cfg) == []
        pipeline.append_audit(pipeline.published_path(cfg), {"id": "a"})
        assert [r["id"] for r in pipeline.list_published(cfg)] == ["a"]
        pipeline.append_audit(pipeline.published_path(cfg), {"id": "b"})
        assert [r["id"] for r in pipeline.list_published(cfg)] == ["a", "b"]

    def test_seen_cache_is_not_shared_with_callers(self, tmp_path):
        cfg = _cfg(tmp_path)
        pipeline.save_seen(cfg, {"a", "b"})
        seen = pipeline.load_seen(cfg)
        seen.add("c")
        assert pipeline.load_seen(cfg) == {"a", "b"}

    def test_dna_file_is_re_read_when_it_changes(self, tmp_path):
        cfg = _cfg(tmp_path)
        dna = tmp_path / "dna.md"
        dna.write_text("voice one", encoding="utf-8")
        cfg["publish"]["dna_file"] = str(dna)
        assert pipeline.dna_text(cfg) == "voice one"
        dna.write_text("voice two", encoding="utf-8")
        assert pipeline.dna_text(cfg) == "voice two"


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

    def _audit_public(self, cfg, days_ago=0):
        day = (dt.datetime.now().astimezone().date() - dt.timedelta(days=days_ago)).isoformat()
        pipeline.append_audit(
            pipeline.published_path(cfg),
            {"id": "older", "posted_at": f"{day}T10:00:00+00:00"},
        )

    def test_interval_days_blocks_a_post_too_soon(self, tmp_path, monkeypatch):
        cfg = _seed_draft(tmp_path, caption="Hello")
        cfg["publish"]["interval_days"] = 2
        self._audit_public(cfg, days_ago=0)
        fake = FakePublisher()
        monkeypatch.setattr(pipeline, "publisher_for", lambda name, cfg, token=None: fake)
        with pytest.raises(ValueError, match="interval"):
            pipeline.publish_draft(cfg, "post-one")
        assert fake.published == []

    def test_interval_days_allows_a_post_after_the_gap(self, tmp_path, monkeypatch):
        cfg = _seed_draft(tmp_path, caption="Hello")
        cfg["publish"]["interval_days"] = 2
        self._audit_public(cfg, days_ago=2)
        fake = FakePublisher()
        monkeypatch.setattr(pipeline, "publisher_for", lambda name, cfg, token=None: fake)
        pipeline.publish_draft(cfg, "post-one")
        assert fake.published == ["post-one"]

    def test_interval_days_ignores_private_sends(self, tmp_path, monkeypatch):
        cfg = _seed_draft(tmp_path, caption="Hello")
        cfg["publish"]["interval_days"] = 2
        day = dt.datetime.now().astimezone().date().isoformat()
        pipeline.append_audit(
            pipeline.published_path(cfg),
            {"id": "older", "posted_at": f"{day}T10:00:00+00:00", "private": True},
        )
        fake = FakePublisher()
        monkeypatch.setattr(pipeline, "publisher_for", lambda name, cfg, token=None: fake)
        pipeline.publish_draft(cfg, "post-one")
        assert fake.published == ["post-one"]


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


class TestPublishScheduled:
    """The scheduler posts only human-approved drafts, oldest first."""

    def _seed(self, tmp_path, drafts):
        cfg = _cfg(tmp_path)
        pipeline.save_drafts(pipeline.queue_path(cfg), drafts)
        return cfg

    def _stub(self, monkeypatch, publisher=None):
        fake = publisher or FakePublisher()
        monkeypatch.setattr(
            pipeline, "publisher_for", lambda name, cfg, token=None: fake
        )
        return fake

    def test_posts_only_approved_oldest_first(self, tmp_path, monkeypatch):
        cfg = self._seed(
            tmp_path,
            [
                Draft(id="new", state=APPROVED, caption="c", destinations=["facebook"],
                      created_at="2026-09-10T00:00:00+00:00"),
                Draft(id="old", state=APPROVED, caption="c", destinations=["facebook"],
                      created_at="2026-09-01T00:00:00+00:00"),
                Draft(id="ai", state=AI_DRAFT, caption="c", destinations=["facebook"]),
                Draft(id="ext", state=EXTRACTED, destinations=["facebook"]),
            ],
        )
        fake = self._stub(monkeypatch)
        result = pipeline.publish_scheduled(cfg)
        assert [entry["id"] for entry in result["posted"]] == ["old"]
        assert fake.published == ["old"]
        assert pipeline.get_draft(cfg, "old").state == POSTED
        assert pipeline.get_draft(cfg, "ai").state == AI_DRAFT  # never auto-approved

    def test_next_scheduled_matches_what_the_poster_sends(self, tmp_path, monkeypatch):
        """The 'next up' the UI shows must be the draft that actually posts."""
        cfg = self._seed(
            tmp_path,
            [
                Draft(id="new", state=APPROVED, caption="c", destinations=["facebook"],
                      created_at="2026-09-10T00:00:00+00:00"),
                Draft(id="old", state=APPROVED, caption="c", destinations=["facebook"],
                      created_at="2026-09-01T00:00:00+00:00"),
                Draft(id="ai", state=AI_DRAFT, caption="c", destinations=["facebook"]),
            ],
        )
        upcoming = pipeline.next_scheduled(pipeline.load_drafts(pipeline.queue_path(cfg)))
        assert upcoming is not None and upcoming.id == "old"
        self._stub(monkeypatch)
        result = pipeline.publish_scheduled(cfg)
        assert result["posted"][0]["id"] == upcoming.id

    def test_scheduled_queue_is_oldest_first(self, tmp_path):
        cfg = self._seed(
            tmp_path,
            [
                Draft(id="b", state=APPROVED, caption="c", destinations=["facebook"],
                      created_at="2026-09-05T00:00:00+00:00"),
                Draft(id="a", state=APPROVED, caption="c", destinations=["facebook"],
                      created_at="2026-09-01T00:00:00+00:00"),
                Draft(id="ai", state=AI_DRAFT, caption="c", destinations=["facebook"]),
            ],
        )
        assert [d.id for d in pipeline.scheduled_queue(cfg)] == ["a", "b"]

    def test_post_per_slot_caps_the_batch(self, tmp_path, monkeypatch):
        cfg = self._seed(
            tmp_path,
            [
                Draft(id=f"d{i}", state=APPROVED, caption="c", destinations=["facebook"],
                      created_at=f"2026-09-0{i + 1}T00:00:00+00:00")
                for i in range(3)
            ],
        )
        cfg["publish"]["post_per_slot"] = 2
        fake = self._stub(monkeypatch)
        result = pipeline.publish_scheduled(cfg)
        assert len(result["posted"]) == 2
        assert fake.published == ["d0", "d1"]

    def test_limit_overrides_post_per_slot(self, tmp_path, monkeypatch):
        cfg = self._seed(
            tmp_path,
            [
                Draft(id=f"d{i}", state=APPROVED, caption="c", destinations=["facebook"],
                      created_at=f"2026-09-0{i + 1}T00:00:00+00:00")
                for i in range(3)
            ],
        )
        cfg["publish"]["post_per_slot"] = 1
        fake = self._stub(monkeypatch)
        result = pipeline.publish_scheduled(cfg, limit=2)
        assert len(result["posted"]) == 2
        assert fake.published == ["d0", "d1"]

    def test_stops_at_the_daily_cap(self, tmp_path, monkeypatch):
        cfg = self._seed(
            tmp_path, [Draft(id="a", state=APPROVED, caption="c", destinations=["facebook"])]
        )
        cfg["publish"]["max_per_day"] = 1
        cfg["publish"]["post_per_slot"] = 5
        self._stub(monkeypatch)
        pipeline.publish_scheduled(cfg)  # consumes the only slot
        pipeline.save_drafts(
            pipeline.queue_path(cfg),
            [Draft(id="b", state=APPROVED, caption="c", destinations=["facebook"])],
        )
        result = pipeline.publish_scheduled(cfg)
        assert result["posted"] == []
        assert result["skipped"][0]["id"] == "b"
        assert "cap" in result["skipped"][0]["reason"]

    def test_dry_run_sends_nothing(self, tmp_path, monkeypatch):
        cfg = self._seed(
            tmp_path, [Draft(id="a", state=APPROVED, caption="c", destinations=["facebook"])]
        )
        fake = self._stub(monkeypatch)
        pipeline.publish_scheduled(cfg, dry_run=True)
        assert fake.published == []
        assert pipeline.get_draft(cfg, "a").state == APPROVED

    def test_private_send_is_not_repeated_today(self, tmp_path, monkeypatch):
        """Private sends leave the draft approved: the poster must not loop on it."""
        cfg = self._seed(
            tmp_path, [Draft(id="a", state=APPROVED, caption="c", destinations=["facebook"])]
        )
        fake = self._stub(monkeypatch, PrivatePublisher())
        first = pipeline.publish_scheduled(cfg, limit=5)
        assert len(first["posted"]) == 1
        second = pipeline.publish_scheduled(cfg, limit=5)
        assert second["posted"] == []
        assert second["skipped"][0]["id"] == "a"
        assert len(fake.published) == 1
        assert pipeline.get_draft(cfg, "a").state == APPROVED

    def test_publisher_error_is_recorded_not_raised(self, tmp_path, monkeypatch):
        cfg = self._seed(
            tmp_path,
            [
                Draft(id="a", state=APPROVED, caption="c", destinations=["facebook"],
                      created_at="2026-09-01T00:00:00+00:00"),
                Draft(id="b", state=APPROVED, caption="c", destinations=["facebook"],
                      created_at="2026-09-02T00:00:00+00:00"),
            ],
        )
        cfg["publish"]["post_per_slot"] = 5

        class Boom(FakePublisher):
            def publish(self, draft):
                raise PublisherError("nope")

        self._stub(monkeypatch, Boom())
        result = pipeline.publish_scheduled(cfg)
        assert result["posted"] == []
        assert [entry["id"] for entry in result["errors"]] == ["a", "b"]

    def test_disabled_publishing_raises(self, tmp_path):
        cfg = self._seed(
            tmp_path, [Draft(id="a", state=APPROVED, caption="c", destinations=["facebook"])]
        )
        cfg["publish"]["enabled"] = False
        with pytest.raises(ValueError):
            pipeline.publish_scheduled(cfg)


class TestApprove:
    def test_approve_draft_queues_without_posting(self, tmp_path):
        cfg = _seed_draft(tmp_path, caption="Hello")
        assert pipeline.approve_draft(cfg, "post-one").state == APPROVED
        assert pipeline.published_path(cfg).exists() is False

    def test_approve_unknown_draft_raises(self, tmp_path):
        with pytest.raises(ValueError):
            pipeline.approve_draft(_cfg(tmp_path), "nope")


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


class TestGenerateImages:
    def _cfg_with_gen(self, tmp_path, **overrides):
        cfg = _seed_draft(tmp_path)
        cfg["image_gen"] = {**DEFAULTS["image_gen"], "enabled": True, **overrides}
        return cfg

    def test_disabled_raises(self, tmp_path):
        cfg = _seed_draft(tmp_path)
        with pytest.raises(ValueError):
            pipeline.generate_images(cfg)

    def test_generates_and_stores_image(self, tmp_path, monkeypatch):
        cfg = self._cfg_with_gen(tmp_path)
        monkeypatch.setattr(
            pipeline, "generate_for_draft", lambda *a, **kw: "https://gen/one.jpg"
        )
        result = pipeline.generate_images(cfg)
        assert result["generated"] == 1
        assert result["ids"] == ["post-one"]
        assert pipeline.get_draft(cfg, "post-one").image == "https://gen/one.jpg"

    def test_overwrite_replaces_existing_image(self, tmp_path, monkeypatch):
        cfg = self._cfg_with_gen(tmp_path)
        draft = pipeline.get_draft(cfg, "post-one")
        draft.image = "https://blog/cover.jpg"
        pipeline.save_drafts(pipeline.queue_path(cfg), [draft])
        monkeypatch.setattr(
            pipeline, "generate_for_draft", lambda *a, **kw: "https://gen/new.jpg"
        )
        pipeline.generate_images(cfg, overwrite=True)
        assert pipeline.get_draft(cfg, "post-one").image == "https://gen/new.jpg"

    def test_missing_only_skips_existing(self, tmp_path, monkeypatch):
        cfg = self._cfg_with_gen(tmp_path)
        draft = pipeline.get_draft(cfg, "post-one")
        draft.image = "https://blog/cover.jpg"
        pipeline.save_drafts(pipeline.queue_path(cfg), [draft])
        monkeypatch.setattr(
            pipeline, "generate_for_draft", lambda *a, **kw: "https://gen/new.jpg"
        )
        result = pipeline.generate_images(cfg, overwrite=False)
        assert result["generated"] == 0
        assert pipeline.get_draft(cfg, "post-one").image == "https://blog/cover.jpg"

    def test_default_keeps_existing_image(self, tmp_path, monkeypatch):
        """No explicit flag: an existing image is kept (config overwrite is off)."""
        cfg = self._cfg_with_gen(tmp_path)
        draft = pipeline.get_draft(cfg, "post-one")
        draft.image = "https://blog/cover.jpg"
        pipeline.save_drafts(pipeline.queue_path(cfg), [draft])
        calls = []
        monkeypatch.setattr(
            pipeline, "generate_for_draft", lambda *a, **kw: calls.append(1) or "x"
        )
        result = pipeline.generate_images(cfg)
        assert result["generated"] == 0
        assert calls == []
        assert pipeline.get_draft(cfg, "post-one").image == "https://blog/cover.jpg"

    def test_does_not_clobber_a_write_that_lands_during_generation(
        self, tmp_path, monkeypatch
    ):
        """Generation is slow: a rewrite arriving mid-call must survive the save.

        serve fills a draft's image in the background while rewriter batches are
        still posting, so writing back the queue loaded before the provider call
        used to roll back every rewrite that landed in between.
        """
        cfg = self._cfg_with_gen(tmp_path)

        def concurrent(*a, **kw):
            other = pipeline.get_draft(cfg, "post-one")
            other.caption = "landed while generating"
            other.touch()
            pipeline.save_drafts(pipeline.queue_path(cfg), [other])
            return "https://gen/one.jpg"

        monkeypatch.setattr(pipeline, "generate_for_draft", concurrent)
        pipeline.generate_images(cfg)
        fresh = pipeline.get_draft(cfg, "post-one")
        assert fresh.caption == "landed while generating"
        assert fresh.image == "https://gen/one.jpg"

    def test_failure_is_recorded_not_raised(self, tmp_path, monkeypatch):
        from social_bot.image_gen import ImageGenError

        def boom(*a, **kw):
            raise ImageGenError("nope")

        cfg = self._cfg_with_gen(tmp_path)
        monkeypatch.setattr(pipeline, "generate_for_draft", boom)
        result = pipeline.generate_images(cfg)
        assert result["generated"] == 0
        assert result["errors"][0]["error"].startswith("image post-one")

    def test_unknown_draft_id_raises(self, tmp_path):
        cfg = self._cfg_with_gen(tmp_path)
        with pytest.raises(ValueError):
            pipeline.generate_images(cfg, draft_ids=["nope"])

    def test_key_and_config_are_passed_through(self, tmp_path, monkeypatch):
        cfg = self._cfg_with_gen(
            tmp_path, model="turbo", api_key="sk_x", base_url="https://gen.example/image"
        )
        captured = {}

        def fake(*args, **kwargs):
            captured.update(kwargs)
            return "https://gen/one.jpg"

        monkeypatch.setattr(pipeline, "generate_for_draft", fake)
        pipeline.generate_images(cfg)
        assert captured["model"] == "turbo"
        assert captured["api_key"] == "sk_x"
        assert captured["base_url"] == "https://gen.example/image"

    def test_blank_base_url_falls_back_to_default(self, tmp_path, monkeypatch):
        cfg = self._cfg_with_gen(tmp_path, base_url="")
        captured = {}

        def fake(*args, **kwargs):
            captured.update(kwargs)
            return "https://gen/one.jpg"

        monkeypatch.setattr(pipeline, "generate_for_draft", fake)
        pipeline.generate_images(cfg)
        assert captured["base_url"] == DEFAULT_BASE_URL


class TestImageStyle:
    def test_reads_style_file(self, tmp_path):
        style = tmp_path / "style.md"
        style.write_text("Deep navy palette.", encoding="utf-8")
        cfg = _cfg(tmp_path)
        cfg["image_gen"]["style_file"] = str(style)
        assert pipeline.image_style_text(cfg) == "Deep navy palette."

    def test_absent_is_empty(self, tmp_path):
        cfg = _cfg(tmp_path)
        cfg["image_gen"]["style_file"] = str(tmp_path / "nope.md")
        assert pipeline.image_style_text(cfg) == ""

    def test_unset_is_empty(self, tmp_path):
        assert pipeline.image_style_text(_cfg(tmp_path)) == ""

    def test_style_is_passed_to_generation(self, tmp_path, monkeypatch):
        style = tmp_path / "style.md"
        style.write_text("Navy, amber accent.", encoding="utf-8")
        cfg = _seed_draft(tmp_path)
        cfg["image_gen"] = {
            **DEFAULTS["image_gen"],
            "enabled": True,
            "style_file": str(style),
        }
        captured = {}

        def fake(*args, **kwargs):
            captured.update(kwargs)
            return "https://gen/one.jpg"

        monkeypatch.setattr(pipeline, "generate_for_draft", fake)
        pipeline.generate_images(cfg)
        assert captured["style"] == "Navy, amber accent."


class TestScanImageGen:
    def test_scan_does_not_generate_images(self, tmp_path, monkeypatch):
        """Images are generated after the rewrite supplies an image_prompt."""
        calls = []
        monkeypatch.setattr(
            pipeline, "generate_for_draft", lambda *a, **kw: calls.append(1) or "x"
        )
        cfg = _cfg(tmp_path)
        cfg["image_gen"] = {**DEFAULTS["image_gen"], "enabled": True}
        pipeline.scan_sources(cfg, client=FakeClient())
        assert calls == []
        # The source image from enrichment is kept untouched.
        assert pipeline.get_draft(cfg, "post-one").image == "https://img/cover.jpg"


class TestImagePrompt:
    def _cfg_with_gen(self, tmp_path, **overrides):
        cfg = _seed_draft(tmp_path)
        cfg["image_gen"] = {**DEFAULTS["image_gen"], "enabled": True, **overrides}
        return cfg

    def test_receive_rewrite_stores_image_prompt(self, tmp_path):
        cfg = _seed_draft(tmp_path)
        draft = pipeline.receive_rewrite(
            cfg, "post-one", {"caption": "c", "image_prompt": "a long ledger"}
        )
        assert draft.image_prompt == "a long ledger"

    def test_image_prompt_is_passed_to_generation(self, tmp_path, monkeypatch):
        cfg = self._cfg_with_gen(tmp_path)
        draft = pipeline.get_draft(cfg, "post-one")
        draft.image_prompt = "a long ledger unspooling"
        pipeline.save_drafts(pipeline.queue_path(cfg), [draft])
        captured = {}

        def fake(*args, **kwargs):
            captured.update(kwargs)
            return "https://gen/one.jpg"

        monkeypatch.setattr(pipeline, "generate_for_draft", fake)
        pipeline.generate_images(cfg)
        assert captured["image_prompt"] == "a long ledger unspooling"

    def test_empty_image_prompt_falls_back_to_title(self, tmp_path, monkeypatch):
        cfg = self._cfg_with_gen(tmp_path)
        captured = {}

        def fake(title, excerpt, **kwargs):
            captured["title"] = title
            captured.update(kwargs)
            return "https://gen/one.jpg"

        monkeypatch.setattr(pipeline, "generate_for_draft", fake)
        pipeline.generate_images(cfg)
        # No image_prompt set, so image_gen must fall back to the title.
        assert captured["image_prompt"] == ""
        assert captured["title"] == "Title"


class TestGenerateMissingImage:
    """The serve hook: fill a just-rewritten draft's image, only if missing."""

    def _cfg_with_gen(self, tmp_path, **overrides):
        cfg = _seed_draft(tmp_path)
        cfg["image_gen"] = {**DEFAULTS["image_gen"], "enabled": True, **overrides}
        return cfg

    def test_disabled_returns_none_without_generating(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(
            pipeline, "generate_for_draft", lambda *a, **kw: calls.append(1) or "x"
        )
        cfg = _seed_draft(tmp_path)  # image_gen disabled by default
        assert pipeline.generate_missing_image(cfg, "post-one") is None
        assert calls == []

    def test_unknown_draft_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pipeline, "generate_for_draft", lambda *a, **kw: "x")
        assert pipeline.generate_missing_image(self._cfg_with_gen(tmp_path), "nope") is None

    def test_generates_when_image_is_missing(self, tmp_path, monkeypatch):
        cfg = self._cfg_with_gen(tmp_path)
        monkeypatch.setattr(
            pipeline, "generate_for_draft", lambda *a, **kw: "https://gen/one.jpg"
        )
        result = pipeline.generate_missing_image(cfg, "post-one")
        assert result["generated"] == 1
        assert pipeline.get_draft(cfg, "post-one").image == "https://gen/one.jpg"

    def test_keeps_existing_image(self, tmp_path, monkeypatch):
        cfg = self._cfg_with_gen(tmp_path)
        draft = pipeline.get_draft(cfg, "post-one")
        draft.image = "https://blog/cover.jpg"
        pipeline.save_drafts(pipeline.queue_path(cfg), [draft])
        calls = []
        monkeypatch.setattr(
            pipeline, "generate_for_draft", lambda *a, **kw: calls.append(1) or "x"
        )
        result = pipeline.generate_missing_image(cfg, "post-one")
        assert result["generated"] == 0
        assert calls == []  # a re-submitted rewrite must not regenerate
        assert pipeline.get_draft(cfg, "post-one").image == "https://blog/cover.jpg"

    def test_failure_is_recorded_not_raised(self, tmp_path, monkeypatch):
        from social_bot.image_gen import ImageGenError

        def boom(*a, **kw):
            raise ImageGenError("nope")

        cfg = self._cfg_with_gen(tmp_path)
        monkeypatch.setattr(pipeline, "generate_for_draft", boom)
        result = pipeline.generate_missing_image(cfg, "post-one")
        assert result["generated"] == 0
        assert result["errors"][0]["error"].startswith("image post-one")


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

    def test_next_draft_is_the_oldest_approved(self, tmp_path):
        cfg = _cfg(tmp_path)
        pipeline.save_drafts(
            pipeline.queue_path(cfg),
            [
                Draft(id="new", state=APPROVED, title="Newest", caption="c",
                      destinations=["facebook"], published="2026-09-10T00:00:00+00:00"),
                Draft(id="old", state=APPROVED, title="Oldest", caption="c",
                      destinations=["facebook"], published="2026-09-01T00:00:00+00:00"),
                Draft(id="drafting", state=AI_DRAFT, title="Not approved",
                      destinations=["facebook"]),
            ],
        )
        publish = pipeline.status(cfg)["publish"]
        assert publish["approved"] == 2
        assert publish["next_draft"]["id"] == "old"
        assert publish["next_draft"]["title"] == "Oldest"
        assert publish["next_draft"]["has_image"] is False

    def test_next_draft_is_none_without_approvals(self, tmp_path):
        cfg = _cfg(tmp_path)
        pipeline.save_drafts(
            pipeline.queue_path(cfg),
            [Draft(id="drafting", state=AI_DRAFT, caption="c", destinations=["facebook"])],
        )
        publish = pipeline.status(cfg)["publish"]
        assert publish["approved"] == 0
        assert publish["next_draft"] is None

    def test_next_draft_reports_an_existing_image(self, tmp_path):
        cfg = _cfg(tmp_path)
        pipeline.save_drafts(
            pipeline.queue_path(cfg),
            [
                Draft(id="a", state=APPROVED, caption="c", destinations=["facebook"],
                      image="https://img/cover.jpg"),
            ],
        )
        publish = pipeline.status(cfg)["publish"]
        assert publish["next_draft"]["has_image"] is True

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
