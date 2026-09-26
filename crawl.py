"""Deep crawl: walk each selected course and category to find everything that would be downloaded.

Nothing is downloaded here. Each category returns counts, the files it would fetch (with sizes),
and the raw API JSON so the download step can write metadata without fetching it again.
"""

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Callable
from urllib.parse import unquote

from rich.markup import escape
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

from auth import ApiError, Session, SessionExpired
from courses import Course
from ui import console, plural

# Categories the user picks from
CATEGORIES = {
    "content": "Content",
    "classlist": "Classlist",
    "grades": "Grades",
    "discussions": "Discussions",
    "assignments": "Assignments",
    "quizzes": "Quizzes",
    "announcements": "Announcements",
    "calendar": "Calendar",
}
COURSE_INFO = "course_info"  # always crawled, never shown in the picker
LABELS = {COURSE_INFO: "Course info", **CATEGORIES}

VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm", ".avi", ".mkv", ".wmv"}
CALENDAR_RANGE = {"startDateTime": "2000-01-01T00:00:00.000Z", "endDateTime": "2100-01-01T00:00:00.000Z"}

Status = Callable[[str], None]  # reports progress within a category, e.g. "file sizes 12/75"


@dataclass
class RemoteFile:
    path: tuple[str, ...]  # folders within the category folder, e.g. ("01 Week 1", "02 Slides")
    name: str
    url: str  # API path to GET when downloading
    size: int | None  # None when the server doesn't report a size

    @property
    def is_video(self) -> bool:
        return PurePosixPath(self.name.lower()).suffix in VIDEO_EXTENSIONS


@dataclass
class CategoryResult:
    unit: str = "item"  # singular noun for what `items` counts: topic, post, grade item, ...
    items: int = 0
    files: list[RemoteFile] = field(default_factory=list)
    links: int = 0  # link-only items (external URLs, embedded tools); recorded, not downloaded
    note: str = ""  # extra detail for display, e.g. "2 forums · 10 topics"
    data: Any = None  # raw API JSON
    error: str | None = None  # set when the category couldn't be crawled


@dataclass
class CourseCrawl:
    course: Course
    results: dict[str, CategoryResult]  # category key -> result, course info first


def total_size(files: list[RemoteFile]) -> int:
    return sum(f.size for f in files if f.size is not None)


def unknown_sizes(files: list[RemoteFile]) -> int:
    return sum(f.size is None for f in files)


def _paged(s: Session, path: str, params: dict | None = None) -> list:
    """Collect every object from an ObjectListPage endpoint ({"Objects": [...], "Next": url})."""
    page = s.get_json(path, params)
    objects = list(page["Objects"])
    while page["Next"]:
        page = s.get_json(page["Next"])  # Next already carries the query string
        objects += page["Objects"]
    return objects


def _optional(s: Session, path: str, default=None):
    """GET JSON that students may not be allowed to see (403) or that may not exist (404)."""
    try:
        return s.get_json(path)
    except ApiError as e:
        if e.status in (403, 404):
            return default
        raise


def _filename_from_headers(headers: dict[str, str], fallback: str) -> str:
    """Pull the filename out of a Content-Disposition header, preferring the RFC 5987 `filename*` form."""
    disposition = headers.get("content-disposition", "")
    for part in disposition.split(";"):
        key, _, value = part.strip().partition("=")
        if key == "filename*" and "''" in value:
            return unquote(value.split("''", 1)[1])
    for part in disposition.split(";"):
        key, _, value = part.strip().partition("=")
        if key == "filename":
            return unquote(value.strip('"'))
    return fallback


