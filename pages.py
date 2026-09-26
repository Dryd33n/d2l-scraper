"""Generated HTML pages: readable views of the crawled JSON for course info, announcements,
assignments, discussions, quizzes, and grades.

Each page is a single file with the shared style inlined. Rich text from Brightspace is kept as HTML;
its site-relative links and images point back at Brightspace until phase 3 downloads them.
"""

import html
import os
import re
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from auth import BASE_URL
from crawl import COURSE_INFO, LABELS, CategoryResult, CourseCrawl
from ui import format_size

esc = html.escape


@dataclass
class Context:
    """What a page needs while rendering: where it's written and where the downloaded files went."""
    crawl: CourseCrawl
    dest: Path
    course_page: Path | None
    files: dict[str, Path]  # API path after the course id -> local file, e.g. "news/12/attachments/34"
    people: dict[str, str]  # user id -> display name, from the classlist when it was crawled

    def href(self, target: Path) -> str:
        return quote(os.path.relpath(target, self.dest.parent).replace(os.sep, "/"))

    def file(self, tail: str, name: str | None = None, size: int | None = None) -> str:
        """A link to a downloaded file, or its name with a note when it isn't on disk."""
        path = self.files.get(tail)
        label = esc(name or (path.name if path else tail))
        extra = f' <span class="muted">{format_size(size)}</span>' if size else ""
        if path is None:
            return f'{label}{extra} <span class="muted">(not in archive)</span>'
        if not path.exists():
            return f'{label}{extra} <span class="muted">(not downloaded)</span>'
        return f'<a href="{self.href(path)}">{label}</a>{extra}'


@dataclass
class Page:
    path: tuple[str, ...]  # folders within the category folder, like RemoteFile.path
    name: str
    title: str
    render: Callable[[Context], str]  # returns the page body
    crumbs: tuple[str, ...] = ()  # shown between the course name and the title, e.g. ("Discussions", forum)


def api_tail(url: str, course_id: int) -> str:
    """"/d2l/api/le/1.99/507204/news/12/attachments/34" -> "news/12/attachments/34" (the whole URL if it has no course id)."""
    _, found, tail = url.partition(f"/{course_id}/")
    return tail if found else url


# ---------- formatting helpers ----------

def when(iso: str | None) -> str:
    """An API timestamp in local time, e.g. "Sun 15 Dec 2024, 1:01 PM"."""
    if not iso:
        return ""
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    text = f"{t:%a} {t.day} {t:%b %Y}, {t.hour % 12 or 12}:{t:%M} {'AM' if t.hour < 12 else 'PM'}"
    return f'<time datetime="{esc(iso)}">{text}</time>'


def num(value) -> str:
    return "" if value is None else f"{value:g}"


def rich(value) -> str:
    """HTML from a D2L RichText ({"Text", "Html"} or {"Content", "Type"}), with site-relative
    links made absolute so they still work outside Brightspace."""
    if isinstance(value, dict):
        if "Content" in value:  # grade category descriptions: Type 2 is HTML, 1 is plain text
            value = value["Content"] if value.get("Type") == 2 else _plain(value["Content"])
        else:
            value = value.get("Html") or _plain(value.get("Text"))
    return re.sub(r"""(\b(?:src|href)\s*=\s*["'])/(?!/)""", rf"\1{BASE_URL}/", value or "")


def _plain(text: str | None) -> str:
    return esc(text or "").replace("\r\n", "\n").replace("\n", "<br>\n")


def _has_text(value) -> bool:
    """Whether rich text has anything visible (D2L often stores "<p></p>" or whitespace)."""
    body = rich(value)
    return bool(re.search(r"<(img|iframe|video|table)\b", body) or re.sub(r"<[^>]+>|&nbsp;|\s", "", body))


def details(rows: list[tuple[str, str]]) -> str:
    rows = [(k, v) for k, v in rows if v]
    if not rows:
        return ""
    return '<dl class="details">' + "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"


def file_list(items: list[str]) -> str:
    return '<ul class="files">' + "".join(f"<li>{i}</li>" for i in items) + "</ul>" if items else ""


def section(heading: str, body: str) -> str:
    return f"<section><h2>{esc(heading)}</h2>\n{body}\n</section>\n" if body else ""


def note(text: str) -> str:
    return f'<p class="note">{text}</p>'


