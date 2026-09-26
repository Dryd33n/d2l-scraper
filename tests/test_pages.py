import re, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root
from courses import Course
from crawl import COURSE_INFO, CategoryResult, CourseCrawl, RemoteFile
from download import Job, plan, write_pages
from pages import Context, Page, api_tail, document, pages_for, rich, when

def check(name, got, want):
    print("PASS" if got == want else f"FAIL (got {got!r})", name)

def rt(html, text=""):
    return {"Text": text, "Html": html}

OU = 1234
LE = f"/d2l/api/le/1.99/{OU}"
course = Course(OU, "202501 TEST 100 CO", "Spring 2025 TEST 100", True, "202501")
tmp = Path(tempfile.mkdtemp())

# ---------- helpers ----------

check("api tail", api_tail(f"{LE}/news/1/attachments/2", OU), "news/1/attachments/2")
check("api tail lp image", api_tail(f"/d2l/api/lp/1.63/courses/{OU}/image", OU), "image")
check("rich: site-relative src made absolute", rich(rt('<img src="/content/enforced/a.png">')),
      '<img src="https://bright.uvic.ca/content/enforced/a.png">')
check("rich: protocol-relative and external untouched", rich(rt('<a href="//x.com/a">x</a><a href="https://y.com">y</a>')),
      '<a href="//x.com/a">x</a><a href="https://y.com">y</a>')
check("rich: plain text fallback escaped", rich(rt("", "a < b\r\nc")), "a &lt; b<br>\nc")
check("rich: grade category Content/Type", rich({"Content": "<b>x</b>", "Type": 2}), "<b>x</b>")
check("when: empty", when(None), "")
check("when: keeps ISO in datetime attr", 'datetime="2025-01-26T07:59:59.000Z"' in when("2025-01-26T07:59:59.000Z"), True)
check("when: 12-hour format", bool(re.search(r">\w{3} \d{1,2} \w{3} 2025, \d{1,2}:\d{2} [AP]M<", when("2025-01-26T07:59:59.000Z"))), True)

# ---------- file links ----------

page_dest = tmp / "c" / "assignments" / "Lab 1" / "assignment.html"
present = tmp / "c" / "assignments" / "Lab 1" / "submissions" / "2025-01-24" / "my file#1.pdf"
present.parent.mkdir(parents=True)
present.write_bytes(b"x")
absent = tmp / "c" / "assignments" / "Lab 1" / "feedback" / "notes.pdf"
ctx = Context(CourseCrawl(course, {}), page_dest, None, {"a": present, "b": absent}, {})
check("file link relative and quoted", ctx.file("a"), '<a href="submissions/2025-01-24/my%20file%231.pdf">my file#1.pdf</a>')
check("file not downloaded", ctx.file("b", "notes.pdf"), 'notes.pdf <span class="muted">(not downloaded)</span>')
check("file not in archive", ctx.file("c", "x.pdf", 2048), 'x.pdf <span class="muted">2.0 KB</span> <span class="muted">(not in archive)</span>')

# ---------- assignments: rubric + assessment ----------

rubric = {
    "RubricId": 7, "Name": "Lab rubric", "Description": rt(""), "ReverseLevelDisplayOrder": False,
    "CriteriaGroups": [{
        "Name": "Criteria",
        "Levels": [{"Id": 1, "Name": "Good", "Points": None}, {"Id": 2, "Name": "Bad", "Points": None},
                   {"Id": 3, "Name": "Spare", "Points": None}],
        "Criteria": [{"Id": 10, "Name": "Code\r\n\r\nquality", "Cells": [
            {"LevelId": 1, "Description": rt("<p>clean</p>"), "Points": 2.0},
            {"LevelId": 2, "Description": rt("<p>messy</p>"), "Points": 0.0},
            {"LevelId": 3, "Description": rt(""), "Points": 0.0},
        ]}],
    }],
}
folder = {"Id": 55, "Name": "Lab 1", "CustomInstructions": rt("<p>Do it</p>"), "Attachments": [],
          "LinkAttachments": [{"LinkName": "Spec", "Href": "https://example.com/spec"}],
          "Assessment": {"ScoreDenominator": 10.0, "Rubrics": [rubric]}, "DueDate": "2025-01-26T07:59:59.000Z"}