def _course_info(s: Session, course: Course, status: Status) -> CategoryResult:
    le, lp, ou = s.versions["le"], s.versions["lp"], course.id
    r = CategoryResult(unit="page", items=1)
    notes = []

    overview = _optional(s, f"/d2l/api/le/{{le}}/{ou}/overview")  # 404: the course has no overview
    r.data = {"enrollment": course.enrollment, "overview": overview}

    if overview:
        notes.append("overview")
        if overview.get("HasAttachment"):
            url = f"/d2l/api/le/{le}/{ou}/overview/attachment"
            exists, size, headers = s.head(url)
            if exists:
                r.files.append(RemoteFile((), _filename_from_headers(headers, "overview attachment"), url, size))

    url = f"/d2l/api/lp/{lp}/courses/{ou}/image"
    exists, size, headers = s.head(url)
    if exists:
        ext = {"image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}.get(headers.get("content-type", ""), ".jpg")
        r.files.append(RemoteFile((), f"course-image{ext}", url, size))
        notes.append("banner image")

    r.note = " · ".join(notes) or "no overview"
    return r


def _content(s: Session, course: Course, status: Status) -> CategoryResult:
    le, ou = s.versions["le"], course.id
    toc = s.get_json(f"/d2l/api/le/{{le}}/{ou}/content/toc")
    r = CategoryResult(unit="topic", data=toc)

    def walk(modules, path):
        # number module folders so they keep the instructor's order on disk
        for i, m in enumerate(sorted(modules, key=lambda m: m["SortOrder"]), 1):
            here = (*path, f"{i:02d} {m['Title']}")
            for t in m["Topics"]:
                yield here, t
            yield from walk(m["Modules"], here)

    topics = list(walk(toc["Modules"], ()))
    r.items = len(topics)
    all_files = [(path, t) for path, t in topics if t["TypeIdentifier"] == "File"]
    # a broken topic's file is missing on Brightspace itself (IsBroken, no Url); the download would 404
    file_topics = [(path, t) for path, t in all_files if not t["IsBroken"] and t["Url"]]
    broken = len(all_files) - len(file_topics)
    r.links = len(topics) - len(all_files)
    r.note = plural(sum(1 for _ in _modules(toc["Modules"])), "module")
    if broken:
        r.note += f" · {plural(broken, 'broken file')}"

    for i, (path, t) in enumerate(file_topics, 1):
        status(f"file sizes {i}/{len(file_topics)}")
        url = f"/d2l/api/le/{le}/{ou}/content/topics/{t['TopicId']}/file"
        name = PurePosixPath(unquote(t["Url"])).name or t["Title"]
        r.files.append(RemoteFile(path, name, url, s.head_size(url)))
    return r


def _modules(modules):
    for m in modules:
        yield m
        yield from _modules(m["Modules"])


def _classlist(s: Session, course: Course, status: Status) -> CategoryResult:
    ou = course.id
    people = s.get_json(f"/d2l/api/le/{{le}}/{ou}/classlist/")
    groups = []
    for category in _optional(s, f"/d2l/api/lp/{{lp}}/{ou}/groupcategories/", []):
        category_groups = _optional(s, f"/d2l/api/lp/{{lp}}/{ou}/groupcategories/{category['GroupCategoryId']}/groups/", [])
        groups.append({"category": category, "groups": category_groups})
    r = CategoryResult(unit="person", items=len(people), data={"people": people, "groups": groups})
    if groups:
        r.note = plural(len(groups), "group category")
    return r


def _grades(s: Session, course: Course, status: Status) -> CategoryResult:
    ou = course.id
    values = s.get_json(f"/d2l/api/le/{{le}}/{ou}/grades/values/myGradeValues/")
    data = {
        "values": values,
        "items": _optional(s, f"/d2l/api/le/{{le}}/{ou}/grades/", []),  # max points, weights, categories
        "categories": _optional(s, f"/d2l/api/le/{{le}}/{ou}/grades/categories/", []),
        "final": _optional(s, f"/d2l/api/le/{{le}}/{ou}/grades/final/values/myGradeValue"),  # 404 until released
    }
    items = [g for g in values if g["GradeObjectTypeName"] != "Category"]
    r = CategoryResult(unit="grade item", items=len(items), data=data)
    if data["final"]:
        r.note = "final grade released"
    return r


def _discussions(s: Session, course: Course, status: Status) -> CategoryResult:
    base = f"/d2l/api/le/{s.versions['le']}/{course.id}/discussions/forums"
    r = CategoryResult(unit="post", data=[])
    n_topics = 0
    failed_topics = 0

    forums = s.get_json(f"{base}/")
    for forum in forums:
        fid = forum["ForumId"]
        topics = []
        for topic in s.get_json(f"{base}/{fid}/topics/"):
            tid = topic["TopicId"]
            status(f"{forum['Name']} › {topic['Name']}")
            try:
                posts = s.get_json(f"{base}/{fid}/topics/{tid}/posts/")
            except ApiError as e:
                # some topics fail server-side (HTTP 500) on every attempt; keep the rest of the forum
                failed_topics += 1
                topics.append({"topic": topic, "posts": [], "error": f"HTTP {e.status}"})
                continue
            r.items += len(posts)
            for post in posts:
                for a in post["Attachments"]:
                    url = f"{base}/{fid}/topics/{tid}/posts/{post['PostId']}/attachments/{a['FileId']}"
                    path = (forum["Name"], topic["Name"], "attachments")
                    r.files.append(RemoteFile(path, a["FileName"], url, a["Size"]))
            topics.append({"topic": topic, "posts": posts})
        n_topics += len(topics)
        r.data.append({"forum": forum, "topics": topics})

    if forums:
        r.note = f"{plural(len(forums), 'forum')} · {plural(n_topics, 'topic')}"
    if failed_topics:
        r.note += f" · {plural(failed_topics, 'topic')} failed"
    return r


def _assignments(s: Session, course: Course, status: Status) -> CategoryResult:
    base = f"/d2l/api/le/{s.versions['le']}/{course.id}/dropbox/folders"
    r = CategoryResult(unit="assignment", data=[])
    n_submissions = 0

    folders = s.get_json(f"{base}/")
    r.items = len(folders)
    for folder in folders:
        fid, name = folder["Id"], folder["Name"]
        status(name)
        r.links += len(folder["LinkAttachments"])
        for a in folder["Attachments"]:
            url = f"{base}/{fid}/attachments/{a['FileId']}"
            r.files.append(RemoteFile((name, "attachments"), a["FileName"], url, a["Size"]))

        mine = s.get_json(f"{base}/{fid}/submissions/mysubmissions/")
        for entity in mine:
            for sub in entity["Submissions"]:
                n_submissions += 1
                day = (sub.get("SubmissionDate") or "undated")[:10]
                for f in sub["Files"]:
                    url = f"{base}/{fid}/submissions/{sub['Id']}/files/{f['FileId']}"
                    r.files.append(RemoteFile((name, "submissions", day), f["FileName"], url, f["Size"]))
            feedback = entity.get("Feedback") or {}
            for f in feedback.get("Files", []):
                e = entity["Entity"]
                url = f"{base}/{fid}/feedback/{e['EntityType'].lower()}/{e['EntityId']}/attachments/{f['FileId']}"
                r.files.append(RemoteFile((name, "feedback"), f["FileName"], url, f["Size"]))
        r.data.append({"folder": folder, "mysubmissions": mine})

    if n_submissions:
        r.note = plural(n_submissions, "submission")
    return r


def _quizzes(s: Session, course: Course, status: Status) -> CategoryResult:
    quizzes = _paged(s, f"/d2l/api/le/{{le}}/{course.id}/quizzes/")
    return CategoryResult(unit="quiz", items=len(quizzes), data=quizzes)


def _announcements(s: Session, course: Course, status: Status) -> CategoryResult:
    le, ou = s.versions["le"], course.id
    news = s.get_json(f"/d2l/api/le/{{le}}/{ou}/news/")
    r = CategoryResult(unit="announcement", items=len(news), data=news)
    for item in news:
        for a in item["Attachments"]:
            url = f"/d2l/api/le/{le}/{ou}/news/{item['Id']}/attachments/{a['FileId']}"
            r.files.append(RemoteFile(("attachments",), a["FileName"], url, a["Size"]))
    return r


def _calendar(s: Session, course: Course, status: Status) -> CategoryResult:
    events = _paged(s, f"/d2l/api/le/{{le}}/{course.id}/calendar/events/myEvents/", CALENDAR_RANGE)
    return CategoryResult(unit="event", items=len(events), data=events)


CRAWLERS = {
    COURSE_INFO: _course_info,
    "content": _content,
    "classlist": _classlist,
    "grades": _grades,
    "discussions": _discussions,
    "assignments": _assignments,
    "quizzes": _quizzes,
    "announcements": _announcements,
    "calendar": _calendar,
}


def crawl_category(session: Session, course: Course, key: str, status: Status) -> CategoryResult:
    """Crawl one category. API errors become `error` on the result instead of stopping the crawl."""
    try:
        return CRAWLERS[key](session, course, status)
    except SessionExpired:
        raise
    except ApiError as e:
        reason = "not available" if e.status in (403, 404) else "failed"
        return CategoryResult(error=f"{reason} (HTTP {e.status})")
    except Exception as e:  # unexpected response shape: report it, keep crawling other categories
        return CategoryResult(error=f"failed ({type(e).__name__}: {e})")


def crawl(session: Session, courses: list[Course], categories: list[str]) -> list[CourseCrawl]:
    """Crawl course info plus every selected category of every selected course, with a progress bar."""
    keys = [COURSE_INFO, *categories]
    crawls = []
    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Crawling", total=len(courses) * len(keys))
        for course in courses:
            results = {}
            for key in keys:
                label = escape(f"{course.short_name} · {LABELS[key]}")
                progress.update(task, description=label)
                status = lambda text: progress.update(task, description=f"{label} [dim]{escape(text)}[/]")
                results[key] = crawl_category(session, course, key, status)
                progress.advance(task)
            crawls.append(CourseCrawl(course, results))
    return crawls
