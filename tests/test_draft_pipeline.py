"""Pipeline orchestration: scan, rewrite intake, publish (no network)."""

from __future__ import annotations

import copy
import json

import pytest

from social_bot import draft_pipeline as pipeline
from social_bot.config import DEFAULTS
from social_bot.drafts import AI_DRAFT, EXTRACTED, POSTED, REJECTED, Draft
from social_bot.image_gen import DEFAULT_BASE_URL
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