mine = [{
    "Entity": {"EntityType": "User", "EntityId": 9},
    "Feedback": {"Score": 8.5, "Feedback": rt("<p>Nice</p>"), "Files": [{"FileId": 3, "FileName": "notes.pdf", "Size": 10}],
                 "Links": [], "GradedSymbol": None,
                 "RubricAssessments": [{"RubricId": 7, "OverallScore": 2.0, "OverallFeedback": rt("<p>overall good</p>"),
                                        "OverallLevel": {"LevelId": 1, "Name": "Good"},
                                        "CriteriaOutcome": [{"CriterionId": 10, "LevelId": 1, "Score": 2.0, "Feedback": rt("<p>tidy</p>")}]}]},
    "Submissions": [{"Id": 77, "SubmittedBy": {"DisplayName": "Me"}, "SubmissionDate": "2025-01-24T10:00:00.000Z",
                     "Comment": rt("<p>late, sorry</p>"),
                     "Files": [{"FileId": 4, "FileName": "lab1.zip", "Size": 5, "IsDeleted": False}]}],
}]
[page] = pages_for("assignments", CategoryResult(data=[{"folder": folder, "mysubmissions": mine}]))
check("assignment page location", (page.path, page.name, page.crumbs), (("Lab 1",), "assignment.html", ("Assignments",)))
files = {"dropbox/folders/55/submissions/77/files/4": present, "dropbox/folders/55/feedback/user/9/attachments/3": absent}
html = page.render(Context(CourseCrawl(course, {}), page_dest, None, files, {}))
check("rubric: chosen level highlighted", '<td class="picked"><p>clean</p>' in html, True)
check("rubric: unused level column dropped", "Spare" not in html, True)
check("rubric: criterion score and feedback", '<td class="num">2</td><td><p>tidy</p></td>' in html, True)
check("rubric: blank lines in criterion name collapsed", "<th>Code<br>\nquality</th>" in html, True)
check("rubric: overall feedback", "<p>overall good</p>" in html, True)
check("feedback score out of", "<dd>8.5 / 10</dd>" in html, True)
check("feedback file matched by entity type/id", "notes.pdf" in html and "(not downloaded)" in html, True)
check("submission file linked", 'href="submissions/2025-01-24/my%20file%231.pdf"' in html, True)
check("submission comment", "<p>late, sorry</p>" in html, True)
check("link attachment", '<a href="https://example.com/spec">Spec</a>' in html, True)

# ---------- discussions: threading ----------

def post(pid, parent, date, pinned=False, **kw):
    return {"PostId": pid, "ParentPostId": parent, "DatePosted": date, "ThreadIsPinned": pinned, "Subject": f"s{pid}",
            "Message": rt(f"<p>m{pid}</p>"), "PostingUserDisplayName": f"u{pid}", "Attachments": [], **kw}

posts = [
    post(1, None, "2025-01-01T00:00:00Z"),
    post(2, None, "2025-01-05T00:00:00Z"),
    post(3, None, "2024-12-01T00:00:00Z", pinned=True),
    post(4, 1, "2025-01-03T00:00:00Z"),
    post(5, 1, "2025-01-02T00:00:00Z", IsAnonymous=True),
    post(6, 99, "2025-01-04T00:00:00Z"),  # parent not returned
    post(7, 4, "2025-01-06T00:00:00Z", IsDeleted=True),
]
forum = {"ForumId": 8, "Name": "General", "Description": rt("")}
data = [{"forum": forum, "topics": [
    {"topic": {"TopicId": 9, "Name": "Q&A", "Description": rt("<p>ask here</p>")}, "posts": posts},
    {"topic": {"TopicId": 10, "Name": "Broken", "Description": rt("")}, "posts": [], "error": "HTTP 500"},
]}]
qa, broken = pages_for("discussions", CategoryResult(data=data))
check("topic page location", (qa.path, qa.name, qa.crumbs), (("General",), "Q&A.html", ("Discussions", "General")))
html = qa.render(Context(CourseCrawl(course, {}), tmp / "t.html", None, {}, {}))
order = [int(m) for m in re.findall(r'<article id="post-(\d+)">', html)]
check("pinned first, newest thread first, replies oldest first", order, [3, 2, 6, 1, 5, 4, 7])
check("reply nested under its parent", re.search(r'id="post-1">.*?<div class="replies"><article id="post-5">', html, re.S) is not None, True)
check("anonymous author", "Anonymous" in html and "u5" not in html, True)
check("deleted post", "This post was deleted." in html and "m7" not in html, True)
check("thread/post count", "4 threads · 7 posts" in html, True)
html = broken.render(Context(CourseCrawl(course, {}), tmp / "b.html", None, {}, {}))
check("failed topic noted", "couldn't return this topic's posts (HTTP 500)" in html, True)

