"""Download phase: raw JSON, spreadsheet/calendar exports, every crawled file, and the generated pages.

Files that already exist with the expected size are skipped, so re-running resumes an interrupted
download. JSON, exports, and pages are always rewritten.
"""

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePath

from playwright.sync_api import Playwright
from rich.markup import escape
from rich.progress import BarColumn, DownloadColumn, Progress, SpinnerColumn, TextColumn, TimeRemainingColumn

from auth import ApiError, Session, SessionExpired, relogin
from crawl import COURSE_FILES, COURSE_INFO, CourseCrawl, RemoteFile
from embed import rewrite_html
from markdown_copy import to_markdown
from exports import write_calendar_ics, write_classlist_csv, write_grades_csv
from pages import Context, Page, api_tail, document, markdown_page, pages_for, people, targets
from prompts import DownloadOptions
from runlog import CourseLog, write_logs
from ui import console, warn

CATEGORY_DIRS = {COURSE_INFO: "course info", COURSE_FILES: "_course-files"}  # every other category's folder is its key
JSON_NAMES = {COURSE_INFO: "course.json"}  # every other category's JSON is "<key>.json"
NO_JSON = {COURSE_FILES}  # found in other categories' JSON; nothing of its own to save
EXPORTS = {
    "grades": ("grades.csv", write_grades_csv),
    "classlist": ("classlist.csv", write_classlist_csv),
    "calendar": ("calendar.ics", write_calendar_ics),
}

MAX_COMPONENT = 80  # longest folder or file name, in characters
MAX_PATH = 250  # stay under Windows' classic 260-character path limit
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_name(name: str, limit: int = MAX_COMPONENT) -> str:
    """A file or folder name that's valid on Windows, macOS, and Linux, keeping the extension when shortened."""
    name = " ".join(name.split())  # tabs, newlines, and unicode spaces become single spaces
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).rstrip(". ") or "_"
    suffix = PurePath(name).suffix if len(PurePath(name).suffix) <= 10 else ""
    stem = name[: len(name) - len(suffix)] if suffix else name
    if stem.upper() in WINDOWS_RESERVED:
        stem = f"_{stem}"
    if len(stem) + len(suffix) > limit:
        stem = stem[: max(1, limit - len(suffix))].rstrip(". ")
    return stem + suffix


class Namer:
    """Assigns each file a unique, safe path. The same crawl always produces the same paths,
    which is what lets a re-run recognise files it already downloaded."""

    def __init__(self):
        self.taken: dict[Path, set[str]] = defaultdict(set)

    def claim(self, directory: Path, name: str) -> Path:
        room = MAX_PATH - len(str(directory)) - 1
        name = safe_name(name, limit=max(12, min(MAX_COMPONENT, room)))
        suffix = PurePath(name).suffix
        stem = name[: len(name) - len(suffix)]
        candidate, n = name, 2
        while candidate.lower() in self.taken[directory]:  # case-insensitive, like Windows and macOS
            candidate = f"{stem} ({n}){suffix}"
            n += 1
        self.taken[directory].add(candidate.lower())
        return directory / candidate


@dataclass
class Job:
    crawl: CourseCrawl
    file: RemoteFile
    dest: Path


@dataclass
class PageJob:
    crawl: CourseCrawl
    key: str  # category
    page: Page
    dest: Path
    markdown: Path | None = None  # where its Markdown copy goes, when its category was chosen for Markdown


@dataclass
class Summary:
    """What a run did, per course (also what the logs are written from)."""
    courses: list[CourseLog] = field(default_factory=list)
    other_failures: list[tuple[Path, str]] = field(default_factory=list)  # outside any course folder
    log: Path | None = None  # the archive-wide log, once written

    def course(self, crawl: CourseCrawl) -> CourseLog:
        return next(log for log in self.courses if log.crawl is crawl)

    def fail(self, path: Path, reason: str) -> None:
        log = next((log for log in self.courses if path.is_relative_to(log.folder)), None)
        (log.failed if log else self.other_failures).append((path, reason))

    @property
    def downloaded(self) -> int:
        return sum(len(log.downloaded) for log in self.courses)

    @property
    def downloaded_bytes(self) -> int:
        return sum(log.downloaded_bytes for log in self.courses)

    @property
    def skipped_existing(self) -> int:
        return sum(len(log.existing) for log in self.courses)

    @property
    def skipped_videos(self) -> int:
        return sum(len(log.videos) for log in self.courses)

    @property
    def pages(self) -> int:
        return sum(len(log.pages) for log in self.courses)

    @property
    def markdown(self) -> int:
        return sum(len(log.markdown) for log in self.courses)

    @property
    def failed(self) -> list[tuple[Path, str]]:
        return [f for log in self.courses for f in log.failed] + self.other_failures


