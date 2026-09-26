import sys, threading, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root
import httpx
import auth
from auth import PROFILES, ApiError, Session, SessionExpired

def check(name, got, want):
    print("PASS" if got == want else f"FAIL (got {got!r})", name)

check("profiles: all parallel, increasing", [p.workers for p in PROFILES.values()], sorted(p.workers for p in PROFILES.values()))
check("profiles: polite is still parallel", PROFILES["polite"].workers > 1, True)

real_sleep = time.sleep
auth.time.sleep = lambda s: None  # no retry back-off in tests (this patches the shared time module)
lock, active, peak, calls = threading.Lock(), [0], [0], {}

def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    with lock:
        calls[path] = calls.get(path, 0) + 1
        active[0] += 1
        peak[0] = max(peak[0], active[0])
    try:
        real_sleep(0.02)  # the server takes a moment, so requests overlap
        if path == "/flaky" and calls[path] < 3:
            return httpx.Response(503)
        if path == "/login-redirect":
            return httpx.Response(302, headers={"location": "/d2l/login"})
        if path == "/hidden":
            return httpx.Response(403)
        if path.startswith("/json"):
            return httpx.Response(200, json={"path": path})
        return httpx.Response(200, content=b"x" * 10, headers={"content-length": "10"})
    finally:
        with lock:
            active[0] -= 1

def session(workers):
    client = httpx.Client(base_url=auth.BASE_URL, transport=httpx.MockTransport(handler))
    return Session(client, {"lp": "1.0", "le": "1.0"}, {}, workers)

for workers in (3, 6, 12):
    peak[0] = 0
    s = session(workers)
    # nested maps, like the crawl: requests stay within the limit however many threads ask
    s.map(lambda i: s.map(lambda j: s.get_json(f"/json/{i}/{j}"), range(8)), range(8))
    check(f"at most {workers} requests at once (peak {peak[0]})", peak[0] <= workers and peak[0] >= min(workers, 3), True)

s = session(3)
check("map keeps order", s.map(lambda i: s.get_json(f"/json/{i}")["path"], range(10)), [f"/json/{i}" for i in range(10)])
check("retries 5xx", s.fetch("/flaky"), b"x" * 10)
check("head", s.head("/file")[:2], (True, 10))
check("head_many in order", [h[1] for h in s.head_many(["/a", "/hidden", "/b"])], [10, None, 10])
for path, error in (("/login-redirect", SessionExpired), ("/hidden", ApiError)):
    try:
        s.fetch(path)
        check(f"fetch {path} raises", None, error.__name__)
    except error:
        check(f"fetch {path} raises", error.__name__, error.__name__)
try:
    s.map(lambda i: s.fetch("/hidden" if i == 5 else "/ok"), range(20))
    check("map raises the first error", None, "ApiError")
except ApiError:
    check("map raises the first error", "ApiError", "ApiError")
