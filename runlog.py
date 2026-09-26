"""End-of-run logs: a detailed `download log.txt` in each course folder, and a summary of every
course in the archive root. Each run is appended, so the logs keep the history of every run."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from crawl import LABELS, CourseCrawl, total_size
from ui import format_size, plural

LOG_NAME = "download log.txt"
RULE = "=" * 78


@dataclass
class CourseLog:
    """Everything one run did for one course; `download.py` fills it in."""
    crawl: CourseCrawl
    folder: Path
    downloaded: list[tuple[Path, int]] = field(default_factory=list)  # (file, bytes)
    existing: list[Path] = field(default_factory=list)  # already in the archive, skipped
    videos: list[tuple[Path, int | None]] = field(default_factory=list)  # not opted in, skipped
    pages: list[Path] = field(default_factory=list)
    markdown: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def downloaded_bytes(self) -> int:
        return sum(size for _, size in self.downloaded)


def local_time(t: datetime) -> str:
    """"Sat 26 Sep 2026, 12:50 PM"."""
    return f"{t:%a} {t.day} {t:%b %Y}, {t.hour % 12 or 12}:{t:%M} {'AM' if t.hour < 12 else 'PM'}"


def duration(seconds: float) -> str:
    seconds = round(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    return f"{minutes // 60}h {minutes % 60}m"


def _header(title: str, started: datetime, finished: datetime, stopped: str | None, options) -> list[str]:
    markdown = ", ".join(LABELS.get(k, k) for k in options.markdown) or "none"
    end = local_time(finished)
    if finished.date() == started.date():
        end = end.split(", ", 1)[1]  # just the time
    return [
        RULE,
        f"{title}  {local_time(started)} to {end} ({duration((finished - started).total_seconds())})",
        f"Result: {'stopped early: ' + stopped if stopped else 'completed'}",
        f"Options: videos {'yes' if options.videos else 'no'} · Markdown copies: {markdown}",
        f"Archive: {options.output}",
        RULE,
    ]


def _rel(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return str(path)


def _files(lines: list[str], heading: str, items: list[tuple[Path, int | None]], base: Path) -> None:
    if not items:
        return
    known = [size for _, size in items if size is not None]
    lines += ["", f"{heading}: {plural(len(items), 'file')}, {format_size(sum(known))}"]
    width = max(len(_rel(p, base)) for p, _ in items)
    lines += [f"  {_rel(p, base).ljust(width)}  {format_size(size) if size is not None else 'size unknown'}" for p, size in items]


def course_section(log: CourseLog, started: datetime, finished: datetime, stopped: str | None, options) -> str:
    c, base = log.crawl.course, log.folder
    lines = _header("Download run", started, finished, stopped, options)
    lines += [f"Course: {c.name}", f"  Code {c.code} · Brightspace id {c.id} · term {c.term_label}", "", "Crawl"]

    width = max(len(LABELS[k]) for k in log.crawl.results)
    for key, r in log.crawl.results.items():
        label = LABELS[key].ljust(width)
        if r.error is not None:
            lines.append(f"  {label}  {r.error}")
            continue
        detail = [plural(r.items, r.unit)] if r.unit != "file" else []  # items that are files would repeat the count
        detail += [plural(len(r.files), "file"), format_size(total_size(r.files))]
        if r.links:
            detail.append(plural(r.links, "link"))
        if r.note:
            detail.append(r.note)
        lines.append(f"  {label}  {' · '.join(detail)}")

    _files(lines, "Downloaded", log.downloaded, base)
    if log.existing:
        lines += ["", f"Already in the archive, not downloaded again: {plural(len(log.existing), 'file')}"]
    _files(lines, "Videos not downloaded (not opted in)", log.videos, base)

    missing = [m for r in log.crawl.results.values() for m in r.missing]
    if missing:
        lines += ["", f"Linked from pages but missing on Brightspace (left as Brightspace links): {len(missing)}"]
        lines += [f"  {m}" for m in missing]

    if log.pages:
        copies = f" (+ {len(log.markdown)} Markdown copies)" if log.markdown else ""
        lines += ["", f"Pages written: {len(log.pages)}{copies}"]
        lines += [f"  {_rel(p, base)}" for p in sorted(log.pages + log.markdown)]

    lines += ["", f"Failures: {len(log.failed)}" if log.failed else "Failures: none"]
    lines += [f"  {_rel(p, base)}: {reason}" for p, reason in log.failed]
    return "\n".join(lines) + "\n\n"


def archive_section(logs: list[CourseLog], root: Path, started: datetime, finished: datetime, stopped: str | None, options) -> str:
    lines = _header("Download run", started, finished, stopped, options)
    lines += [f"Courses: {len(logs)}", ""]

    headings = ["Course", "Downloaded", "Size", "Skipped", "Videos skipped", "Pages", "Failures"]
    rows = [[
        log.crawl.course.name,
        str(len(log.downloaded)),
        format_size(log.downloaded_bytes),
        str(len(log.existing)),
        str(len(log.videos)),
        str(len(log.pages)) + (f" + {len(log.markdown)} md" if log.markdown else ""),
        str(len(log.failed)),
    ] for log in logs]
    rows.append([
        "Total",
        str(sum(len(l.downloaded) for l in logs)),
        format_size(sum(l.downloaded_bytes for l in logs)),
        str(sum(len(l.existing) for l in logs)),
        str(sum(len(l.videos) for l in logs)),
        str(sum(len(l.pages) for l in logs)) + (f" + {sum(len(l.markdown) for l in logs)} md" if any(l.markdown for l in logs) else ""),
        str(sum(len(l.failed) for l in logs)),
    ])
    widths = [max(len(r[i]) for r in [headings, *rows]) for i in range(len(headings))]
    fmt = lambda r: "  " + "  ".join(v.ljust(w) if i == 0 else v.rjust(w) for i, (v, w) in enumerate(zip(r, widths)))
    lines += [fmt(headings), "  " + "-" * (sum(widths) + 2 * (len(widths) - 1)), *map(fmt, rows[:-1]),
              "  " + "-" * (sum(widths) + 2 * (len(widths) - 1)), fmt(rows[-1])]

    unavailable = [(log.crawl.course.name, LABELS[k], r.error) for log in logs for k, r in log.crawl.results.items() if r.error]
    if unavailable:
        lines += ["", "Categories that couldn't be crawled:"]
        lines += [f"  {course} · {label}: {error}" for course, label, error in unavailable]

    failures = [(log, p, reason) for log in logs for p, reason in log.failed]
    lines += ["", f"Failures: {len(failures)}" if failures else "Failures: none"]
    lines += [f"  {_rel(p, root)}: {reason}" for _, p, reason in failures]
    lines += ["", f"Details for each course are in its folder's \"{LOG_NAME}\"."]
    return "\n".join(lines) + "\n\n"


def write_logs(logs: list[CourseLog], root: Path, started: datetime, finished: datetime, stopped: str | None, options) -> Path:
    """Append this run to every course's log and to the archive log. Returns the archive log's path."""
    for log in logs:
        log.folder.mkdir(parents=True, exist_ok=True)
        with (log.folder / LOG_NAME).open("a", encoding="utf-8") as f:
            f.write(course_section(log, started, finished, stopped, options))
    root.mkdir(parents=True, exist_ok=True)
    path = root / LOG_NAME
    with path.open("a", encoding="utf-8") as f:
        f.write(archive_section(logs, root, started, finished, stopped, options))
    return path