STYLE = """
:root { color-scheme: light dark; --fg: #1f2328; --muted: #59636e; --line: #d1d9e0; --soft: #f6f8fa;
  --accent: #0969da; --picked: #dafbe1; --warn: #fff8c5; }
@media (prefers-color-scheme: dark) { :root { --fg: #e6edf3; --muted: #9198a1; --line: #3d444d;
  --soft: #151b23; --accent: #4493f8; --picked: #1b3a26; --warn: #3b2e00; } }
* { box-sizing: border-box; }
body { font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; color: var(--fg); background: Canvas;
  max-width: 54rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
a { color: var(--accent); }
img, video, iframe { max-width: 100%; }
img { height: auto; }
h1 { font-size: 1.75rem; line-height: 1.25; margin: .25rem 0 1rem; }
h2 { font-size: 1.3rem; margin: 2rem 0 .75rem; padding-bottom: .3rem; border-bottom: 1px solid var(--line); }
h3 { font-size: 1.05rem; margin: 1.25rem 0 .5rem; }
nav.crumbs, .muted, footer { color: var(--muted); font-size: .9rem; }
nav.crumbs a { color: inherit; }
footer { margin-top: 3rem; border-top: 1px solid var(--line); padding-top: .75rem; }
dl.details { display: grid; grid-template-columns: max-content 1fr; gap: .25rem 1rem; margin: 0 0 1rem; }
dl.details dt { color: var(--muted); }
dl.details dd { margin: 0; }
article { border: 1px solid var(--line); border-radius: 8px; padding: .75rem 1rem; margin: 1rem 0; }
article > header { margin-bottom: .5rem; }
article > header h2, article > header h3 { margin: 0; border: 0; padding: 0; }
.body { overflow-wrap: anywhere; }
.body > :first-child { margin-top: 0; }
.body > :last-child { margin-bottom: 0; }
.replies { border-left: 3px solid var(--line); margin: .75rem 0 0 .25rem; padding-left: .75rem; }
.replies article { border: 0; border-radius: 0; padding: .25rem 0; margin: .75rem 0; }
.tag { display: inline-block; font-size: .75rem; padding: 0 .4rem; border: 1px solid var(--line); border-radius: 1rem;
  color: var(--muted); vertical-align: middle; }
.note { background: var(--warn); border-radius: 6px; padding: .5rem .75rem; }
ul.files { padding-left: 1.25rem; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .95rem; margin: .5rem 0 1rem; }
th, td { border: 1px solid var(--line); padding: .4rem .6rem; text-align: left; vertical-align: top; }
th { background: var(--soft); }
td p { margin: 0 0 .25rem; }
td.num, th.num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
td.picked { background: var(--picked); outline: 2px solid var(--accent); outline-offset: -2px; }
tr.group td { background: var(--soft); font-weight: 600; }
tr.comment td { border-top: 0; color: var(--muted); }
.banner { width: 100%; max-height: 14rem; object-fit: cover; border-radius: 8px; }
"""


def document(ctx: Context, page: Page, body: str) -> str:
    course = esc(ctx.crawl.course.name)
    if ctx.course_page and ctx.course_page != ctx.dest:
        course = f'<a href="{ctx.href(ctx.course_page)}">{course}</a>'
    crumbs = " › ".join([course, *(esc(c) for c in page.crumbs)])
    saved = datetime.now().astimezone().isoformat(timespec="seconds")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(page.title)} · {esc(ctx.crawl.course.short_name)}</title>
