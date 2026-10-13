"""Code-drawn diagrams: well-formed SVG/HTML, in-bounds geometry, safe escaping."""

from __future__ import annotations

import pathlib
import re
import xml.etree.ElementTree as ET

import pytest

from social_bot import browser_shot, diagram, diagram_html
from social_bot import draft_pipeline as pipeline
from social_bot.drafts import AI_DRAFT, Draft


def _std_draft(**overrides):
    base = {
        "id": "d1",
        "source": "atento-original",
        "topic": "ClickHouse architecture",
        "image_style": "diagram",
    }
    base.update(overrides)
    return Draft(**base)


class TestSparseIndex:
    def test_is_well_formed_svg(self):
        root = ET.fromstring(diagram.render_sparse_index())
        assert root.tag == "{http://www.w3.org/2000/svg}svg"
        assert root.attrib["viewBox"] == f"0 0 {diagram.WIDTH} {diagram.HEIGHT}"

    def test_carries_the_essential_copy(self):
        svg = diagram.render_sparse_index()
        for needle in ("SPARSE INDEX", "DENSE INDEX", "CLICKHOUSE", "8192"):
            assert needle in svg

    def test_keys_are_drawn_not_written(self):
        """No per-row "key" words — the key is an icon, the image explains."""
        svg = diagram.render_sparse_index()
        assert ">key<" not in svg

    def test_stays_minimal(self):
        """The image shows the mechanism; the caption tells the story."""
        svg = diagram.render_sparse_index()
        for needle in (
            "mục lục",
            "mỗi dòng",
            "dòng dữ liệu",
            "VÌ SAO",
            "rẻ cả cụm",
            "HỌC CÙNG ATENTO",
        ):
            assert needle not in svg

    def test_geometry_stays_inside_the_canvas(self):
        svg = diagram.render_sparse_index()
        for value in re.findall(r"x='([\d.]+)'", svg):
            assert 0 <= float(value) <= diagram.WIDTH, value
        for value in re.findall(r"y='([\d.]+)'", svg):
            assert 0 <= float(value) <= diagram.HEIGHT, value

    def test_user_text_is_escaped(self):
        svg = diagram.render_sparse_index(title="<key> & key")
        assert "<key>" not in svg
        assert "&lt;key&gt; &amp; key" in svg


class TestWriteConcern:
    def test_is_well_formed_svg(self):
        root = ET.fromstring(diagram.render_write_concern())
        assert root.tag == "{http://www.w3.org/2000/svg}svg"
        assert root.attrib["viewBox"] == f"0 0 {diagram.WIDTH} {diagram.HEIGHT}"

    def test_carries_the_essential_copy(self):
        svg = diagram.render_write_concern()
        for needle in (
            "WRITE CONCERN",
            "MONGODB REPLICA SET",
            "w:1",
            "w:majority",
            "ACK NGAY",
            "CHỜ ĐA SỐ",
            "mất nếu sập",
            "còn khi sập",
        ):
            assert needle in svg

    def test_words_stay_out_of_the_drawing(self):
        """The scene is objects — cabinets and cards; the only words are the
        title, the kicker, the two row labels and the two verdicts."""
        svg = diagram.render_write_concern()
        for word in ("PRIMARY", "SECONDARY", "NODE GIỮ"):
            assert word not in svg

    def test_geometry_stays_inside_the_canvas(self):
        svg = diagram.render_write_concern()
        for value in re.findall(r"x='([\d.]+)'", svg):
            assert 0 <= float(value) <= diagram.WIDTH, value
        for value in re.findall(r"y='([\d.]+)'", svg):
            assert 0 <= float(value) <= diagram.HEIGHT, value

    def test_user_text_is_escaped(self):
        svg = diagram.render_write_concern(title="<key> & key")
        assert "<key>" not in svg
        assert "&lt;key&gt; &amp; key" in svg


class TestRenderForDraft:
    def test_diagram_style_renders(self):
        assert diagram.render_for_draft(_std_draft()).startswith("<svg")

    def test_a_mongo_draft_gets_the_write_concern_plate(self):
        svg = diagram.render_for_draft(_std_draft(topic="MongoDB architecture"))
        assert "WRITE CONCERN" in svg
        assert "SPARSE INDEX" not in svg

    def test_an_unrecognised_system_renders_nothing(self):
        # A wrong plate is worse than no plate: an unknown system must not
        # borrow another one's figure.
        assert diagram.render_for_draft(_std_draft(topic="Postgres architecture")) == ""

    def test_other_styles_render_nothing(self):
        assert diagram.render_for_draft(_std_draft(image_style="editorial")) == ""
        assert diagram.render_for_draft(_std_draft(image_style="")) == ""
        assert diagram.render_for_draft(None) == ""


