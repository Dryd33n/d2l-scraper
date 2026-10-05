"""Study packs: a few clean sources per course to upload to a NotebookLM notebook, built from the
archive on disk (no Brightspace requests).

NotebookLM does the studying; the pack's job is to stay under the notebook's source limit with as
little noise as possible. Downloaded files keep their format (NotebookLM reads PDF, PowerPoint, Word,
and images); pages, assignments, discussions, and quiz questions become Markdown. When there are too
many sources, PDFs are merged per module, then per top-level module, then slides and documents are
turned into text, and only then is anything left out (listed in the manifest).

Run on its own (`python studypack.py`) to rebuild packs from an existing archive, or tick courses in
the main run's "Build a study pack for" question.
"""

import hashlib
import io
import json
import logging
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from crawl import walk_toc, _topic_file_name
from download import safe_name
from markdown_copy import to_markdown
from quiz_attempts import Card, parse_attempt, study_card
from ui import plural

PACKS_DIR = "Study Packs"
LIMIT = 45  # NotebookLM's free plan takes 50 sources; leave room for a few of your own
MANIFEST = "manifest.md"
MAX_WORDS = 450_000  # NotebookLM reads up to 500,000 words per source
MAX_PDF = 190 * 1024 * 1024  # and up to 200 MB per file

NATIVE = {".pdf", ".pptx", ".docx"}  # uploaded as they are
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}  # uploaded as they are, or as PDF pages when merged
OFFICE_TEXT = {".pptx", ".docx"}  # turned into text when there are too many sources
CODE = {".txt": "", ".md": "", ".csv": "csv", ".tex": "latex", ".java": "java", ".c": "c", ".h": "c", ".cpp": "cpp",
        ".hpp": "cpp", ".py": "python", ".asm": "asm", ".s": "asm", ".inc": "asm", ".sql": "sql", ".js": "javascript",
        ".r": "r", ".m": "matlab", ".json": "json", ".xml": "xml", ".sh": "bash"}
ROOT_PAGES = {"content.html", "content.md", "links.html", "links.md", "content.json"}
MAX_CODE = 200_000  # bytes; bigger text files are left out
VIDEO_AUDIO = {".mp4", ".m4v", ".mov", ".webm", ".avi", ".mkv", ".wmv", ".mp3", ".m4a", ".wav"}
REDIRECT = re.compile(rb'<meta http-equiv="refresh"', re.I)
DATA_IMG = re.compile(r"<img\b[^>]*\bsrc=[\"']data:[^>]*>", re.I)
IMG = re.compile(r"<img\b[^>]*>", re.I)
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
FOOTER = re.compile(r"\n(---\n\n)?Archived from Brightspace\b[^\n]*\s*$")


@dataclass
class Part:
    title: str  # where it came from, e.g. "Lectures › Unit I › 02-FA.pdf"
    path: Path | None = None  # a file to upload or merge
    text: str | None = None  # Markdown


@dataclass
class Source:
    name: str  # file name in the pack, without its number
    kind: str  # "md" (text parts), "file" (one file copied), "pdf" (files merged into one PDF)
    parts: list[Part]
    group: tuple[str, ...] = ()  # module path, for merging; () for the course-wide documents

    @property
    def size(self) -> int:
        return sum(p.path.stat().st_size for p in self.parts if p.path) + sum(len(p.text or "") for p in self.parts)


@dataclass
class Pack:
    course: str
    folder: Path
    sources: list[Source] = field(default_factory=list)
    left_out: list[tuple[str, str]] = field(default_factory=list)  # (what, why)
    links: list[tuple[str, str]] = field(default_factory=list)  # (title, url), to add to the notebook by hand
    notes: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)  # what was done to fit the limit
    written: list[tuple[Path, Source]] = field(default_factory=list)  # files in the pack folder, and what each holds


# ---------- reading the archive ----------