<style>{STYLE}</style>
</head>
<body>
<nav class="crumbs">{crumbs}</nav>
<h1>{esc(page.title)}</h1>
{body}
<footer>Archived from Brightspace {when(saved)}</footer>
</body>
</html>
"""


# ---------- course info ----------

def _course(data: dict, ctx: Context) -> str:
    org = data["enrollment"].get("OrgUnit", {})
    access = data["enrollment"].get("Access", {})
    image = ctx.files.get("image")
    image = image if image and image.exists() else None
    out = f'<img class="banner" src="{ctx.href(image)}" alt="">\n' if image else ""
    home = org.get("HomeUrl")
    out += details([
        ("Code", esc(org.get("Code") or "")),
        ("Starts", when(access.get("StartDate"))),
        ("Ends", when(access.get("EndDate"))),
        ("Role", esc(access.get("ClasslistRoleName") or "")),
        ("Last visited", when(access.get("LastAccessed"))),
        ("Brightspace", f'<a href="{esc(home)}">{esc(home)}</a>' if home else ""),
    ])
    overview = data.get("overview")
    if overview:
        body = f'<div class="body">{rich(overview.get("Description"))}</div>' if _has_text(overview.get("Description")) else ""
        if overview.get("HasAttachment"):
            body += file_list([ctx.file("overview/attachment")])
        out += section("Overview", body)
    return out


# ---------- announcements ----------

def _announcements(news: list[dict], ctx: Context) -> str:
    if not news:
        return '<p class="muted">No announcements.</p>'
    items = sorted(news, key=lambda n: n.get("StartDate") or n.get("CreatedDate") or "", reverse=True)
    out = []
    for n in items:
        meta = [when(n.get("StartDate") or n.get("CreatedDate"))]
        if n.get("IsAuthorInfoShown") and (author := ctx.people.get(str(n.get("CreatedBy")))):
            meta.append(esc(author))
        if n.get("IsPinned"):
            meta.append('<span class="tag">Pinned</span>')
        files = [ctx.file(f"news/{n['Id']}/attachments/{a['FileId']}", a["FileName"], a.get("Size"))
                 for a in n.get("Attachments", [])]
        out.append(
            f'<article id="announcement-{n["Id"]}">\n<header><h2>{esc(n.get("Title") or "Untitled")}</h2>'
            f'<div class="muted">{" · ".join(m for m in meta if m)}</div></header>\n'
            f'<div class="body">{rich(n.get("Body"))}</div>\n{file_list(files)}</article>'
        )
    return "\n".join(out)


# ---------- assignments ----------

def _rubric(rubric: dict, assessment: dict | None) -> str:
    """A rubric as one table per criteria group; with an assessment, the chosen levels are highlighted
    and each criterion's score and feedback get their own columns."""
    outcomes = {o.get("CriterionId"): o for o in (assessment or {}).get("CriteriaOutcome") or []}
    out = f"<h3>{esc(rubric.get('Name') or 'Rubric')}</h3>\n"
    if _has_text(rubric.get("Description")):
        out += f'<div class="body">{rich(rubric["Description"])}</div>\n'
    for group in rubric.get("CriteriaGroups", []):
        # instructors often leave spare levels with no description and 0 points; they'd only add empty columns
        used = {c.get("LevelId") for cr in group.get("Criteria", []) for c in cr.get("Cells", [])
                if _has_text(c.get("Description")) or c.get("Points")}
        used |= {o.get("LevelId") for o in outcomes.values()}
        levels = [lv for lv in group.get("Levels", []) if lv.get("Id") in used or lv.get("Points")]
        if rubric.get("ReverseLevelDisplayOrder"):
            levels.reverse()
        head = "".join(
            f"<th>{esc(lv.get('Name') or '')}" + (f' <span class="muted">{num(lv["Points"])} pts</span>' if lv.get("Points") is not None else "") + "</th>"
            for lv in levels
        )
        if assessment:
            head += "<th>Score</th><th>Feedback</th>"
        rows = []
        for criterion in group.get("Criteria", []):
            cells = {c.get("LevelId"): c for c in criterion.get("Cells", [])}
            outcome = outcomes.get(criterion.get("Id"), {})
            name = re.sub(r"\s*\n\s*", "\n", (criterion.get("Name") or "").strip())
            row = f"<th>{_plain(name)}</th>"
            for lv in levels:
                cell = cells.get(lv.get("Id"), {})
                picked = ' class="picked"' if outcome and outcome.get("LevelId") == lv.get("Id") else ""
                show_points = lv.get("Points") is None and cell.get("Points") is not None and (cell["Points"] or _has_text(cell.get("Description")))
                points = f'<div class="muted">{num(cell["Points"])} pts</div>' if show_points else ""
                row += f"<td{picked}>{rich(cell.get('Description'))}{points}</td>"
            if assessment:
                row += f'<td class="num">{num(outcome.get("Score"))}</td><td>{rich(outcome.get("Feedback"))}</td>'
            rows.append(f"<tr>{row}</tr>")
        caption = f"<caption>{esc(group['Name'])}</caption>" if len(rubric.get("CriteriaGroups", [])) > 1 and group.get("Name") else ""
        out += f'<div class="table-wrap"><table>{caption}<thead><tr><th>Criterion</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>\n'
    if assessment:
        level = (assessment.get("OverallLevel") or {}).get("Name")
        out += details([
            ("Total", esc(num(assessment.get("OverallScore")))),
            ("Overall level", esc(level or "")),
        ])
        if _has_text(assessment.get("OverallFeedback")):
            out += f'<div class="body">{rich(assessment["OverallFeedback"])}</div>\n'
    return out