def course_dir(root: Path, crawl: CourseCrawl) -> Path:
    # the D2L course name already includes the term ("Spring 2025 CSC 230 ..."), which keeps
    # same-named courses from different terms apart
    return root / safe_name(crawl.course.name)


def category_dir(root: Path, crawl: CourseCrawl, key: str) -> Path:
    return course_dir(root, crawl) / CATEGORY_DIRS.get(key, key)


def plan(root: Path, crawls: list[CourseCrawl], markdown: list[str] = ()) -> tuple[Namer, list[Job], list[PageJob]]:
    """Decide where every file and page goes, with Markdown copies for the categories in `markdown`.
    JSON, export, and page names are claimed first so files can't take them."""
    namer = Namer()
    jobs, page_jobs = [], []
    for crawl in crawls:
        for key, result in crawl.results.items():
            if result.error is not None:
                continue
            base = category_dir(root, crawl, key)
            if key not in NO_JSON:
                namer.claim(base, JSON_NAMES.get(key, f"{key}.json"))
            if key in EXPORTS:
                namer.claim(base, EXPORTS[key][0])
            for page in pages_for(key, result):
                directory = base.joinpath(*(safe_name(part) for part in page.path))
                dest = namer.claim(directory, page.name)
                md = namer.claim(directory, f"{dest.stem}.md") if key in markdown and page.markdown else None
                page_jobs.append(PageJob(crawl, key, page, dest, md))
            for f in result.files:
                directory = base.joinpath(*(safe_name(part) for part in f.path))
                jobs.append(Job(crawl, f, namer.claim(directory, f.name)))
    return namer, jobs, page_jobs


def write_metadata(root: Path, crawls: list[CourseCrawl]) -> list[tuple[Path, str]]:
    """Write each category's raw JSON and its CSV/ICS export. Returns failures instead of stopping."""
    failed = []
    for crawl in crawls:
        for key, result in crawl.results.items():
            if result.error is not None or key in NO_JSON:
                continue
            base = category_dir(root, crawl, key)
            base.mkdir(parents=True, exist_ok=True)
            json_path = base / JSON_NAMES.get(key, f"{key}.json")
            json_path.write_text(json.dumps(result.data, indent=2, ensure_ascii=False), encoding="utf-8")
            if key in EXPORTS:
                name, writer = EXPORTS[key]
                try:
                    writer(result.data, base / name)
                except Exception as e:  # a surprising record shouldn't lose the rest of the archive
                    failed.append((base / name, f"{type(e).__name__}: {e}"))
    return failed


def write_pages(page_jobs: list[PageJob], jobs: list[Job]) -> tuple[list[PageJob], list[PageJob], list[tuple[Path, str]]]:
    """Render every generated page (and its Markdown copy), linking to wherever the download put each file.
    Returns (pages written, pages whose Markdown copy was written, failures)."""
    written, markdown, failed = [], [], []
    for crawl in {id(pj.crawl): pj.crawl for pj in page_jobs}.values():
        files = {api_tail(j.file.url, crawl.course.id): j.dest for j in jobs if j.crawl is crawl}
        names = people(crawl)
        mine = [pj for pj in page_jobs if pj.crawl is crawl]
        course_page = next((pj.dest for pj in mine if pj.key == COURSE_INFO), None)
        by_key = {pj.page.key: pj.dest for pj in mine if pj.page.key}
        where = targets(crawl)
        for pj in mine:
            ctx = Context(crawl, pj.dest, course_page, files, names, by_key, where)
            try:
                if pj.page.standalone:
                    text = pj.page.render(ctx)
                else:  # generated pages: embed rich text's images, point its links at the archive
                    text = document(ctx, pj.page, rewrite_html(pj.page.render(ctx), None, ctx))
                pj.dest.parent.mkdir(parents=True, exist_ok=True)
                pj.dest.write_bytes(text.encode("utf-8"))
                written.append(pj)
            except Exception as e:  # one odd record shouldn't cost the other pages
                failed.append((pj.dest, f"{type(e).__name__}: {e}"))
                continue
            if pj.markdown is None:
                continue
            ctx.embed = False  # the copy links images to their files instead of embedding them
            try:
                if pj.page.standalone:
                    text = to_markdown(pj.page.render(ctx))
                else:
                    text = markdown_page(ctx, pj.page, rewrite_html(pj.page.render(ctx), None, ctx, embed=False))
                pj.markdown.write_bytes(text.encode("utf-8"))
                markdown.append(pj)
            except Exception as e:
                failed.append((pj.markdown, f"{type(e).__name__}: {e}"))
    return written, markdown, failed


def _already_have(job: Job) -> bool:
    if not job.dest.exists():
        return False
    size = job.dest.stat().st_size
    return size == job.file.size if job.file.size is not None else size > 0


