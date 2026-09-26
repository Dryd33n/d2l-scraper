"""Deep crawl: walk each selected course and category to find everything that would be downloaded.

Nothing is downloaded here. Each category returns counts, the files it would fetch (with sizes),
and the raw API JSON so the download step can write metadata without fetching it again.
"""

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Callable, Iterator
from urllib.parse import quote, unquote

from rich.markup import escape
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

from auth import BASE_URL, ApiError, Session, SessionExpired
from courses import Course
from embed import canonical, css_refs, decode, html_refs, local_folder, view_attachment
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
COURSE_FILES = "course_files"  # files referenced from HTML pages and rich text; always crawled last
LABELS = {COURSE_INFO: "Course info", **CATEGORIES, COURSE_FILES: "Linked files"}

HTML_EXTENSIONS = {".html", ".htm"}
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm", ".avi", ".mkv", ".wmv"}
CALENDAR_RANGE = {"startDateTime": "2000-01-01T00:00:00.000Z", "endDateTime": "2100-01-01T00:00:00.000Z"}

Status = Callable[[str], None]  # reports progress within a category, e.g. "file sizes 12/75"


@dataclass
class RemoteFile:
    path: tuple[str, ...]  # folders within the category folder, e.g. ("01 Week 1", "02 Slides")
    name: str
    url: str  # API path to GET when downloading
    size: int | None  # None when the server doesn't report a size
    data: bytes | None = field(default=None, repr=False)  # already fetched during the crawl; not fetched again

    @property
    def is_video(self) -> bool:
        return PurePosixPath(self.name.lower()).suffix in VIDEO_EXTENSIONS


@dataclass
class HtmlPage:
    """An HTML content topic, fetched during the crawl so its references can be found."""
    topic_id: int
    path: tuple[str, ...]  # module folders, like RemoteFile.path
    name: str
    url: str  # API path it was fetched from
    base: str  # absolute URL its relative references resolve against
    html: bytes = field(repr=False)


@dataclass
class CategoryResult:
    unit: str = "item"  # singular noun for what `items` counts: topic, post, grade item, ...
    items: int = 0
    files: list[RemoteFile] = field(default_factory=list)
    links: int = 0  # link-only items (external URLs, embedded tools); recorded, not downloaded
    note: str = ""  # extra detail for display, e.g. "2 forums · 10 topics"
    data: Any = None  # raw API JSON
    error: str | None = None  # set when the category couldn't be crawled
    html_pages: list[HtmlPage] = field(default_factory=list)  # content only


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

    modules = list(walk_toc(toc["Modules"]))
    topics = [(path, t) for path, m in modules for t in m["Topics"]]
    r.items = len(topics)
    all_files = [(path, t) for path, t in topics if t["TypeIdentifier"] == "File"]
    # a broken topic's file is missing on Brightspace itself (IsBroken, no Url); the download would 404
    file_topics = [(path, t) for path, t in all_files if not t["IsBroken"] and t["Url"]]
    broken = len(all_files) - len(file_topics)
    r.links = len(topics) - len(all_files)
    r.note = plural(len(modules), "module")
    if broken:
        r.note += f" · {plural(broken, 'broken file')}"

    for i, (path, t) in enumerate(file_topics, 1):
        url = f"/d2l/api/le/{le}/{ou}/content/topics/{t['TopicId']}/file"
        name = PurePosixPath(unquote(t["Url"])).name or t["Title"]
        if PurePosixPath(name.lower()).suffix in HTML_EXTENSIONS:
            # fetched now so the course files step can find what the page references; the download
            # writes a self-contained copy here and keeps this original under _course-files/_originals
            status(f"pages {i}/{len(file_topics)}")
            try:
                html = s.fetch(url)
            except ApiError:
                r.files.append(RemoteFile(path, name, url, None))  # let the download report the failure
                continue
            r.html_pages.append(HtmlPage(t["TopicId"], path, name, url, BASE_URL + quote(unquote(t["Url"]), safe="/()!$'*+,;=:@-._~&"), html))
        else:
            status(f"file sizes {i}/{len(file_topics)}")
            r.files.append(RemoteFile(path, name, url, s.head_size(url)))
    return r