def _assignment(entry: dict, ctx: Context) -> str:
    folder, mine = entry["folder"], entry["mysubmissions"]
    fid = folder["Id"]
    out_of = (folder.get("Assessment") or {}).get("ScoreDenominator")
    availability = folder.get("Availability") or {}
    out = details([
        ("Due", when(folder.get("DueDate"))),
        ("Available from", when(availability.get("StartDate"))),
        ("Available until", when(availability.get("EndDate"))),
        ("Out of", esc(num(out_of))),
    ])

    if _has_text(folder.get("CustomInstructions")):
        out += section("Instructions", f'<div class="body">{rich(folder["CustomInstructions"])}</div>')

    files = [ctx.file(f"dropbox/folders/{fid}/attachments/{a['FileId']}", a["FileName"], a.get("Size"))
             for a in folder.get("Attachments", [])]
    files += [f'<a href="{esc(link["Href"])}">{esc(link.get("LinkName") or link["Href"])}</a>'
              for link in folder.get("LinkAttachments", []) if link.get("Href")]
    out += section("Attachments", file_list(files))

    assessments = {a.get("RubricId"): a for e in mine for a in (e.get("Feedback") or {}).get("RubricAssessments") or []}
    rubrics = (folder.get("Assessment") or {}).get("Rubrics") or []
    out += section("Rubric" if len(rubrics) == 1 else "Rubrics",
                   "".join(_rubric(r, assessments.get(r.get("RubricId"))) for r in rubrics))

    submissions = ""
    for entity in mine:
        for sub in sorted(entity.get("Submissions", []), key=lambda s: s.get("SubmissionDate") or ""):
            by = (sub.get("SubmittedBy") or {}).get("DisplayName")
            meta = " · ".join(m for m in [when(sub.get("SubmissionDate")), esc(by or "")] if m)
            sub_files = []
            for f in sub.get("Files", []):
                link = ctx.file(f"dropbox/folders/{fid}/submissions/{sub['Id']}/files/{f['FileId']}", f["FileName"], f.get("Size"))
                sub_files.append(link + (' <span class="tag">Deleted</span>' if f.get("IsDeleted") else ""))
            comment = f'<div class="body">{rich(sub["Comment"])}</div>' if _has_text(sub.get("Comment")) else ""
            submissions += f'<article>\n<header><h3>{meta or "Submission"}</h3></header>\n{comment}{file_list(sub_files)}</article>\n'
    out += section("My submissions", submissions or '<p class="muted">No submissions.</p>')

    feedback = ""
    for entity in mine:
        fb = entity.get("Feedback")
        if not fb:
            continue
        entity_id = entity.get("Entity") or {}
        score = num(fb.get("Score"))
        grade = f"{score} / {num(out_of)}" if score and out_of else score
        body = details([("Score", esc(grade)), ("Grade", esc(fb.get("GradedSymbol") or ""))])
        if _has_text(fb.get("Feedback")):
            body += f'<div class="body">{rich(fb["Feedback"])}</div>\n'
        fb_files = [
            ctx.file(f"dropbox/folders/{fid}/feedback/{str(entity_id.get('EntityType', '')).lower()}/{entity_id.get('EntityId')}/attachments/{f['FileId']}",
                     f["FileName"], f.get("Size"))
            for f in fb.get("Files", [])
        ]
        fb_files += [f'<a href="{esc(link["Href"])}">{esc(link.get("LinkName") or link["Href"])}</a>'
                     for link in fb.get("Links", []) if link.get("Href")]
        body += file_list(fb_files)
        if fb.get("RubricAssessments"):
            body += '<p class="muted">Rubric scores are highlighted in the rubric above.</p>'
        feedback += body
    out += section("Feedback", feedback)
    return out


# ---------- discussions ----------

