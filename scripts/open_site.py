"""Open the deployed operator UI in agent-browser, authenticated.

The dashboard at https://social.atento.vn/ sits behind nginx HTTP basic auth.
agent-browser's own auth vault is form-based (`auth login` waits for a login
form), which an HTTP challenge is not, so the supported path is to hand Chrome
the pair with `set credentials` before it navigates. This script is that bridge:
it reads the pair from the git-ignored credentials.yaml and drives the browser.

    .venv/bin/python scripts/open_site.py
    .venv/bin/python scripts/open_site.py https://social.atento.vn/status

The credentials live beside the page token — never in the committed config, and
never in git:

    site:
      user: atento
      password: "..."

Exit codes: 0 opened, 1 agent-browser failed, 2 no credentials configured.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

# Work from a bare checkout too (pytest gets this via the test config).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from social_bot.config import load_config  # noqa: E402

DEFAULT_URL = "https://social.atento.vn/"


def site_credentials(cfg: dict) -> tuple[str, str]:
    """The (user, password) for the deployed UI, or ("", "") when unset."""
    site = cfg.get("site") or {}
    return str(site.get("user") or "").strip(), str(site.get("password") or "").strip()


def main(argv: list[str]) -> int:
    url = argv[1] if len(argv) > 1 else DEFAULT_URL
    user, password = site_credentials(load_config())
    if not (user and password):
        print(
            "open_site: set site.user and site.password in credentials.yaml",
            file=sys.stderr,
        )
        return 2
    # agent-browser's HTTP-auth API takes user + password, so the pair has to
    # cross as arguments. It is sourced from the file, never typed, so it stays
    # out of shell history.
    set_creds = subprocess.run(["agent-browser", "set", "credentials", user, password])
    if set_creds.returncode:
        return 1
    return subprocess.run(["agent-browser", "open", url]).returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
