import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root
import download
from auth import ApiError, SessionExpired
from courses import Course
from crawl import CategoryResult, CourseCrawl, RemoteFile
from prompts import DownloadOptions

def check(name, got, want):
    print("PASS" if got == want else f"FAIL (got {got!r})", name)

class FakeSession:
    def __init__(self, script, valid):
        self.script = list(script)  # per fetch call: bytes to return, or an exception to raise
        self.valid = valid
        self.fetches = 0
    def fetch(self, url):
        self.fetches += 1
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step
    def download_to(self, path, dest, on_bytes=None):  # the thread-safe path downloads use
        data = self.fetch(path)
        dest.write_bytes(data)
        return len(data)
    workers = 4
    def is_valid(self):
        return self.valid

relogins = []
download.relogin = lambda p, s: (relogins.append(1), setattr(s, "valid", True))
course = Course(1, "", "Spring 2025 TEST 100", True, "202501")

def run(script, valid):
    relogins.clear()
    out = Path(tempfile.mkdtemp())
    result = CategoryResult(files=[RemoteFile(("attachments",), "a.pdf", "/x", 3)], data={})
    crawls = [CourseCrawl(course, {"announcements": result})]
    s = FakeSession(script, valid)
    summary = download.download(None, s, crawls, DownloadOptions(False, [], out))
    return summary, s, len(relogins), out

summary, s, n, out = run([b"abc"], True)
check("plain download", (summary.downloaded, n, (out / "Spring 2025 TEST 100/announcements/attachments/a.pdf").read_bytes()), (1, 0, b"abc"))

summary, s, n, _ = run([SessionExpired("x"), b"abc"], False)
check("login redirect -> relogin -> retry", (summary.downloaded, n, s.fetches), (1, 1, 2))

summary, s, n, _ = run([ApiError("/x", 403), b"abc"], False)
check("403 with dead session -> relogin -> retry", (summary.downloaded, n, s.fetches), (1, 1, 2))

summary, s, n, _ = run([ApiError("/x", 403)], True)
check("403 with live session -> hidden file, recorded as failure, no relogin", (summary.downloaded, len(summary.failed), n), (0, 1, 0))

summary, s, n, _ = run([ApiError("/x", 404)], True)
check("404 -> failure, no relogin", (len(summary.failed), n), (1, 0))

# parallel: one file finds the session expired; the rest are held, one re-login, then all finish
import threading
class ParallelSession(FakeSession):
    def __init__(self):
        super().__init__([], False)
        self.lock = threading.Lock()
        self.expired_once = False
        self.valid = True
    def fetch(self, url):
        with self.lock:
            self.fetches += 1
            if url == "/f3" and not self.expired_once:
                self.expired_once = True
                raise SessionExpired("x")
        return url.encode()

relogins.clear()
out = Path(tempfile.mkdtemp())
files = [RemoteFile(("attachments",), f"f{i}.pdf", f"/f{i}", 3) for i in range(12)]
crawls = [CourseCrawl(course, {"announcements": CategoryResult(files=files, data={})})]
s = ParallelSession()
summary = download.download(None, s, crawls, DownloadOptions(False, [], out))
got = sorted(p.name for p in (out / "Spring 2025 TEST 100/announcements/attachments").iterdir())
check("parallel: every file downloaded after one re-login", (summary.downloaded, len(relogins), len(got), summary.failed), (12, 1, 12, []))
check("parallel: no .part files left", [n for n in got if n.endswith(".part")], [])