# ---------- grades grouping ----------

grades = {
    "values": [
        {"GradeObjectIdentifier": "1", "GradeObjectName": "Labs", "GradeObjectTypeName": "Category", "PointsNumerator": 8.0,
         "PointsDenominator": 10.0, "WeightedNumerator": 16.0, "WeightedDenominator": 20.0, "DisplayedGrade": "80 %", "Comments": rt("")},
        {"GradeObjectIdentifier": "2", "GradeObjectName": "Lab 1", "GradeObjectTypeName": "Numeric", "PointsNumerator": 4.0,
         "PointsDenominator": 5.0, "WeightedNumerator": None, "WeightedDenominator": None, "DisplayedGrade": "80 %",
         "Comments": rt("<p>good</p>")},
    ],
    "items": [{"Id": 2, "Name": "Lab 1", "CategoryId": 1, "MaxPoints": 5.0, "GradeType": "Numeric"},
              {"Id": 3, "Name": "Lab 2", "CategoryId": 1, "MaxPoints": 5.0, "GradeType": "Numeric"},
              {"Id": 4, "Name": "Final", "CategoryId": 0, "MaxPoints": 50.0, "GradeType": "Numeric"}],
    "categories": [{"Id": 1, "Name": "Labs", "MaxPoints": 10.0}],
    "final": {"DisplayedGrade": "A+", "Comments": rt("")},
}
[page] = pages_for("grades", CategoryResult(data=grades))
html = page.render(Context(CourseCrawl(course, {}), tmp / "g.html", None, {}, {}))
names = re.findall(r"<tr(?: class=\"group\")?><td>([^<]+)</td>", html)
check("uncategorised first, then category and its items", names, ["Final", "Labs", "Lab 1", "Lab 2"])
check("ungraded item shows out of", "– / 5" in html, True)
check("grade comment row", '<tr class="comment"><td colspan="4"><div class="body"><p>good</p>' in html, True)
check("final grade", "<strong>A+</strong>" in html, True)

# ---------- plan + write ----------

news = [{"Id": 1, "Title": "Hi", "Body": rt("<p>hello</p>"), "StartDate": "2025-01-02T00:00:00Z", "CreatedBy": 42,
         "IsAuthorInfoShown": True, "Attachments": [{"FileId": 5, "FileName": "a.pdf", "Size": 3}]},
        {"Id": 2, "Title": "Older", "Body": rt("<p>old</p>"), "StartDate": "2025-01-01T00:00:00Z", "CreatedBy": 1,
         "IsAuthorInfoShown": False, "Attachments": []}]
crawl = CourseCrawl(course, {
    COURSE_INFO: CategoryResult(data={"enrollment": {"OrgUnit": {"Code": "C1"}, "Access": {}}, "overview": None}),
    "classlist": CategoryResult(data={"people": [{"Identifier": "42", "DisplayName": "Prof X"}], "groups": []}),
    "announcements": CategoryResult(data=news, files=[RemoteFile(("attachments",), "a.pdf", f"{LE}/news/1/attachments/5", 3)]),
    "quizzes": CategoryResult(error="not available (HTTP 403)"),
})
root = tmp / "archive"
_, jobs, page_jobs = plan(root, [crawl])
check("pages planned", sorted(str(pj.dest.relative_to(root)).replace("\\", "/") for pj in page_jobs),
      ["Spring 2025 TEST 100/announcements/announcements.html", "Spring 2025 TEST 100/course info/course.html"])
jobs[0].dest.parent.mkdir(parents=True)
jobs[0].dest.write_bytes(b"abc")
written, failed = write_pages(page_jobs, jobs)
check("pages written", (written, failed), (2, []))
html = (root / "Spring 2025 TEST 100/announcements/announcements.html").read_text(encoding="utf-8")
check("announcements newest first", html.index(">Hi<") < html.index(">Older<"), True)
check("author from classlist", "Prof X" in html, True)
check("attachment linked", '<a href="attachments/a.pdf">a.pdf</a>' in html, True)
check("crumb links to course page", '<a href="../course%20info/course.html">Spring 2025 TEST 100</a>' in html, True)
check("self-contained style", "<style>" in html and "<link" not in html, True)

bad = CourseCrawl(course, {"announcements": CategoryResult(data=[{"Id": 1, "Attachments": [{}]}])})  # attachment without FileId
_, jobs, page_jobs = plan(tmp / "bad", [bad])
written, failed = write_pages(page_jobs, jobs)
check("broken record recorded as failure, not raised", (written, len(failed)), (0, 1))

