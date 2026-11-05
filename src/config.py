"""Where the program keeps its data, and which school's Brightspace it talks to."""

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import platformdirs
import questionary
from rich.markup import escape

from ui import PROMPT_STYLE, console, in_thread, ok, warn

# D2L_SCRAPER_HOME keeps a test install away from the real login and settings
APP_DIR = Path(os.environ.get("D2L_SCRAPER_HOME") or platformdirs.user_data_path("d2l-scraper", appauthor=False))
CONFIG_FILE = APP_DIR / "config.json"
STATE_FILE = APP_DIR / "state.enc"
ERROR_LOG = APP_DIR / "error.log"
DEFAULT_OUTPUT = platformdirs.user_documents_path() / "D2L Archive"  # archives hold classmates' personal data

_base_url: str | None = None


def use(url: str) -> None:
    """Talk to this Brightspace for the rest of the run, without saving it."""
    global _base_url
    _base_url = url


def saved_school() -> str | None:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("base_url")
    except (OSError, ValueError, AttributeError):
        return None


def base_url() -> str:
    """The school's Brightspace, e.g. "https://bright.uvic.ca". Call `ensure_school` first."""
    global _base_url
    if _base_url is None:
        _base_url = saved_school()
    if _base_url is None:
        raise RuntimeError("No school chosen yet")
    return _base_url


def normalize(text: str) -> str | None:
    """Reduce a link from anywhere on the site, or a bare address, to "https://host", or None if it
    can't be a web address. Always https: the login cookies must never travel unencrypted."""
    text = text.strip(" \t\r\n\"'<>")
    if not text or any(c.isspace() for c in text):
        return None
    try:
        parts = urlsplit(text if "://" in text else f"https://{text}")
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    if not host or "." not in host:
        return None
    return f"https://{host}" + (f":{port}" if port else "")


def find_brightspace(url: str) -> str | None:
    """The address of the Brightspace at `url`, following redirects, or None if there isn't one.
    Every Brightspace answers the versions endpoint with JSON, logged in or not."""
    try:
        resp = httpx.get(f"{url}/d2l/api/versions/", follow_redirects=True, timeout=15)
        versions = resp.json() if resp.is_success else None
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(versions, list) or not versions or not isinstance(versions[0], dict) or "ProductCode" not in versions[0]:
        return None
    return normalize(str(resp.url))


def set_school(url: str) -> None:
    """Save the school. A login for a different school is no use, so it's dropped."""
    if url != saved_school() and STATE_FILE.exists():
        STATE_FILE.unlink()
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({"base_url": url}), encoding="utf-8")
    use(url)


def choose_school(address: str | None = None) -> None:
    """Ask for the school's Brightspace address until one checks out. Exits if cancelled.
    `address` is tried first, if given."""
    while True:
        if address is None:
            address = in_thread(questionary.text(
                "Open your school's Brightspace in a browser, copy the link, and paste it here:",
                style=PROMPT_STYLE,
            ).ask)
        if address is None:
            warn("Cancelled.")
            sys.exit(1)
        url = normalize(address)
        with console.status("Checking that address..."):
            found = find_brightspace(url) if url else None
        if found:
            set_school(found)
            ok(f"Using [bold]{found.removeprefix('https://')}[/]")
            return
        warn(f"Couldn't find Brightspace at [bold]{escape(address)}[/]. Log in first, copy the link from any "
             "Brightspace page (not your school's sign-in page), and check your internet connection.")
        address = None


def ensure_school() -> None:
    """Ask for the school the first time the program runs."""
    if saved_school() is None and _base_url is None:
        choose_school()
