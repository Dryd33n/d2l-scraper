import re, sys, tempfile
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root
import download
from auth import ApiError, SessionExpired
from courses import Course
from crawl import COURSE_FILES, CategoryResult, CourseCrawl, RemoteFile
from prompts import DownloadOptions
from runlog import LOG_NAME, duration

def check(name, got, want):
    print("PASS" if got == want else f"FAIL (got {got!r})", name)

check("duration seconds", duration(42.4), "42s")
check("duration minutes", duration(125), "2m 5s")
check("duration hours", duration(3 * 3600 + 120), "3h 2m")

class FakeSession:
    def __init__(self, script):
        self.script = list(script)
    def fetch(self, url):
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
        return True

download.relogin = lambda p, s: (_ for _ in ()).throw(SessionExpired("login failed"))

def crawls():
    a = Course(1, "202501 TEST 100 CO", "Spring 2025 TEST 100", True, "202501")
    b = Course(2, "202501 TEST 200 CO", "Spring 2025 TEST 200", True, "202501")
    return [
        CourseCrawl(a, {
            "announcements": CategoryResult(unit="announcement", items=0, data=[], files=[
                RemoteFile(("attachments",), "a.pdf", "/a", 3),
                RemoteFile(("attachments",), "b.pdf", "/b", 3),
                RemoteFile(("attachments",), "lecture.mp4", "/v", 1000),
            ]),
            COURSE_FILES: CategoryResult(unit="file", missing=["/content/enforced/1-X/gone.png"]),
        }),
        CourseCrawl(b, {"quizzes": CategoryResult(error="not available (HTTP 403)")}),
    ]

out = Path(tempfile.mkdtemp())
started = datetime.now().astimezone() - timedelta(seconds=90)
summary = download.download(None, FakeSession([b"abc", ApiError("/b", 404)]), crawls(), DownloadOptions(False, [], out), started)
course_log = (out / "Spring 2025 TEST 100" / LOG_NAME).read_text(encoding="utf-8")
archive_log = (out / LOG_NAME).read_text(encoding="utf-8")
check("summary counts from course logs", (summary.downloaded, summary.skipped_videos, len(summary.failed), summary.pages), (1, 1, 1, 1))
check("archive log path returned", summary.log, out / LOG_NAME)
check("course log: completed", "Result: completed" in course_log, True)
check("course log: run length", "(1m 30s)" in course_log, True)
check("course log: course details", "Code 202501 TEST 100 CO · Brightspace id 1 · term Spring 2025" in course_log, True)
check("course log: downloaded file listed", "Downloaded: 1 file, 3 B\n  announcements/attachments/a.pdf  3 B" in course_log, True)
check("course log: skipped video listed", "Videos not downloaded (not opted in): 1 file, 1000 B\n  announcements/attachments/lecture.mp4  1000 B" in course_log, True)
check("course log: missing linked file", "missing on Brightspace (left as Brightspace links): 1\n  /content/enforced/1-X/gone.png" in course_log, True)
check("course log: failure with reason", "Failures: 1\n  announcements/attachments/b.pdf: ApiError" in course_log, True)
check("course log: page listed", "Pages written: 1\n  announcements/announcements.html" in course_log, True)
check("other course's log notes the uncrawlable category", "Quizzes  not available (HTTP 403)" in (out / "Spring 2025 TEST 200" / LOG_NAME).read_text(encoding="utf-8"), True)
check("archive log: one row per course and a total", len(re.findall(r"^  (?:Spring 2025 TEST \d00|Total) +\d", archive_log, re.M)), 3)
check("archive log: uncrawlable category", "Spring 2025 TEST 200 · Quizzes: not available (HTTP 403)" in archive_log, True)
check("archive log: failure path from archive root", "Spring 2025 TEST 100/announcements/attachments/b.pdf: ApiError" in archive_log, True)

# a second run appends; a run that stops early still logs what it did
try:
    download.download(None, FakeSession([SessionExpired("expired")]), crawls(), DownloadOptions(False, [], out))
except SessionExpired:
    pass
course_log = (out / "Spring 2025 TEST 100" / LOG_NAME).read_text(encoding="utf-8")
check("runs are appended", course_log.count("Download run"), 2)
check("stopped run recorded", "Result: stopped early: SessionExpired: login failed" in course_log, True)
check("stopped run: earlier file counted as already there", "Already in the archive, not downloaded again: 1 file" in course_log, True)
check("archive log appended too", (out / LOG_NAME).read_text(encoding="utf-8").count("Result: "), 2)