def _page_markdown(html_path: Path) -> str:
    """A generated or content page as Markdown: its `.md` copy when there is one, else converted.
    Images become a short note (NotebookLM doesn't see images inside Markdown)."""
    md_path = html_path.with_suffix(".md")
    if md_path.exists():
        text = md_path.read_text(encoding="utf-8", errors="replace")
    else:
        html = html_path.read_text(encoding="utf-8", errors="replace")
        text = to_markdown(DATA_IMG.sub("[image]", html))
    text = FOOTER.sub("", text)
    text = MD_IMAGE.sub(lambda m: f"[image{': ' + m[1] if m[1] else ''}]", text)
    lines = text.strip().splitlines()
    if lines and " › " in lines[0] and not lines[0].startswith("#"):  # the breadcrumb
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    if lines and lines[0].startswith("# "):  # the page's title: it's merged under a heading of its own
        lines = lines[1:]
    return "\n".join(lines).strip()


def _demote(md: str, levels: int = 1) -> str:
    """Push Markdown headings down so a page fits under the heading it's merged under."""
    out, fenced = [], False
    for line in md.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        out.append("#" * levels + line if not fenced and re.match(r"#{1,5} ", line) else line)
    return "\n".join(out)


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _label(folder: str) -> str:
    """"02 Unit I -- Finite Automata" -> "Unit I -- Finite Automata"."""
    return re.sub(r"^\d{2} ", "", folder)


def _overview(course: Path, pack: Pack) -> Source | None:
    parts = []
    for rel, title in [("course info/course.html", "Course info"), ("content/content.html", "Course outline"),
                       ("announcements/announcements.html", "Announcements")]:
        path = course / rel
        if path.exists():
            parts.append(Part(title, text=_demote(_page_markdown(path))))
        elif rel.startswith("announcements"):
            pack.notes.append("No announcements in the archive.")
    return Source("Course overview.md", "md", parts) if parts else None


def _assignments(course: Path, pack: Pack) -> tuple[Source | None, list[Source]]:
    """Instructions, rubrics, and feedback as one document; the files instructors attached, as sources.
    Your own submissions and returned feedback files are left out."""
    folder = course / "assignments"
    if not folder.is_dir():
        pack.notes.append("No assignments in the archive.")
        return None, []
    data = _json(folder / "assignments.json") or []
    order = {safe_name(e["folder"]["Name"]): i for i, e in enumerate(data) if isinstance(e, dict) and "folder" in e}
    dirs = sorted((d for d in folder.iterdir() if d.is_dir()), key=lambda d: (order.get(d.name, 1e9), d.name.lower()))
    parts, files = [], []
    for d in dirs:
        if (d / "assignment.html").exists():
            parts.append(Part(d.name, text=_demote(_page_markdown(d / "assignment.html"))))
        for f in sorted((d / "attachments").glob("*")) if (d / "attachments").is_dir() else []:
            title = f"Assignments › {d.name} › {f.name}"
            if f.suffix.lower() in CODE and f.stat().st_size <= MAX_CODE:
                parts.append(Part(title, text=_code(f)))
            else:
                files.extend(_file_sources(f, ("Assignment files",), title, pack))
        for kind in ("submissions", "feedback"):
            if (d / kind).is_dir() and any((d / kind).rglob("*")):
                pack.left_out.append((f"Assignments › {d.name} › {kind}", "your own work and returned files"))
    return (Source("Assignments.md", "md", parts) if parts else None), files


def _discussions(course: Path, pack: Pack) -> Source | None:
    folder = course / "discussions"
    if not folder.is_dir():
        return None
    parts = [Part(f"{p.parent.name} › {p.stem}", text=_demote(_page_markdown(p)))
             for p in sorted(folder.glob("*/*.html"), key=lambda p: (p.parent.name.lower(), p.name.lower()))]
    parts = [p for p in parts if "No posts." not in p.text]
    return Source("Discussions.md", "md", parts) if parts else None


