"""Download phase: raw JSON, spreadsheet/calendar exports, and every crawled file.

Files that already exist with the expected size are skipped, so re-running resumes an interrupted
download. JSON and exports are always rewritten.
"""

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePath

from playwright.sync_api import Playwright
from rich.markup import escape
from rich.progress import BarColumn, DownloadColumn, Progress, SpinnerColumn, TextColumn, TimeRemainingColumn

from auth import ApiError, Session, SessionExpired, relogin
from crawl import COURSE_INFO, CourseCrawl, RemoteFile
from exports import write_calendar_ics, write_classlist_csv, write_grades_csv
from prompts import DownloadOptions
from ui import console, warn

CATEGORY_DIRS = {COURSE_INFO: "course info"}  # every other category's folder is its key
JSON_NAMES = {COURSE_INFO: "course.json"}  # every other category's JSON is "<key>.json"
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
class Summary:
    downloaded: int = 0
    downloaded_bytes: int = 0
    skipped_existing: int = 0
    skipped_videos: int = 0
    failed: list[tuple[Path, str]] = field(default_factory=list)


def course_dir(root: Path, crawl: CourseCrawl) -> Path:
    # the D2L course name already includes the term ("Spring 2025 CSC 230 ..."), which keeps
    # same-named courses from different terms apart
    return root / safe_name(crawl.course.name)


def category_dir(root: Path, crawl: CourseCrawl, key: str) -> Path:
    return course_dir(root, crawl) / CATEGORY_DIRS.get(key, key)


def plan(root: Path, crawls: list[CourseCrawl]) -> tuple[Namer, list[Job]]:
    """Decide where every file goes. JSON and export names are claimed first so files can't take them."""
    namer = Namer()
    jobs = []
    for crawl in crawls:
        for key, result in crawl.results.items():
            if result.error is not None:
                continue
            base = category_dir(root, crawl, key)
            namer.claim(base, JSON_NAMES.get(key, f"{key}.json"))
            if key in EXPORTS:
                namer.claim(base, EXPORTS[key][0])
            for f in result.files:
                directory = base.joinpath(*(safe_name(part) for part in f.path))
                jobs.append(Job(crawl, f, namer.claim(directory, f.name)))
    return namer, jobs


def write_metadata(root: Path, crawls: list[CourseCrawl]) -> list[tuple[Path, str]]:
    """Write each category's raw JSON and its CSV/ICS export. Returns failures instead of stopping."""
    failed = []
    for crawl in crawls:
        for key, result in crawl.results.items():
            if result.error is not None:
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


def _already_have(job: Job) -> bool:
    if not job.dest.exists():
        return False
    size = job.dest.stat().st_size
    return size == job.file.size if job.file.size is not None else size > 0


def _fetch(p: Playwright, session: Session, job: Job, progress: Progress) -> bytes:
    """Fetch a file, pausing for a browser re-login whenever the session turns out to have expired."""
    while True:
        try:
            return session.fetch(job.file.url)
        except SessionExpired:
            pass
        except ApiError as e:
            # an expired session answers 403, the same as hidden content; whoami tells them apart
            if e.status != 403 or session.is_valid():
                raise
        progress.stop()
        warn("Your Brightspace session expired. Log in again in the browser to continue.")
        relogin(p, session)
        progress.start()


def download(p: Playwright, session: Session, crawls: list[CourseCrawl], options: DownloadOptions) -> Summary:
    root = options.output
    summary = Summary()
    summary.failed += write_metadata(root, crawls)

    _, jobs = plan(root, crawls)
    wanted = [j for j in jobs if options.videos or not j.file.is_video]
    summary.skipped_videos = len(jobs) - len(wanted)
    todo = []
    for job in wanted:
        if _already_have(job):
            summary.skipped_existing += 1
        else:
            todo.append(job)
    if not todo:
        return summary

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
        for job in todo:
            progress.update(task, description=escape(f"{job.crawl.course.short_name} · {job.dest.name}"))
            try:
                data = _fetch(p, session, job, progress)
                job.dest.parent.mkdir(parents=True, exist_ok=True)
                partial = job.dest.with_name(job.dest.name + ".part")
                partial.write_bytes(data)
                partial.replace(job.dest)  # never leave a half-written file under the real name
                summary.downloaded += 1
                summary.downloaded_bytes += len(data)
            except SessionExpired:
                raise  # re-login itself failed; nothing sensible to continue with
            except Exception as e:
                summary.failed.append((job.dest, f"{type(e).__name__}: {e}"))
            progress.advance(task, job.file.size or 0)
    return summary