def download(p: Playwright, session: Session, crawls: list[CourseCrawl], options: DownloadOptions,
             started: datetime | None = None) -> Summary:
    """Write metadata, download files, write pages, then append this run to the logs. The logs are
    written even when the run stops early; `started` is when the run began (before the crawl)."""
    root = options.output
    started = started or datetime.now().astimezone()
    summary = Summary([CourseLog(c, course_dir(root, c)) for c in crawls])
    stopped = None
    try:
        for path, reason in write_metadata(root, crawls):
            summary.fail(path, reason)

        _, jobs, page_jobs = plan(root, crawls, options.markdown)
        todo = []
        for job in jobs:
            log = summary.course(job.crawl)
            if job.file.is_video and not options.videos:
                log.videos.append((job.dest, job.file.size))
            elif _already_have(job):
                log.existing.append(job.dest)
            else:
                todo.append(job)
        if todo:
            _download_files(p, session, todo, summary)

        written, markdown, failed = write_pages(page_jobs, jobs)  # after the files, so links know what's on disk
        for pj in written:
            summary.course(pj.crawl).pages.append(pj.dest)
        for pj in markdown:
            summary.course(pj.crawl).markdown.append(pj.markdown)
        for path, reason in failed:
            summary.fail(path, reason)
    except KeyboardInterrupt:
        stopped = "cancelled"
        raise
    except Exception as e:
        stopped = f"{type(e).__name__}: {e}"
        raise
    finally:
        try:
            summary.log = write_logs(summary.courses, root, started, datetime.now().astimezone(), stopped, options)
        except OSError as e:
            warn(f"Couldn't write the download log: {e}")
    return summary


class _Stopped(Exception):
    """Raised inside a worker's download to abandon it when the run is stopping."""


def _fetch_one(session: Session, job: Job, expired: threading.Event, advance) -> tuple[str, int | str | None]:
    """Download one file on a worker thread: ("ok", size), ("failed", reason), or ("expired", None)
    when the session has expired (then no worker starts another file until the main thread re-logs in)."""
    if expired.is_set():
        return "expired", None
    job.dest.parent.mkdir(parents=True, exist_ok=True)
    partial = job.dest.with_name(job.dest.name + ".part")
    try:
        if job.file.data is not None:
            partial.write_bytes(job.file.data)
            advance(len(job.file.data))
            size = len(job.file.data)
        else:
            size = session.download_to(job.file.url, partial, advance)
        partial.replace(job.dest)  # never leave a half-written file under the real name
        return "ok", size
    except SessionExpired:
        expired.set()
        return "expired", None
    except ApiError as e:
        # an expired session answers 403, the same as hidden content; whoami tells them apart
        if e.status == 403 and not session.is_valid():
            expired.set()
            return "expired", None
        return "failed", f"{type(e).__name__}: {e}"
    except Exception as e:
        return "failed", f"{type(e).__name__}: {e}"


def _download_files(p: Playwright, session: Session, todo: list[Job], summary: Summary) -> None:
    """Download files in parallel (the session's `workers`). If the session expires, the files still waiting are held
    back, you log in again in the browser (which only works on this thread), and they carry on."""
    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Downloading", total=sum(j.file.size or 0 for j in todo))
        stop = threading.Event()

        def advance(n: int) -> None:  # called by workers for every chunk
            if stop.is_set():
                raise _Stopped()
            progress.advance(task, n)

        done, queue, order = 0, list(todo), {id(job): i for i, job in enumerate(todo)}
        while queue:
            expired, held = threading.Event(), []
            pool = ThreadPoolExecutor(session.workers)
            try:
                futures = {pool.submit(_fetch_one, session, job, expired, advance): job for job in queue}
                for future in as_completed(futures):
                    job = futures[future]
                    outcome, value = future.result()
                    if outcome == "expired":
                        held.append(job)
                        continue
                    done += 1
                    if outcome == "ok":
                        summary.course(job.crawl).downloaded.append((job.dest, value))
                        if job.file.size is None:  # not in the total yet
                            progress.update(task, total=progress.tasks[0].total + value)
                    else:
                        summary.fail(job.dest, value)
                    label = f"{done}/{len(todo)} files · {job.crawl.course.short_name} · {job.dest.name}"
                    progress.update(task, description=escape(label))
            except BaseException:  # Ctrl+C or an error: don't wait for every queued file
                stop.set()
                expired.set()  # workers that haven't started yet return straight away
                raise
            finally:
                pool.shutdown(wait=True, cancel_futures=True)
            if held:
                progress.stop()
                warn("Your Brightspace session expired. Log in again in the browser to continue.")
                relogin(p, session)  # raises SessionExpired if the login fails; the run then stops
                progress.start()
            queue = sorted(held, key=lambda job: order[id(job)])
