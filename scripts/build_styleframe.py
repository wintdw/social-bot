"""Regenerate docs/design/styleframe.html from the live UI code.

Run after any change to the operator pages or the shared stylesheet:

    .venv/bin/python scripts/build_styleframe.py

`tests/test_design_system.py` fails if the committed file is stale, so this is
the only supported way to update it — never edit the HTML by hand.
"""

from __future__ import annotations

import pathlib
import sys

# Work from a bare checkout too (pytest gets this via the test config).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from social_bot.styleframe import STYLEFRAME_PATH, render_styleframe  # noqa: E402


def main() -> None:
    STYLEFRAME_PATH.write_text(render_styleframe(), encoding="utf-8")
    print(f"wrote {STYLEFRAME_PATH}")


if __name__ == "__main__":
    main()