def _post(post: dict, children: dict[int, list[dict]], fid: int, tid: int, ctx: Context) -> str:
    author = "Anonymous" if post.get("IsAnonymous") else post.get("PostingUserDisplayName") or "Unknown"
    meta = [esc(author), when(post.get("DatePosted"))]
    if post.get("LastEditDate"):
        meta.append(f"edited {when(post['LastEditDate'])}")
    if post.get("ThreadIsPinned") and not post.get("ParentPostId"):
        meta.append('<span class="tag">Pinned</span>')
    if post.get("IsDeleted"):
        body = '<p class="muted">This post was deleted.</p>'
    else:
        body = f'<div class="body">{rich(post.get("Message"))}</div>'
    files = [ctx.file(f"discussions/forums/{fid}/topics/{tid}/posts/{post['PostId']}/attachments/{a['FileId']}",
                      a["FileName"], a.get("Size")) for a in post.get("Attachments", [])]
    replies = "".join(_post(r, children, fid, tid, ctx) for r in children.get(post["PostId"], []))
    return (
        f'<article id="post-{post["PostId"]}">\n<header><h3>{esc(post.get("Subject") or "")}</h3>'
        f'<div class="muted">{" · ".join(m for m in meta if m)}</div></header>\n{body}\n{file_list(files)}'
        + (f'<div class="replies">{replies}</div>' if replies else "") + "</article>\n"
    )


def _topic(forum: dict, entry: dict, ctx: Context) -> str:
    topic, posts = entry["topic"], entry["posts"]
    out = ""
    if entry.get("error"):
        out += note(f"Brightspace couldn't return this topic's posts ({esc(entry['error'])}), so they aren't in the archive.")
    out += details([
        ("Opens", when(topic.get("StartDate"))),
        ("Closes", when(topic.get("EndDate"))),
        ("Due", when(topic.get("DueDate"))),
        ("Locked", "Yes" if topic.get("IsLocked") else ""),
    ])
    if _has_text(topic.get("Description")):
        out += f'<div class="body">{rich(topic["Description"])}</div>\n'
    if _has_text(forum.get("Description")):
        out += f'<details><summary>About the {esc(forum["Name"])} forum</summary><div class="body">{rich(forum["Description"])}</div></details>\n'

    ids = {p["PostId"] for p in posts}
    children: dict[int, list[dict]] = {}
    roots = []
    for p in sorted(posts, key=lambda p: p.get("DatePosted") or ""):
        parent = p.get("ParentPostId")
        if parent in ids:
            children.setdefault(parent, []).append(p)
        else:  # thread starters, and replies whose parent wasn't returned
            roots.append(p)
    # pinned threads first, then newest thread first; replies stay oldest first
    roots =[p for p in roots if p.get("ThreadIsPinned")] + sorted(
        (p for p in roots if not p.get("ThreadIsPinned")), key=lambda p: p.get("DatePosted") or "", reverse=True)

    if not entry.get("error"):
        count = f"{len(roots)} thread{'s' * (len(roots) != 1)} · {len(posts)} post{'s' * (len(posts) != 1)}"
        out += f'<p class="muted">{count}</p>\n' if posts else '<p class="muted">No posts.</p>\n'
    fid, tid = forum["ForumId"], topic["TopicId"]
    out += "".join(_post(p, children, fid, tid, ctx) for p in roots)
    return out


# ---------- quizzes ----------

def _quizzes(quizzes: list[dict], ctx: Context) -> str:
    out = note("Brightspace doesn't let students download quiz questions or attempts, so only quiz details are archived.")
    if not quizzes:
        return out + '<p class="muted">No quizzes.</p>'
    for q in sorted(quizzes, key=lambda q: q.get("SortOrder") or 0):
        limit = q.get("SubmissionTimeLimit") or {}
        attempts = q.get("AttemptsAllowed") or {}
        allowed = "Unlimited" if attempts.get("IsUnlimited") else num(attempts.get("NumberOfAttemptsAllowed"))
        body = details([
            ("Opens", when(q.get("StartDate"))),
            ("Closes", when(q.get("EndDate"))),
            ("Due", when(q.get("DueDate"))),
            ("Time limit", f"{limit['TimeLimitValue']} minutes" if limit.get("IsEnforced") and limit.get("TimeLimitValue") else ""),
            ("Attempts", esc(allowed)),
        ])
        for key in ("Description", "Instructions"):
            text = (q.get(key) or {}).get("Text")
            if _has_text(text):
                body += f'<h3>{key}</h3><div class="body">{rich(text)}</div>\n'
        out += f'<article id="quiz-{q["QuizId"]}">\n<header><h2>{esc(q.get("Name") or "Untitled")}</h2></header>\n{body}</article>\n'
    return out