class TestRenderDiagrams:
    @pytest.fixture(autouse=True)
    def _no_browser(self, monkeypatch):
        """Pin the SVG fallback: the suite runs where no Chromium exists."""

        def _missing(page, dest, **kwargs):
            raise browser_shot.ShotError("no Chromium")

        monkeypatch.setattr(pipeline, "html_to_png", _missing)

    def _cfg(self, tmp_path):
        import copy

        from social_bot.config import DEFAULTS

        cfg = copy.deepcopy(DEFAULTS)
        cfg["review"]["dir"] = str(tmp_path / "review")
        return cfg

    def _seed(self, cfg, **kw):
        draft = Draft(
            id=kw.get("id", "d1"),
            source="atento-original",
            title="Title",
            topic=kw.get("topic", "ClickHouse architecture"),
            destinations=["facebook"],
            state=AI_DRAFT,
            image_style=kw.get("image_style", "diagram"),
            image=kw.get("image", ""),
        )
        pipeline.save_drafts(pipeline.queue_path(cfg), [draft])
        return cfg

    def test_writes_file_and_points_draft_at_it(self, tmp_path):
        cfg = self._seed(self._cfg(tmp_path))
        result = pipeline.render_diagrams(cfg)
        assert result == {"rendered": 1, "candidates": 1, "ids": ["d1"]}
        path = pipeline.diagram_dir(cfg) / "d1.svg"
        assert path.read_text(encoding="utf-8").startswith("<svg")
        [draft] = pipeline.load_drafts(pipeline.queue_path(cfg))
        assert draft.image == "/images/d1.svg"

    def test_skips_non_diagram_styles(self, tmp_path):
        cfg = self._seed(self._cfg(tmp_path), image_style="editorial")
        assert pipeline.render_diagrams(cfg)["rendered"] == 0

    def test_never_replaces_without_overwrite(self, tmp_path):
        cfg = self._seed(self._cfg(tmp_path), image="https://example.com/old.png")
        assert pipeline.render_diagrams(cfg)["rendered"] == 0
        assert pipeline.render_diagrams(cfg, overwrite=True)["rendered"] == 1

    def test_unknown_draft_raises(self, tmp_path):
        cfg = self._cfg(tmp_path)
        with pytest.raises(ValueError, match="no draft"):
            pipeline.render_diagrams(cfg, draft_ids=["ghost"])


class TestSparseIndexHtml:
    def test_carries_the_essential_copy(self):
        page = diagram_html.render_sparse_index_html()
        for needle in ("SPARSE INDEX", "DENSE INDEX", "CLICKHOUSE", "8192", "RAM"):
            assert needle in page

    def test_stays_minimal(self):
        """The image shows the mechanism; the caption tells the story."""
        page = diagram_html.render_sparse_index_html()
        for needle in (
            "mục lục",
            "mỗi dòng",
            "dòng dữ liệu",
            "VÌ SAO",
            "rẻ cả cụm",
            "HỌC CÙNG ATENTO",
        ):
            assert needle not in page

    def test_no_quote_collision_in_style_attributes(self):
        """Single-quoted style attributes must not contain single quotes.

        A collision truncates the attribute and drops font-family back to a
        serif default — exactly the regression this pins.
        """
        page = diagram_html.render_sparse_index_html()
        assert "'Be Vietnam" not in page
        assert "'Segoe UI'" not in page

    def test_user_text_is_escaped(self):
        page = diagram_html.render_sparse_index_html(title="<key> & key")
        assert "<key>" not in page
        assert "&lt;key&gt; &amp; key" in page


class TestWriteConcernHtml:
    def test_carries_the_essential_copy(self):
        page = diagram_html.render_write_concern_html()
        for needle in ("WRITE CONCERN", "w:1", "w:majority", "còn khi sập"):
            assert needle in page

    def test_no_quote_collision_in_style_attributes(self):
        page = diagram_html.render_write_concern_html()
        assert "'Be Vietnam" not in page
        assert "'Segoe UI'" not in page

    def test_user_text_is_escaped(self):
        page = diagram_html.render_write_concern_html(title="<key> & key")
        assert "<key>" not in page
        assert "&lt;key&gt; &amp; key" in page