def _practice(course: Path, pack: Pack) -> Source | None:
    """Every quiz's unique questions with the right answers, from all of its saved attempts."""
    folder = course / "quizzes"
    if not folder.is_dir():
        pack.notes.append("No quizzes in the archive.")
        return None
    data = _json(folder / "quizzes.json") or []
    names = [safe_name(q.get("Name") or "Untitled") for q in sorted(data, key=lambda q: q.get("SortOrder") or 0)]
    dirs = [folder / n for n in dict.fromkeys(names) if (folder / n / "_originals").is_dir()]
    dirs += sorted(d for d in folder.iterdir() if (d / "_originals").is_dir() and d not in dirs)
    parts, unseen = [], []
    for d in dirs:
        best: dict[str, tuple[int, int, Card]] = {}  # key -> (answer shown, attempt number, card)
        attempts = sorted(d.glob("_originals/attempt *.html"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))
        for p in attempts:
            a = parse_attempt(0, 0, int(re.sub(r"\D", "", p.stem) or 0), p.read_bytes())
            for q in a.questions:
                card = study_card(q)
                rank = (card.answer is not None, a.number)
                if card.key not in best or rank > best[card.key][:2]:
                    best[card.key] = (*rank, card)
        if not best:
            unseen.append(d.name)
            continue
        cards = list(best.values())  # in the order first seen
        body = f"{len(cards)} question{'s' * (len(cards) != 1)} from {len(attempts)} attempt{'s' * (len(attempts) != 1)}.\n\n"
        body += "\n\n".join(_card_markdown(i, c) for i, (_, _, c) in enumerate(cards, 1))
        parts.append(Part(d.name, text=body))
    if unseen:
        pack.notes.append(f"No questions could be seen for: {', '.join(unseen)} (score only, or never submitted).")
    return Source("Practice questions.md", "md", parts) if parts else None


def _inline_md(html: str) -> str:
    return " ".join(to_markdown(IMG.sub("[image]", html)).split())


def _card_markdown(n: int, card: Card) -> str:
    """A question as Markdown: the question, its choices, the right answer, and any feedback."""
    prompt = _demote(to_markdown(IMG.sub("[image]", card.prompt)).strip(), 3)
    out = f"### Question {n}\n\n{prompt}\n"
    choices = [_inline_md(c) for c in card.choices]
    if choices:
        if card.lettered and not all(re.match(r"^[A-Za-z][).]\s", c) for c in choices):  # unless already lettered
            choices = [f"{LETTERS[i % 26]}. {c}" for i, c in enumerate(choices)]
        out += "\n" + "\n".join(f"- {c}" for c in choices) + "\n"
    if card.answer is None:
        out += "\n**Correct answer:** not shown\n"
    elif card.lettered or len(card.answer) == 1:
        out += f"\n**Correct answer:** {', '.join(_inline_md(a) for a in card.answer)}\n"
    else:  # typed answers in several blanks, matching pairs
        out += "\n**Correct answer:**\n" + "".join(f"\n- {_matched(_inline_md(a))}" for a in card.answer) + "\n"
    if card.feedback:
        out += f"\n**Feedback:** {_inline_md(card.feedback)}\n"
    return out


def _matched(answer: str) -> str:
    """A matching answer, "__2__ item" as Brightspace shows it, as "item → 2"."""
    m = re.match(r"^\\_\\_\s*(.+?)\s*\\_\\_\s*(.+)$", answer)
    return f"{m[2]} → {m[1]}" if m else answer


def _code(path: Path) -> str:
    """A text file as Markdown: Markdown as it is, anything else in a code block."""
    body = path.read_text(encoding="utf-8", errors="replace").rstrip()
    return body if path.suffix.lower() == ".md" else f"```{CODE[path.suffix.lower()]}\n{body}\n```"


def _file_sources(path: Path, group: tuple[str, ...], title: str, pack: Pack) -> list[Source]:
    """A downloaded file as a source, or why it's left out."""
    ext = path.suffix.lower()
    if ext in NATIVE or ext in IMAGES:
        return [Source(path.name, "file", [Part(title, path)], group)]
    if ext in VIDEO_AUDIO:
        pack.left_out.append((title, "video or audio"))
    elif ext in CODE:
        pack.left_out.append((title, "text file over 200 KB"))
    else:
        pack.left_out.append((title, f"{ext or 'no extension'} files can't be a NotebookLM source"))
    return []


