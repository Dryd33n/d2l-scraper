"""Log in to UVic Brightspace, save the session, and verify it against the Valence API."""

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import keyring
from cryptography.fernet import Fernet, InvalidToken
from playwright.sync_api import sync_playwright, APIRequestContext, APIResponse, Playwright
from playwright.sync_api import Error as PlaywrightError

from ui import console, ok, warn

BASE_URL = "https://bright.uvic.ca"
STATE_FILE = Path(__file__).parent / ".auth" / "state.enc"
LOGIN_TIMEOUT_MS = 5 * 60 * 1000  # time allowed for the user to finish SSO + MFA
FILE_TIMEOUT_MS = 10 * 60 * 1000  # per file download; videos can be hundreds of MB

RETRIES = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}

KEYRING_SERVICE = "d2l-scraper"
KEYRING_USER = "session-key"


def _fernet() -> Fernet:
    """Return a Fernet cipher keyed from the OS keychain, creating the key on first use."""
    key = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    if key is None:
        key = Fernet.generate_key().decode()
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
    return Fernet(key)


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_bytes(_fernet().encrypt(json.dumps(state).encode()))


def load_state() -> dict | None:
    """Decrypt the saved session, or return None if it is missing or unreadable."""
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(_fernet().decrypt(STATE_FILE.read_bytes()))
    except InvalidToken:
        return None  # key changed or file corrupted; treat as logged out


def login(p: Playwright) -> None:
    """Open a headed browser, let the user log in manually, then save the session."""
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto(f"{BASE_URL}/d2l/login")

    with console.status("Waiting for you to log in in the browser window (SSO + MFA)..."):
        page.wait_for_url(f"{BASE_URL}/d2l/home**", timeout=LOGIN_TIMEOUT_MS)

    save_state(context.storage_state())
    ok(f"Session saved (encrypted) to [dim]{STATE_FILE}[/]")
    browser.close()


class SessionExpired(Exception):
    """Raised when an API call is answered with a login redirect instead of data."""


class ApiError(RuntimeError):
    def __init__(self, path: str, status: int):
        super().__init__(f"GET {path}: HTTP {status}")
        self.status = status


@dataclass
class Session:
    api: APIRequestContext
    versions: dict[str, str]  # product code -> latest API version, e.g. {"lp": "1.63"}
    user: dict

    def _get(self, path: str, params: dict | None = None, timeout: float | None = None) -> APIResponse:
        """GET with retries on network errors, 429, and 5xx (waits 1s, 2s, 4s between attempts)."""
        for attempt in range(RETRIES + 1):
            try:
                # max_redirects=0: an expired session redirects to the login page instead of failing
                resp = self.api.get(path, params=params, max_redirects=0, timeout=timeout)
            except PlaywrightError:
                if attempt == RETRIES:
                    raise
            else:
                if resp.status not in RETRY_STATUSES or attempt == RETRIES:
                    return resp
            time.sleep(2 ** attempt)

    def get_json(self, path: str, params: dict | None = None):
        """GET a Valence endpoint and return its JSON. `{lp}` etc. in `path` are filled from versions."""
        resp = self._get(path.format(**self.versions), params)
        if resp.ok and "application/json" in resp.headers.get("content-type", ""):
            return resp.json()
        if resp.status in (301, 302, 401) or resp.ok:
            raise SessionExpired(f"GET {path}: HTTP {resp.status}")
        raise ApiError(path, resp.status)

    def fetch(self, path: str) -> bytes:
        """Download a file's bytes. Raises SessionExpired on a login redirect, ApiError on other failures."""
        resp = self._get(path, timeout=FILE_TIMEOUT_MS)
        if resp.status in (301, 302, 303, 307, 308):
            location = resp.headers.get("location", "")
            if "login" in location.lower():
                raise SessionExpired(f"GET {path}: redirected to login")
            resp = self._get(location, timeout=FILE_TIMEOUT_MS)  # one hop, e.g. to a file server
        if resp.status == 401:
            raise SessionExpired(f"GET {path}: HTTP 401")
        if not resp.ok:
            raise ApiError(path, resp.status)
        return resp.body()

    def is_valid(self) -> bool:
        """Whether the session is still logged in. An expired session gets 403 on every API call,
        so this is how a 403 is told apart from content that is genuinely hidden."""
        try:
            self.get_json("/d2l/api/lp/{lp}/users/whoami")
            return True
        except (SessionExpired, ApiError):
            return False

    def head(self, path: str) -> tuple[bool, int | None, dict[str, str]]:
        """HEAD a file: (exists, size or None if not reported, response headers)."""
        resp = self.api.head(path, max_redirects=0)
        length = resp.headers.get("content-length")
        size = int(length) if resp.ok and length and length.isdigit() else None
        return resp.ok, size, resp.headers

    def head_size(self, path: str) -> int | None:
        """Return a file's size from a HEAD request, or None if the server doesn't report one."""
        return self.head(path)[1]


def _open_session(p: Playwright) -> Session | None:
    """Build a Session from the saved state, or return None if it is missing or no longer valid."""
    state = load_state()
    if state is None:
        return None

    api = p.request.new_context(base_url=BASE_URL, storage_state=state)
    versions = api.get("/d2l/api/versions/")
    if not versions.ok:
        api.dispose()
        raise RuntimeError(f"Could not read API versions: HTTP {versions.status}")

    session = Session(api, {v["ProductCode"]: v["LatestVersion"] for v in versions.json()}, {})
    try:
        session.user = session.get_json("/d2l/api/lp/{lp}/users/whoami")
    except (SessionExpired, ApiError) as e:
        # whoami answers an invalid session with 403; elsewhere 403 means hidden content
        if isinstance(e, ApiError) and e.status != 403:
            raise
        api.dispose()
        return None
    return session


def connect(p: Playwright) -> Session:
    """Return a verified Session, prompting for a browser login if the saved one is invalid."""
    with console.status("Checking saved session..."):
        session = _open_session(p)
    if session is None:
        warn("No valid session found, opening a browser to log in")
        login(p)
        with console.status("Verifying session..."):
            session = _open_session(p)
    if session is None:
        console.print("[red]✗[/] Login finished but the session could not be verified.")
        sys.exit(1)

    user = session.user
    ok(f"Logged in as [bold]{user['FirstName']} {user['LastName']}[/] [dim]({user['UniqueName']})[/]")
    return session


def relogin(p: Playwright, session: Session) -> None:
    """Log in again in the browser and swap the fresh cookies into the existing session in place."""
    login(p)
    fresh = p.request.new_context(base_url=BASE_URL, storage_state=load_state())
    session.api.dispose()
    session.api = fresh
    if not session.is_valid():
        raise SessionExpired("Login finished but the session could not be verified.")
    ok("Logged in again, resuming")


def main() -> None:
    with sync_playwright() as p:
        connect(p)


if __name__ == "__main__":
    main()
