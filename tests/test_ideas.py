"""Idea seeds: topics-file parsing and title slugging (pure logic)."""

from __future__ import annotations

from social_bot import ideas


class TestParseTopics:
    def test_name_and_optional_url(self):
        text = "ClickHouse architecture | https://clickhouse.com/docs\nMySQL internals\n"
        assert ideas.parse_topics(text) == [
            {"name": "ClickHouse architecture", "url": "https://clickhouse.com/docs"},
            {"name": "MySQL internals", "url": ""},
        ]

    def test_ignores_blanks_and_comments(self):
        text = "# a comment\n\n   \nLoki architecture\n"
        assert ideas.parse_topics(text) == [{"name": "Loki architecture", "url": ""}]

    def test_strips_bullets(self):
        text = "- Elasticsearch architecture\n*   Grafana architecture\n"
        assert [t["name"] for t in ideas.parse_topics(text)] == [
            "Elasticsearch architecture",
            "Grafana architecture",
        ]

    def test_collapses_whitespace_in_names(self):
        assert ideas.parse_topics("  MySQL   internals  \n")[0]["name"] == "MySQL internals"

    def test_drops_duplicate_names_keeping_the_first(self):
        text = "MySQL internals | https://a\nmysql internals | https://b\n"
        assert ideas.parse_topics(text) == [{"name": "MySQL internals", "url": "https://a"}]

    def test_empty_input(self):
        assert ideas.parse_topics("") == []
        assert ideas.parse_topics(None) == []


class TestSlugify:
    def test_basic(self):
        assert ideas.slugify("Vì sao MySQL chọn B+ tree?") == "vi-sao-mysql-chon-b-tree"

    def test_folds_d_stroke(self):
        assert ideas.slugify("Đánh index trong database") == "danh-index-trong-database"

    def test_collapses_punctuation_and_strips_edges(self):
        assert ideas.slugify("  Kafka: khi nào KHÔNG nên dùng!  ") == "kafka-khi-nao-khong-nen-dung"

    def test_empty_for_text_with_no_letters(self):
        assert ideas.slugify("!!!") == ""
        assert ideas.slugify("") == ""

    def test_capped_length(self):
        assert len(ideas.slugify("a" * 200, max_length=10)) == 10