def _module_order(course: Path) -> dict[tuple[str, ...], list[str]]:
    """Instructor order of the topics in each module, as file names on disk."""
    toc = _json(course / "content" / "content.json")
    order = {}
    if not toc:
        return order
    for path, m in walk_toc(toc["Modules"]):
        names = []
        for t in sorted(m["Topics"], key=lambda t: t["SortOrder"]):
            if t["TypeIdentifier"] == "File" and t.get("Url"):
                names.append(safe_name(_topic_file_name(t)).lower())
            names.append(safe_name(t.get("Title") or "").lower())
        order[tuple(safe_name(p) for p in path)] = names
    return order


def _content(course: Path, pack: Pack) -> list[Source]:
    """Module by module in the instructor's order: files as sources, pages and code as one text
    document per top-level module."""
    root = course / "content"
    if not root.is_dir():
        pack.notes.append("No course content in the archive.")
        return []
    order = _module_order(course)
    sources: list[Source] = []
    text: dict[str, Source] = {}  # top-level module -> its text document

    def add_text(top: str, part: Part):
        if top not in text:
            text[top] = Source(f"{_label(top)} (pages).md", "md", [], (top,))
            sources.append(text[top])
        text[top].parts.append(part)

    def walk(folder: Path, rel: tuple[str, ...]):
        names = order.get(rel, [])
        rank = lambda p: (names.index(p.name.lower()) if p.name.lower() in names else len(names), p.name.lower())
        entries = sorted(folder.iterdir(), key=lambda p: (p.is_dir(), rank(p)))
        for p in entries:
            if p.is_dir():
                walk(p, (*rel, p.name))
                continue
            title = " › ".join([*(_label(r) for r in rel), p.name])
            ext = p.suffix.lower()
            top = rel[0] if rel else "Content"
            if ext == ".md" and p.with_suffix(".html").exists():
                continue  # the Markdown copy of a page, read with the page
            if not rel and p.name.lower() in ROOT_PAGES:
                continue  # the outline is in the course overview; links go in the manifest
            if ext == ".url":
                url = re.search(r"^URL=(.+)$", p.read_text(encoding="utf-8", errors="replace"), re.M)
                pack.links.append((title.removesuffix(".url"), url[1].strip() if url else ""))
            elif ext in {".html", ".htm"}:
                head = p.read_bytes()[:600]
                if REDIRECT.search(head):
                    continue  # a shortcut to another archived item (assignment, quiz, ...), already included
                md = _page_markdown(p)
                if md:
                    add_text(top, Part(title.removesuffix(p.suffix), text=_demote(md)))
            elif ext in CODE and p.stat().st_size <= MAX_CODE:
                add_text(top, Part(title, text=_code(p)))
            else:
                sources.extend(_file_sources(p, rel, title, pack))

    walk(root, ())
    # each module's text document goes first in its module
    for top, doc in text.items():
        sources.remove(doc)
        first = next((i for i, s in enumerate(sources) if s.group[:1] == (top,)), len(sources))
        sources.insert(first, doc)
    return sources


def _linked_files(course: Path, pack: Pack) -> list[Source]:
    """Documents linked from pages (not embedded assets or page originals)."""
    root = course / "_course-files"
    if not root.is_dir():
        return []
    sources = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).parts
        if p.is_dir() or rel[0] in ("_assets", "_originals"):
            continue
        if p.suffix.lower() in CODE:
            continue
        sources.extend(_file_sources(p, ("Linked files",), "Linked files › " + "/".join(rel), pack))
    return sources


# ---------- fitting the limit ----------

def _dedupe(sources: list[Source], pack: Pack) -> list[Source]:
    seen: dict[str, str] = {}
    out = []
    for s in sources:
        if s.kind == "file":
            digest = hashlib.sha1(s.parts[0].path.read_bytes()).hexdigest()
            if digest in seen:
                pack.left_out.append((s.parts[0].title, f"same file as {seen[digest]}"))
                continue
            seen[digest] = s.parts[0].title
        out.append(s)
    return out


def _pdfable(s: Source) -> bool:
    return s.kind in ("file", "pdf") and all(p.path.suffix.lower() == ".pdf" or p.path.suffix.lower() in IMAGES for p in s.parts)