class TestRenderForDraftHtml:
    def _std_draft(self, **overrides):
        base = {
            "id": "d1",
            "source": "atento-original",
            "topic": "ClickHouse architecture",
            "image_style": "diagram",
        }
        base.update(overrides)
        return Draft(**base)

    def test_diagram_style_renders(self):
        assert diagram_html.render_for_draft_html(self._std_draft()).startswith("<!doctype html>")

    def test_a_mongo_draft_gets_the_write_concern_plate(self):
        page = diagram_html.render_for_draft_html(self._std_draft(topic="MongoDB architecture"))
        assert "WRITE CONCERN" in page
        assert "SPARSE INDEX" not in page

    def test_an_unrecognised_system_renders_nothing(self):
        assert diagram_html.render_for_draft_html(self._std_draft(topic="Postgres")) == ""

    def test_other_styles_render_nothing(self):
        assert diagram_html.render_for_draft_html(self._std_draft(image_style="x")) == ""
        assert diagram_html.render_for_draft_html(None) == ""


class TestBrowserShot:
    def test_env_override_wins(self, tmp_path, monkeypatch):
        binary = tmp_path / "chrome"
        binary.write_bytes(b"x")
        monkeypatch.setenv("SOCIAL_BOT_CHROMIUM", str(binary))
        assert browser_shot.find_chromium() == str(binary)

    def test_empty_when_nothing_available(self, monkeypatch):
        monkeypatch.delenv("SOCIAL_BOT_CHROMIUM", raising=False)
        monkeypatch.setattr(browser_shot.glob, "glob", lambda pattern: [])
        monkeypatch.setattr(browser_shot.shutil, "which", lambda name: None)
        assert browser_shot.find_chromium() == ""

    def test_raises_without_a_browser(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SOCIAL_BOT_CHROMIUM", raising=False)
        monkeypatch.setattr(browser_shot.glob, "glob", lambda pattern: [])
        monkeypatch.setattr(browser_shot.shutil, "which", lambda name: None)
        with pytest.raises(browser_shot.ShotError, match="no Chromium"):
            browser_shot.html_to_png("<html></html>", tmp_path / "out.png")

    def test_returns_the_screenshot(self, tmp_path, monkeypatch):
        dest = tmp_path / "out.png"
        monkeypatch.setattr(browser_shot, "find_chromium", lambda: "/bin/chromium")

        def _run(cmd, **kwargs):
            assert "--screenshot=" + str(dest) in cmd
            dest.write_bytes(b"\x89PNG fake")
            return browser_shot.subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(browser_shot.subprocess, "run", _run)
        assert browser_shot.html_to_png("<html></html>", dest) == dest
        assert dest.read_bytes() == b"\x89PNG fake"


class TestRenderDiagramsPng:
    def _cfg(self, tmp_path):
        import copy

        from social_bot.config import DEFAULTS

        cfg = copy.deepcopy(DEFAULTS)
        cfg["review"]["dir"] = str(tmp_path / "review")
        return cfg

    def _seed(self, cfg, **kw):
        draft = Draft(
            id=kw.get("id", "d1"),
            source="atento-original",
            title="Title",
            topic=kw.get("topic", "ClickHouse architecture"),
            destinations=["facebook"],
            state=AI_DRAFT,
            image_style=kw.get("image_style", "diagram"),
            image=kw.get("image", ""),
        )
        pipeline.save_drafts(pipeline.queue_path(cfg), [draft])
        return cfg

    def test_points_draft_at_png_when_browser_works(self, tmp_path, monkeypatch):
        def _shot(page, dest, **kwargs):
            assert "SPARSE INDEX" in page
            pathlib.Path(dest).write_bytes(b"\x89PNG fake")
            return pathlib.Path(dest)

        monkeypatch.setattr(pipeline, "html_to_png", _shot)
        cfg = self._seed(self._cfg(tmp_path))
        result = pipeline.render_diagrams(cfg)
        assert result == {"rendered": 1, "candidates": 1, "ids": ["d1"]}
        out_dir = pipeline.diagram_dir(cfg)
        assert (out_dir / "d1.svg").read_text(encoding="utf-8").startswith("<svg")
        assert (out_dir / "d1.png").read_bytes() == b"\x89PNG fake"
        [draft] = pipeline.load_drafts(pipeline.queue_path(cfg))
        assert draft.image == "/images/d1.png"

    def test_keeps_svg_when_browser_fails(self, tmp_path, monkeypatch):
        def _missing(page, dest, **kwargs):
            raise browser_shot.ShotError("no Chromium")

        monkeypatch.setattr(pipeline, "html_to_png", _missing)
        cfg = self._seed(self._cfg(tmp_path))
        assert pipeline.render_diagrams(cfg)["rendered"] == 1
        [draft] = pipeline.load_drafts(pipeline.queue_path(cfg))
        assert draft.image == "/images/d1.svg"