# ---------- grades ----------

def _grades(data: dict, ctx: Context) -> str:
    values = {v["GradeObjectIdentifier"]: v for v in data["values"]}
    items = [i for i in data["items"] if i.get("GradeType") != "Category"]
    categories = data["categories"]

    def row(name: str, value: dict | None, max_points=None, group=False) -> str:
        if value:
            points = f"{num(value.get('PointsNumerator'))} / {num(value.get('PointsDenominator'))}" if value.get("PointsDenominator") else ""
            weighted = f"{num(value.get('WeightedNumerator'))} / {num(value.get('WeightedDenominator'))}" if value.get("WeightedDenominator") else ""
            grade = value.get("DisplayedGrade") or ""
        else:
            points, weighted, grade = (f"– / {num(max_points)}" if max_points else "–"), "", ""
        cls = ' class="group"' if group else ""
        out = f'<tr{cls}><td>{esc(name)}</td><td class="num">{esc(points)}</td><td class="num">{esc(weighted)}</td><td class="num">{esc(grade)}</td></tr>'
        if value and _has_text(value.get("Comments")):
            out += f'<tr class="comment"><td colspan="4"><div class="body">{rich(value["Comments"])}</div></td></tr>'
        return out

    body = []
    shown = set()

    def item_rows(group_items):
        for i in group_items:
            shown.add(str(i["Id"]))
            body.append(row(i["Name"], values.get(str(i["Id"])), i.get("MaxPoints")))

    item_rows([i for i in items if not i.get("CategoryId")])
    for c in categories:
        shown.add(str(c["Id"]))
        body.append(row(c["Name"], values.get(str(c["Id"])), c.get("MaxPoints"), group=True))
        item_rows([i for i in items if i.get("CategoryId") == c["Id"]])
    for key, v in values.items():  # grades whose item definition wasn't visible
        if key not in shown:
            body.append(row(v["GradeObjectName"], v, group=v["GradeObjectTypeName"] == "Category"))

    out = ""
    final = data.get("final")
    if final:
        grade = final.get("DisplayedGrade") or f"{num(final.get('PointsNumerator'))} / {num(final.get('PointsDenominator'))}"
        out += details([("Final grade", f"<strong>{esc(grade)}</strong>")])
        if _has_text(final.get("Comments")):
            out += f'<div class="body">{rich(final["Comments"])}</div>\n'
    if not body:
        return out + '<p class="muted">No grades.</p>'
    return out + (
        '<div class="table-wrap"><table><thead><tr><th>Item</th><th class="num">Points</th><th class="num">Weighted</th><th class="num">Grade</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>'
    )


# ---------- which pages each category gets ----------

def pages_for(key: str, result: CategoryResult) -> list[Page]:
    """The generated pages for one crawled category (none for categories without readable pages yet)."""
    if result.error is not None:
        return []
    data = result.data
    label = LABELS[key]
    if key == COURSE_INFO:
        return [Page((), "course.html", "Course info", partial(_course, data))]
    if key == "announcements":
        return [Page((), "announcements.html", label, partial(_announcements, data))]
    if key == "quizzes":
        return [Page((), "quizzes.html", label, partial(_quizzes, data))]
    if key == "grades":
        return [Page((), "grades.html", label, partial(_grades, data))]
    if key == "assignments":
        return [Page((e["folder"]["Name"],), "assignment.html", e["folder"]["Name"], partial(_assignment, e), (label,))
                for e in data]
    if key == "discussions":
        return [Page((f["forum"]["Name"],), f"{t['topic']['Name']}.html", t["topic"]["Name"],
                     partial(_topic, f["forum"], t), (label, f["forum"]["Name"]))
                for f in data for t in f["topics"]]
    return []


def people(crawl: CourseCrawl) -> dict[str, str]:
    result = crawl.results.get("classlist")
    if result is None or result.error is not None:
        return {}
    return {str(p["Identifier"]): p.get("DisplayName") or "" for p in result.data["people"]}