def _pdf_groups(sources: list[Source], depth: int | None) -> dict[tuple[str, ...], list[int]]:
    """Positions of the PDFs and images of each module (`depth` folders deep; None for the whole
    module path) that has more than one."""
    groups: dict[tuple[str, ...], list[int]] = {}
    for i, s in enumerate(sources):
        if s.group and _pdfable(s):
            groups.setdefault(s.group if depth is None else s.group[:depth], []).append(i)
    return {key: idx for key, idx in groups.items() if len(idx) > 1}


def _merge_group(sources: list[Source], key: tuple[str, ...], idx: list[int]) -> list[Source]:
    """Merge one module's PDFs and images into one PDF at the place of its first one, in parts if
    they'd be over NotebookLM's size limit together."""
    chunks, size = [[]], 0
    for i in idx:
        if chunks[-1] and size + sources[i].size > MAX_PDF:
            chunks.append([])
            size = 0
        chunks[-1].append(i)
        size += sources[i].size
    merged = []
    for n, chunk in enumerate(chunks, 1):
        name = " - ".join(_label(k) for k in key) + (f" (part {n})" if len(chunks) > 1 else "") + ".pdf"
        merged.append(Source(name, "pdf", [p for i in chunk for p in sources[i].parts], key))
    out = []
    for i, s in enumerate(sources):
        if i == idx[0]:
            out.extend(merged)
        elif i not in idx:
            out.append(s)
    return out


def _office_text(path: Path) -> str:
    """Slide text and speaker notes of a .pptx, or paragraphs and tables of a .docx, as Markdown."""
    with zipfile.ZipFile(path) as z:
        if path.suffix.lower() == ".pptx":
            slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=lambda n: int(re.sub(r"\D", "", n)))
            out = []
            for i, name in enumerate(slides, 1):
                text = _xml_paragraphs(z.read(name), "a")
                number = re.sub(r"\D", "", name)
                notes_name = f"ppt/notesSlides/notesSlide{number}.xml"
                notes = _xml_paragraphs(z.read(notes_name), "a") if notes_name in z.namelist() else []
                notes = [n for n in notes if not n.isdigit()]  # the slide number placeholder
                out.append(f"#### Slide {i}\n\n" + "\n".join(text) + (f"\n\nNotes: {' '.join(notes)}" if notes else ""))
            return "\n\n".join(out)
        return "\n\n".join(_xml_paragraphs(z.read("word/document.xml"), "w"))


def _xml_paragraphs(xml: bytes, ns: str) -> list[str]:
    """Text of each paragraph (<a:p> / <w:p>) in an Office XML part."""
    paragraphs = re.findall(rb"<%s:p[ >].*?</%s:p>" % (ns.encode(), ns.encode()), xml, re.S)
    out = []
    for p in paragraphs:
        runs = re.findall(rb"<%s:t(?: [^>]*)?>(.*?)</%s:t>" % (ns.encode(), ns.encode()), p, re.S)
        text = "".join(r.decode("utf-8", "replace") for r in runs)
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'")
        if text.strip():
            out.append(text.strip())
    return out


def _is_office(s: Source) -> bool:
    return s.kind == "file" and bool(s.group) and s.parts[0].path.suffix.lower() in OFFICE_TEXT


def _office_to_text(sources: list[Source], office: Source, pack: Pack) -> list[Source]:
    """Move one slide deck or Word document into its top-level module's text document (made if needed,
    where the file was). A file that can't be read stays as it is."""
    top = office.group[0]
    try:
        body = _office_text(office.parts[0].path)
    except (zipfile.BadZipFile, KeyError, OSError) as e:
        pack.notes.append(f"Couldn't read {office.parts[0].title} as text ({type(e).__name__}); kept as a file.")
        return sources
    doc = next((s for s in sources if s.kind == "md" and s.group == (top,)), None)
    out = [s for s in sources if s is not office]
    if doc is None:
        doc = Source(f"{_label(top)} (pages).md", "md", [], (top,))
        out.insert(sources.index(office), doc)
    doc.parts.append(Part(office.parts[0].title, text=body))
    return out


