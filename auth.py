"""Log in to UVic Brightspace, save the session, and verify it against the Valence API."""

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import httpx
import keyring
from cryptography.fernet import Fernet, InvalidToken
from playwright.sync_api import sync_playwright, Playwright

from ui import console, ok, warn

BASE_URL = "https://bright.uvic.ca"
STATE_FILE = Path(__file__).parent / ".auth" / "state.enc"
LOGIN_TIMEOUT_MS = 5 * 60 * 1000  # time allowed for the user to finish SSO + MFA

RETRIES = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}
REDIRECTS = {301, 302, 303, 307, 308}
CHUNK = 1 << 16

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


@dataclass(frozen=True)
class Profile:
    name: str
    workers: int  # requests in flight at once
    description: str


# how hard a run hits the server; chosen after login. Every profile runs requests in parallel.
PROFILES = {
    "polite": Profile("Polite", 3, "3 requests at a time: the lightest load on Brightspace. Roughly half as fast as Fair."),
    "fair": Profile("Fair", 6, "6 requests at a time: about the load of a few browser tabs. Recommended."),
    "aggressive": Profile("Aggressive", 12, "12 requests at a time: the heaviest load. A little faster than Fair when crawling, "
                          "usually no faster downloading (your connection is the limit), and more likely to be rate-limited."),
}
DEFAULT_PROFILE = "fair"


def http_client(state: dict) -> httpx.Client:
    """An HTTP client carrying the browser login's cookies. httpx clients are thread-safe, so the
    crawl and download can share one across worker threads."""
    cookies = httpx.Cookies()
    for c in state["cookies"]:
        cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])
    return httpx.Client(
        base_url=BASE_URL, cookies=cookies, follow_redirects=False,  # a login redirect must not pass for data
        timeout=httpx.Timeout(60.0), limits=httpx.Limits(max_connections=max(p.workers for p in PROFILES.values()) * 2),
    )