# ---------- content: outline, links, shortcuts, quickLinks ----------

from crawl import HtmlPage
QL = "/d2l/common/dialogs/quickLink/quickLink.d2l?ou=1234&type="
def topic(tid, title, kind="File", activity=1, url=None, sort=0, **kw):
    return {"TopicId": tid, "Title": title, "TypeIdentifier": kind, "ActivityType": activity, "Url": url, "SortOrder": sort,
            "IsBroken": False, "ActivityId": f"https://ids.brightspace.com/activities/x/ABC-{tid}", "Description": rt(""), **kw}
toc = {"Modules": [{"ModuleId": 1, "Title": "Week 1", "SortOrder": 1, "Description": rt("<p>Read <a href='/d2l/le/content/1234/viewContent/11/View'>the slides</a></p>"),
                    "Modules": [], "Topics": [
    topic(11, "Slides", url="/content/enforced/x/slides.pdf", sort=1),
    topic(12, "Page", url="/content/enforced/x/page.html", sort=2),
    topic(13, "Textbook", "Link", 2, "https://example.com/book", sort=3),
    topic(14, "Quiz 1", "Link", 4, QL + "quiz&rCode=QZ-7", sort=4),
    topic(15, "Recordings", "Link", 7, QL + "lti&rcode=LTI-1", sort=5),
    topic(16, "Old notes", sort=6, IsBroken=True),
]}]}
page_html = b'<html><body><a href="/d2l/common/dialogs/quickLink/quickLink.d2l?ou=1234&amp;type=quiz&amp;rcode=qz-7">quiz</a></body></html>'
crawl = CourseCrawl(course, {
    "content": CategoryResult(data=toc, files=[RemoteFile(("01 Week 1",), "slides.pdf", f"{LE}/content/topics/11/file", 4)],
                              html_pages=[HtmlPage(12, ("01 Week 1",), "page.html", f"{LE}/content/topics/12/file", "https://bright.uvic.ca/content/enforced/x/page.html", page_html)]),
    "quizzes": CategoryResult(data=[{"QuizId": 7, "Name": "Quiz 1", "ActivityId": "https://ids.brightspace.com/activities/quiz/QZ-7"}]),
})
root = tmp / "content-archive"
_, jobs, page_jobs = plan(root, [crawl])
jobs[0].dest.parent.mkdir(parents=True)
jobs[0].dest.write_bytes(b"%PDF")
written, failed = write_pages(page_jobs, jobs)
check("content pages written", failed, [])
base = root / "Spring 2025 TEST 100" / "content"
check("content files", sorted(str(p.relative_to(base)).replace("\\", "/") for p in base.rglob("*") if p.is_file()),
      ["01 Week 1/Quiz 1.html", "01 Week 1/Recordings.url", "01 Week 1/Textbook.url", "01 Week 1/page.html", "01 Week 1/slides.pdf", "content.html", "links.html"])
check(".url shortcut", (base / "01 Week 1/Textbook.url").read_bytes(), b"[InternetShortcut]\r\nURL=https://example.com/book\r\n")
check("LTI shortcut keeps Brightspace URL", b"type=lti" in (base / "01 Week 1/Recordings.url").read_bytes(), True)
check("tool shortcut redirects to archived quiz", 'url=../../quizzes/quizzes.html#quiz-7"' in (base / "01 Week 1/Quiz 1.html").read_text(encoding="utf-8"), True)
check("HTML topic quickLink (lowercase rcode) rewritten", 'href="../../quizzes/quizzes.html#quiz-7"' in (base / "01 Week 1/page.html").read_text(encoding="utf-8"), True)
outline = (base / "content.html").read_text(encoding="utf-8")
check("outline links file and page", 'href="01%20Week%201/slides.pdf">Slides</a>' in outline and 'href="01%20Week%201/page.html">Page</a>' in outline, True)
check("outline: broken topic noted", "Old notes <span class=\"muted\">missing on Brightspace</span>" in outline, True)
check("outline: viewContent link in description goes to the file", "<a href=\"01%20Week%201/slides.pdf\">the slides</a>" in outline, True)
links_page = (base / "links.html").read_text(encoding="utf-8")
check("links page lists link topics only", re.findall(r'<tr id="topic-(\d+)">', links_page), ["13", "14", "15"])
check("links page: LTI note", "(only works inside Brightspace)" in links_page, True)