def fit(sources: list[Source], limit: int, pack: Pack) -> list[Source]:
    """Merge until the pack fits, in the order that loses the least, one module at a time (the one
    with the most files first), so as much as possible stays as it was; list whatever still doesn't fit."""
    for depth, label in ((None, "module"), (1, "top-level module")):
        before, done, merged = len(sources), set(), 0
        while len(sources) > limit:
            groups = {k: v for k, v in _pdf_groups(sources, depth).items() if k not in done}
            if not groups:
                break
            key = max(groups, key=lambda k: len(groups[k]))
            done.add(key)
            after = _merge_group(sources, key, groups[key])
            if len(after) < len(sources):
                sources, merged = after, merged + 1
        if merged:
            pack.steps.append(f"merged the PDFs of {plural(merged, label)}: {before} → {len(sources)} sources")

    # one file at a time, from the top-level module with the most; the first one in a module without a
    # text document saves nothing, every one after it saves a source
    before, tried, converted = len(sources), set(), 0
    while len(sources) > limit:
        office = [s for s in sources if _is_office(s) and id(s) not in tried]
        if not office:
            break
        counts: dict[str, int] = {}
        for s in office:
            counts[s.group[0]] = counts.get(s.group[0], 0) + 1
        top = max(counts, key=counts.get)
        target = next(s for s in office if s.group[0] == top)
        tried.add(id(target))
        after = _office_to_text(sources, target, pack)
        converted += after is not sources
        sources = after
    if len(sources) < before:
        pack.steps.append(f"turned {plural(converted, 'slide/Word file')} "
                          f"into text (their images are lost): {before} → {len(sources)} sources")

    while len(sources) > limit:  # largest content file first; the course-wide documents always stay
        candidates = [s for s in sources if s.group]
        if not candidates:
            break
        biggest = max(candidates, key=lambda s: s.size)
        sources.remove(biggest)
        for p in biggest.parts:
            pack.left_out.append((p.title, "over the source limit"))
    return sources


# ---------- writing ----------

def _write_md(source: Source, course_name: str, dest: Path) -> list[Path]:
    """A Markdown source, split into parts if it's over NotebookLM's word limit."""
    title = source.name.removesuffix(".md")
    chunks, words = [[]], 0
    for part in source.parts:
        n = len(part.text.split())
        if chunks[-1] and words + n > MAX_WORDS:
            chunks.append([])
            words = 0
        chunks[-1].append(part)
        words += n
    written = []
    for i, chunk in enumerate(chunks, 1):
        suffix = f" (part {i})" if len(chunks) > 1 else ""
        body = f"# {title}{suffix}\n\n{course_name}\n\n" + "\n\n".join(f"## {p.title}\n\n{p.text.strip()}" for p in chunk) + "\n"
        path = dest if len(chunks) == 1 else dest.with_name(f"{dest.stem}{suffix}.md")
        path.write_text(body, encoding="utf-8")
        written.append(path)
    return written


def _write_pdf(source: Source, dest: Path, pack: Pack) -> None:
    from PIL import Image
    from pypdf import PdfWriter
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # it warns about every slightly malformed PDF
    writer = PdfWriter()
    for part in source.parts:
        try:
            if part.path.suffix.lower() in IMAGES:
                buffer = io.BytesIO()
                Image.open(part.path).convert("RGB").save(buffer, "PDF")
                buffer.seek(0)
                writer.append(buffer, outline_item=part.title)
            else:
                writer.append(str(part.path), outline_item=part.title)
        except Exception as e:  # an encrypted or broken file shouldn't cost the rest of the module
            pack.left_out.append((part.title, f"couldn't be merged ({type(e).__name__})"))
    with dest.open("wb") as f:
        writer.write(f)