@dataclass
class Session:
    """The logged-in API session. Every method is safe to call from worker threads; at most `workers`
    requests are in flight at once however many threads are asking (see `set_workers`)."""
    http: httpx.Client
    versions: dict[str, str]  # product code -> latest API version, e.g. {"lp": "1.63"}
    user: dict
    workers: int = PROFILES[DEFAULT_PROFILE].workers
    _slots: threading.BoundedSemaphore = field(init=False, repr=False)

    def __post_init__(self):
        self.set_workers(self.workers)

    def set_workers(self, workers: int) -> None:
        """Set how many requests may run at once (the scraping profile). Call between phases, not mid-run."""
        self.workers = workers
        self._slots = threading.BoundedSemaphore(workers)

    def _request(self, method: str, path: str, params: dict | None = None) -> httpx.Response:
        """A request with retries on network errors, 429, and 5xx (waits 1s, 2s, 4s between attempts)."""
        for attempt in range(RETRIES + 1):
            try:
                with self._slots:
                    resp = self.http.request(method, path, params=params)
            except httpx.TransportError:
                if attempt == RETRIES:
                    raise
            else:
                if resp.status_code not in RETRY_STATUSES or attempt == RETRIES:
                    return resp
            time.sleep(2 ** attempt)  # outside the slot, so waiting doesn't hold up other requests

    def get_json(self, path: str, params: dict | None = None):
        """GET a Valence endpoint and return its JSON. `{lp}` etc. in `path` are filled from versions."""
        resp = self._request("GET", path.format(**self.versions), params)
        if resp.is_success and "application/json" in resp.headers.get("content-type", ""):
            return resp.json()
        if resp.status_code in (301, 302, 401) or resp.is_success:
            raise SessionExpired(f"GET {path}: HTTP {resp.status_code}")
        raise ApiError(path, resp.status_code)

    def fetch(self, path: str) -> bytes:
        """A small file's bytes (pages, stylesheets). Raises SessionExpired on a login redirect,
        ApiError on other failures. Use `download_to` for anything that may be large."""
        resp = self._request("GET", path)
        if resp.status_code in REDIRECTS:
            location = resp.headers.get("location", "")
            if "login" in location.lower():
                raise SessionExpired(f"GET {path}: redirected to login")
            resp = self._request("GET", location)  # one hop, e.g. to a file server
        if resp.status_code == 401:
            raise SessionExpired(f"GET {path}: HTTP 401")
        if not resp.is_success:
            raise ApiError(path, resp.status_code)
        return resp.content

    def download_to(self, path: str, dest: Path, on_bytes: Callable[[int], None] | None = None) -> int:
        """Stream a file to `dest`, retrying like `_request`; returns its size. Raises SessionExpired on
        a login redirect or 401, ApiError on other failures. `on_bytes` gets each chunk's size (negative
        to take back a failed attempt)."""
        for attempt in range(RETRIES + 1):
            written = 0
            try:
                with self._slots:
                    url, hops = path, 0
                    while True:
                        with self.http.stream("GET", url) as resp:
                            if resp.status_code in REDIRECTS and hops == 0:
                                location = resp.headers.get("location", "")
                                if "login" in location.lower():
                                    raise SessionExpired(f"GET {path}: redirected to login")
                                url, hops = location, 1  # one hop, e.g. to a file server
                                continue
                            if resp.status_code == 401 or resp.status_code in REDIRECTS:
                                raise SessionExpired(f"GET {path}: HTTP {resp.status_code}")
                            if resp.status_code in RETRY_STATUSES and attempt < RETRIES:
                                break
                            if not resp.is_success:
                                raise ApiError(path, resp.status_code)
                            with dest.open("wb") as f:
                                for chunk in resp.iter_bytes(CHUNK):
                                    f.write(chunk)
                                    written += len(chunk)
                                    if on_bytes:
                                        on_bytes(len(chunk))
                            return written
            except httpx.TransportError:
                if attempt == RETRIES:
                    raise
            if on_bytes and written:
                on_bytes(-written)
            time.sleep(2 ** attempt)
        raise ApiError(path, 0)  # not reached: the last attempt returns or raises

    def head(self, path: str) -> tuple[bool, int | None, dict[str, str]]:
        """HEAD a file: (exists, size or None if not reported, response headers)."""
        try:
            resp = self._request("HEAD", path)
        except httpx.TransportError:
            return False, None, {}
        length = resp.headers.get("content-length")
        size = int(length) if resp.is_success and length and length.isdigit() else None
        return resp.is_success, size, dict(resp.headers)

    def head_size(self, path: str) -> int | None:
        """A file's size from a HEAD request, or None if the server doesn't report one."""
        return self.head(path)[1]

    def head_many(self, paths: list[str], done: Callable[[int], None] | None = None) -> list[tuple[bool, int | None, dict[str, str]]]:
        """`head` for many paths in parallel, in order."""
        return self.map(self.head, paths, done)

    def map(self, fn: Callable, items, done: Callable[[int], None] | None = None) -> list:
        """`fn` over `items` on worker threads, results in order; `done` gets the count finished so far.
        The first exception is raised and work not yet started is cancelled."""
        items = list(items)
        if len(items) <= 1:
            results = [fn(item) for item in items]
            if done and items:
                done(1)
            return results
        pool = ThreadPoolExecutor(self.workers)
        try:
            futures = [pool.submit(fn, item) for item in items]
            results = []
            for future in futures:
                results.append(future.result())
                if done:
                    done(len(results))
            return results
        finally:
            pool.shutdown(wait=True, cancel_futures=True)

    def is_valid(self) -> bool:
        """Whether the session is still logged in. An expired session gets 403 on every API call,
        so this is how a 403 is told apart from content that is genuinely hidden."""
        try:
            self.get_json("/d2l/api/lp/{lp}/users/whoami")
            return True
        except (SessionExpired, ApiError):
            return False
        except httpx.TransportError:
            return True  # can't tell; treat the 403 as a real one rather than forcing a login


def _open_session(p: Playwright) -> Session | None:
    """Build a Session from the saved state, or return None if it is missing or no longer valid."""
    state = load_state()
    if state is None:
        return None

    http = http_client(state)
    versions = http.get("/d2l/api/versions/")
    if versions.status_code in (401, 403) or versions.status_code in REDIRECTS:
        http.close()
        return None  # an expired session is refused here too; log in again
    if not versions.is_success:
        http.close()
        raise RuntimeError(f"Could not read API versions: HTTP {versions.status_code}")

    session = Session(http, {v["ProductCode"]: v["LatestVersion"] for v in versions.json()}, {})
    try:
        session.user = session.get_json("/d2l/api/lp/{lp}/users/whoami")
    except (SessionExpired, ApiError) as e:
        # whoami answers an invalid session with 403; elsewhere 403 means hidden content
        if isinstance(e, ApiError) and e.status != 403:
            raise
        http.close()
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
    """Log in again in the browser and swap the fresh cookies into the existing session in place.
    Must run on the main thread (Playwright's browser)."""
    login(p)
    old, session.http = session.http, http_client(load_state())
    old.close()
    if not session.is_valid():
        raise SessionExpired("Login finished but the session could not be verified.")
    ok("Logged in again, resuming")


def main() -> None:
    with sync_playwright() as p:
        connect(p)


if __name__ == "__main__":
    main()