def walk_toc(modules: list[dict], path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], dict]]:
    """(folder path, module) for every module, parents first. Folders are numbered so they keep
    the instructor's order on disk, e.g. ("01 Week 1", "02 Slides")."""
    for i, m in enumerate(sorted(modules, key=lambda m: m["SortOrder"]), 1):
        here = (*path, f"{i:02d} {m['Title']}")
        yield here, m
        yield from walk_toc(m["Modules"], here)


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


def _strings(data) -> Iterator[str]:
    """Every string in a JSON value that could hold HTML."""
    if isinstance(data, str):
        if "<" in data:
            yield data
    elif isinstance(data, dict):
        for value in data.values():
            yield from _strings(value)
    elif isinstance(data, list):
        for value in data:
            yield from _strings(value)


def _course_files(s: Session, course: Course, status: Status, results: dict[str, CategoryResult]) -> CategoryResult:
    """Files referenced from HTML content pages and from rich text (announcements, posts, instructions, ...):
    the course files they link to, and the images, stylesheets, and scripts to embed. Also keeps the
    untouched originals of the HTML content pages."""
    r = CategoryResult(unit="file")
    content = results.get("content")
    html_pages = content.html_pages if content and content.error is None else []
    for page in html_pages:
        r.files.append(RemoteFile(("_originals", *page.path), page.name, page.url, len(page.html), page.html))

    # images shown inside posts are usually also post attachments, which the discussion download has
    attached = set()
    discussions = results.get("discussions")
    if discussions and discussions.error is None:
        attached = {(p["PostId"], a["FileId"]) for f in discussions.data for t in f["topics"]
                    for p in t["posts"] for a in p["Attachments"]}

    wanted: dict[str, bool] = {}  # canonical path -> embedded; embedded wins when a file is both
    def add(refs):
        for ref in refs:
            key = canonical(ref.url)
            post_image = view_attachment(key) if key else None
            if key and not (post_image and post_image[1:] in attached):
                wanted[key] = wanted.get(key, False) or ref.embedded

    for page in html_pages:
        add(html_refs(decode(page.html), page.base))
    for result in results.values():
        if result.error is None:
            for text in _strings(result.data):
                add(html_refs(text, None))  # rich text: relative references can't be resolved

    queue, missing = list(wanted.items()), 0
    for i, (key, embedded) in enumerate(queue):  # stylesheets append what they reference while this runs
        status(f"linked files {i + 1}/{len(queue)}")
        exists, size, headers = s.head(key)
        if not exists:
            missing += 1
            continue
        folder, name = local_folder(key, embedded)
        if post_image := view_attachment(key):
            name = _filename_from_headers(headers, f"image-{post_image[2]}")
        data = None
        if embedded and ("text/css" in headers.get("content-type", "") or name.lower().endswith(".css")):
            try:
                data = s.fetch(key)  # fetched now to find the fonts and images it uses
            except ApiError:
                missing += 1
                continue
            for ref in css_refs(decode(data), BASE_URL + key):
                if (k := canonical(ref.url)) and k not in wanted:
                    wanted[k] = True
                    queue.append((k, True))
        r.files.append(RemoteFile(folder, name, key, len(data) if data is not None else size, data))

    r.items = len(r.files)
    notes = [plural(len(html_pages), "HTML page")] if html_pages else []
    if missing:
        notes.append(f"{missing} missing on Brightspace")
    r.note = " · ".join(notes)
    return r


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


def crawl_category(session: Session, course: Course, key: str, status: Status,
                   results: dict[str, CategoryResult] | None = None) -> CategoryResult:
    """Crawl one category. API errors become `error` on the result instead of stopping the crawl.
    Course files need the other categories' `results`."""
    try:
        if key == COURSE_FILES:
            return _course_files(session, course, status, results or {})
        return CRAWLERS[key](session, course, status)
    except SessionExpired:
        raise
    except ApiError as e:
        reason = "not available" if e.status in (403, 404) else "failed"
        return CategoryResult(error=f"{reason} (HTTP {e.status})")
    except Exception as e:  # unexpected response shape: report it, keep crawling other categories
        return CategoryResult(error=f"failed ({type(e).__name__}: {e})")


def crawl(session: Session, courses: list[Course], categories: list[str]) -> list[CourseCrawl]:
    """Crawl course info, every selected category, and the files they link to, for every selected course."""
    keys = [COURSE_INFO, *categories, COURSE_FILES]
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
                results[key] = crawl_category(session, course, key, status, results)
                progress.advance(task)
            crawls.append(CourseCrawl(course, results))
    return crawls