def _manifest(pack: Pack, limit: int) -> str:
    now = datetime.now().astimezone()
    lines = [f"# Study pack: {pack.course}", "",
             f"Built {now:%a} {now.day} {now:%b %Y}, {now.hour % 12 or 12}:{now:%M} {'AM' if now.hour < 12 else 'PM'} "
             f"from the archive. {len(pack.written)} sources (limit {limit}). Upload every file in this folder except this one.", ""]
    if pack.steps:
        lines += ["To fit the limit:", *(f"- {s}" for s in pack.steps), ""]
    lines += ["## Sources", ""]
    for path, source in pack.written:
        lines.append(f"- **{path.name}**")
        if source.kind != "file" and len(source.parts) > 1:
            lines += [f"  - {p.title}" for p in source.parts]
    if pack.notes:
        lines += ["", "## Notes", "", *(f"- {n}" for n in pack.notes)]
    if pack.links:
        lines += ["", "## Web links", "", "Add any of these to the notebook as a website source if they matter:", "",
                  *(f"- {t}: {u}" for t, u in pack.links)]
    if pack.left_out:
        lines += ["", "## Left out", "", *(f"- {what}: {why}" for what, why in pack.left_out)]
    return "\n".join(lines) + "\n"


def build_pack(course: Path, packs_root: Path, limit: int = LIMIT, status: Callable[[str], None] = lambda _: None) -> Pack:
    """Build (or rebuild) one course's study pack from its archive folder. `status` hears what it's
    working on (merging large PDFs can take minutes)."""
    pack = Pack(course.name, packs_root / course.name)
    overview = _overview(course, pack)
    practice = _practice(course, pack)
    assignments, assignment_files = _assignments(course, pack)
    discussions = _discussions(course, pack)
    documents = [s for s in (overview, practice, assignments, discussions) if s]
    content = _dedupe(_content(course, pack) + assignment_files + _linked_files(course, pack), pack)
    pack.sources = documents + fit(content, limit - len(documents), pack)

    # write into a fresh folder, then swap it in, so a failed build never leaves half a pack
    building = packs_root / f".{course.name}.building"
    if building.exists():
        shutil.rmtree(building)
    building.mkdir(parents=True)
    written = []
    for n, source in enumerate(pack.sources, 1):
        dest = building / safe_name(f"{n:02d} {source.name}")
        status(f"{n}/{len(pack.sources)} {source.name}")
        if source.kind == "md":
            written += [(p, source) for p in _write_md(source, course.name, dest)]
            continue
        if source.kind == "pdf":
            _write_pdf(source, dest, pack)
            if dest.stat().st_size > 200 * 1024 * 1024:
                pack.notes.append(f"{dest.name} came out over 200 MB; NotebookLM may refuse it.")
        else:
            shutil.copyfile(source.parts[0].path, dest)
        written.append((dest, source))
    pack.written = [(pack.folder / p.name, source) for p, source in written]
    (building / MANIFEST).write_text(_manifest(pack, limit), encoding="utf-8")
    if pack.folder.exists():
        if not (pack.folder / MANIFEST).exists() and any(pack.folder.iterdir()):
            raise RuntimeError(f"{pack.folder} exists and isn't a study pack; not replacing it")
        shutil.rmtree(pack.folder)
    building.rename(pack.folder)
    return pack


# ---------- on its own ----------

def course_folders(archive: Path) -> list[Path]:
    return sorted(d for d in archive.iterdir()
                  if d.is_dir() and d.name != PACKS_DIR and (d / "course info").is_dir())


def main() -> None:
    import questionary
    from prompts import DEFAULT_OUTPUT
    from ui import PROMPT_STYLE, console, ok, warn

    archive = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else DEFAULT_OUTPUT
    if not archive.is_dir():
        warn(f"No archive at {archive}")
        sys.exit(1)
    courses = course_folders(archive)
    picked = questionary.checkbox(
        "Build a study pack for:",
        choices=[questionary.Choice(c.name, c) for c in courses],
        instruction="(space toggle · enter confirm)",
        style=PROMPT_STYLE,
    ).ask()
    if not picked:
        warn("Nothing to build.")
        return
    for course in picked:
        with console.status(f"Building {course.name}...") as spinner:
            update = lambda text, name=course.name: spinner.update(f"Building {name}... [dim]{text}[/]")
            pack = build_pack(course, archive / PACKS_DIR, status=update)
        ok(f"{course.name}: {len(pack.written)} sources [dim]({pack.folder})[/]")


if __name__ == "__main__":
    main()
