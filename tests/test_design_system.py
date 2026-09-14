"""Design-system contracts: tokens, classes, badges, and the styleframe.

These tests are the guardrail that keeps the operator UI a *system* rather than
a pile of one-off pages. They fail when a new page uses a class with no rule, a
token that isn't defined, a badge state the stylesheet doesn't colour, or when
the committed styleframe drifts from the code that generates it.
"""

from __future__ import annotations

import pathlib
import re
from html.parser import HTMLParser

from social_bot import dashboard_html, draft_html, styleframe, ui
from social_bot.destinations.facebook import feed_html
from social_bot.drafts import STATES

_CLASS_RE = re.compile(r'class="([^"]*)"')
_VAR_DEF_RE = re.compile(r"(--[\w-]+)\s*:")
_VAR_USE_RE = re.compile(r"var\(\s*(--[\w-]+)")
_STYLE_RE = re.compile(r"<style>(.*?)</style>", re.S)
_LIGHT_ROOT_RE = re.compile(r":root\s*\{(.*?)\}", re.S)
_DARK_ROOT_RE = re.compile(r"prefers-color-scheme: dark\)\s*\{\s*:root\s*\{(.*?)\}", re.S)
# Styling that must never appear in a page module: a stylesheet, an inline style
# attribute, a raw colour, or a colour function.
_STYLE_LITERAL_RE = re.compile(r"<style|\bstyle=|#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(")

# The modules that render markup (they must defer all styling to ui._CSS).
_PAGE_MODULES = (dashboard_html, draft_html, feed_html)

_VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


class _Balance(HTMLParser):
    """Collect unclosed / mismatched tags in a document."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in _VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"</{tag}> at {self.getpos()}")
        else:
            self.stack.pop()


def _classes(markup: str) -> set[str]:
    found: set[str] = set()
    for group in _CLASS_RE.findall(markup):
        found.update(group.split())
    return found


def _has_rule(css: str, cls: str) -> bool:
    """True when the stylesheet has a `.cls` selector (never `-`/word-chained)."""
    return re.search(r"\." + re.escape(cls) + r"(?![\w-])", css) is not None


def _defined_tokens(css: str) -> set[str]:
    return set(_VAR_DEF_RE.findall(css))


def _used_tokens(css: str) -> set[str]:
    return set(_VAR_USE_RE.findall(css))


class TestTokens:
    def test_every_referenced_custom_property_is_defined(self):
        used = _used_tokens(ui._CSS)
        defined = _defined_tokens(ui._CSS)
        assert not (used - defined), f"undefined custom properties: {sorted(used - defined)}"

    def test_light_and_dark_share_the_same_token_names(self):
        # A token the dark theme sets must also exist in light, or light renders
        # an undefined value.
        light = _defined_tokens(_LIGHT_ROOT_RE.search(ui._CSS).group(1))
        dark = _defined_tokens(_DARK_ROOT_RE.search(ui._CSS).group(1))
        assert dark <= light, f"dark-only tokens: {sorted(dark - light)}"


class TestClasses:
    def test_every_class_on_a_rendered_page_has_a_rule(self):
        missing: set[str] = set()
        for _name, document in styleframe.render_pages():
            for cls in _classes(document):
                if not _has_rule(ui._CSS, cls):
                    missing.add(cls)
        assert not missing, f"classes used with no stylesheet rule: {sorted(missing)}"

    def test_pages_carry_no_inline_style_attributes(self):
        # Styling belongs to ui._CSS, never to a page's markup.
        for name, document in styleframe.render_pages():
            assert 'style="' not in document, f"{name} adds an inline style attribute"

    def test_every_page_composes_the_shared_chrome(self):
        for name, document in styleframe.render_pages():
            assert document.lstrip().startswith("<!doctype html>"), name
            assert document.rstrip().endswith("</html>"), name
            for href in ('href="/"', 'href="/review"', 'href="/publish"', 'href="/status"'):
                assert href in document, f"{name} is missing {href}"

    def test_every_page_uses_the_one_shared_stylesheet(self):
        for name, document in styleframe.render_pages():
            assert document.count("<style>") == 1, f"{name} adds a second <style> block"
            assert ui._CSS in document, f"{name} does not embed ui._CSS"

    def test_page_modules_keep_all_styling_in_ui(self):
        # A page module renders markup only; colour, size, and <style> literals
        # belong in ui.py's stylesheet.
        for module in _PAGE_MODULES:
            source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
            found = _STYLE_LITERAL_RE.findall(source)
            assert not found, f"{module.__name__} contains styling literals: {found}"

    def test_rendered_pages_are_well_formed(self):
        for name, document in styleframe.render_pages():
            balance = _Balance()
            balance.feed(document)
            assert not balance.errors, f"{name} has mismatched tags: {balance.errors[:5]}"
            assert not balance.stack, f"{name} has unclosed tags: {balance.stack[-5:]}"


class TestBadges:
    def test_every_draft_state_has_a_colour_rule(self):
        for state in STATES:
            cls = ui.badge(state).split('class="badge ')[1].split('"')[0]
            assert _has_rule(ui._CSS, cls), f"no rule for {cls}"

    def test_every_labelled_badge_has_a_colour_rule(self):
        for label in styleframe._BADGE_LABELS:
            cls = ui.badge(label).split('class="badge ')[1].split('"')[0]
            assert _has_rule(ui._CSS, cls), f"no rule for {cls}"


class TestStyleframe:
    def test_committed_styleframe_is_current(self):
        committed = styleframe.STYLEFRAME_PATH.read_text(encoding="utf-8")
        assert committed == styleframe.render_styleframe(), (
            "docs/design/styleframe.html is stale — run "
            ".venv/bin/python scripts/build_styleframe.py"
        )

    def test_styleframe_embeds_the_live_stylesheet(self):
        committed = styleframe.STYLEFRAME_PATH.read_text(encoding="utf-8")
        assert ui._CSS in committed
        assert styleframe._SF_CSS in committed

    def test_styleframe_has_no_unstyled_classes(self):
        committed = styleframe.STYLEFRAME_PATH.read_text(encoding="utf-8")
        match = _STYLE_RE.search(committed)
        assert match, "styleframe has no <style> block"
        css = match.group(1)
        missing = sorted(cls for cls in _classes(committed) if not _has_rule(css, cls))
        assert not missing, f"styleframe classes with no rule: {missing}"

    def test_styleframe_is_well_formed(self):
        balance = _Balance()
        balance.feed(styleframe.STYLEFRAME_PATH.read_text(encoding="utf-8"))
        assert not balance.errors, f"mismatched tags: {balance.errors[:5]}"
        assert not balance.stack, f"unclosed tags: {balance.stack[-5:]}"
