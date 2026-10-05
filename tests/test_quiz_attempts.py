import re, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root
from courses import Course
from crawl import COURSE_FILES, CategoryResult, CourseCrawl, RemoteFile, crawl_category
from download import plan, write_pages
from markdown_copy import to_markdown
from quiz_attempts import attempt_ids, attempt_url, parse_attempt, submissions_url

def check(name, got, want):
    print("PASS" if got == want else f"FAIL (got {got!r})", name)

OU = 1234
course = Course(OU, "202501 TEST 100 CO", "Spring 2025 TEST 100", True, "202501")
tmp = Path(tempfile.mkdtemp())

def block(html, inline=False):
    escaped = html.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
    return f'<d2l-html-block html="{escaped}"{" inline" if inline else ""}></d2l-html-block>'

def header(n, points, note="", retake=False):
    cls = "dco vui-heading-3 d2l-quiz-submission-question-header-container-retake-incorrect" if retake else "dco updated-submission-question-header"
    extra = f'<span class="d2l-body-small dh_s">{note}</span>' if note else ""
    return (f'<div class="{cls}"><div class="dco_c"><a id="Q{n}" name="Q{n}"></a><table><tr>'
            f'<td class="dlay_l"><label><strong>Question {n}</strong></label>{extra}</td><td class="dlay_m"></td>'
            f'<td class="dlay_r"><label>{points}</label></td></tr></table></div></div>')

def choice(text, selected, mark=None, inline=True):
    icon = f'<d2l-icon icon="tier1:check" class="di_i" alt="{mark}" title="{mark}"></d2l-icon>' if mark else "<label> </label>"
    radio = "radioChecked" if selected else "radioUnchecked"
    return (f'<tr><td><div class="dco d2l-qc-controls-container"><div class="dco_c">{icon}</div></div></td>'
            f'<td><span class="di_s"><img src="/d2l/img/0/QuestionCollection.Main.{radio}.svg" alt="{"Selected" if selected else "Unselected"}"/></span></td>'
            f'<td><div class="dco d2l-quiz-answer-container"><div class="d2l-htmlblock-untrusted">{block(text, inline)}</div></div></td></tr>')

def page(title, written, questions_html, scores=(("Attempt Score", "1 / 2 - 50 %"),)):
    rows = "".join(f'<tr><td><label>{k}</label></td><td><div class="dco d2l-grades-score"><label>{v}</label></div></td></tr>' for k, v in scores)
    return (f'<html><body><script>var x = "<div>";</script><div class="dco info"><h2 class="dhdg_2">{title}</h2>'
            f'<div class="dco"><label>{written}</label></div></div>'
            f'<div class="dco score"><div class="dco_c"><table class="d_t">{rows}</table></div></div>'
            f'<div class="dco"><div class="dco_c">{questions_html}'
            '<div class="dco"><div class="dco_c"><button type="button" class="d2l-button">Done</button></div></div></div></div>'
            '<input type="hidden" name="x" value="[1,2]"></body></html>').encode()

LATEX = '<math><semantics><mi>x</mi><annotation encoding="latex">{"version":"1.1","math":"\\(x^2\\)"}</annotation></semantics></math>'
FULL = page("Attempt 1 of 3", "Written Jan 10, 2024 12:20 AM - Jan 10, 2024 12:30 AM",
    '<div><h2 class="dhdg_1 vui-heading-2">Part A</h2></div>'
    + header(1, "0 / 1 point")
    + f'<div><div>{block("<p>Is it true?</p>")}</div><table class="d_t">'
    + choice("True", True, "Incorrect Response") + choice("False", False, "Correct Answer") + "</table>"
    + '<div><table class="d_FG"><tr><td><button type="button" class="d2l-hpg-opener"><span>Hide question 1 feedback</span></button></td></tr>'
    + f'<tr><td><h2 class="dhdg_2">Feedback</h2><div class="dco d2l-question-feedback-text">{block("<p>Because.</p>")}</div></td></tr></table></div></div>'
    + '<div><h2 class="dhdg_1 vui-heading-2">Part B</h2></div>'
    + header(2, "1 / 1 point")
    + f'<div><div>{block("<p>Compute " + LATEX + "</p>", inline=True)}<label>Answer:</label></div>'
    + '<table class="d_t"><tr><td><label>4.00</label></td><td><d2l-icon alt="Correct Response"></d2l-icon></td></tr></table></div>'
    + header(3, "1 / 1 point")
    + f'<div>{block("<p>Pick the diagram</p>")}<table class="d_t">'
    + choice('<p><img src="/content/enforced/1234-X/q3a.png"></p>', True, "Correct Response", inline=False)
    + choice("<p>none<br/></p>", False, inline=False) + "</table></div>")

# ---------- submissions page ----------

subs = ('<a href="quiz_submissions_attempt.d2l?isprv=&amp;qi=7&amp;ai=301&amp;isInPopup=0&amp;ou=1234">Attempt 1</a>'
        '<a href="quiz_submissions_attempt.d2l?isprv=&amp;qi=7&amp;ai=302&amp;ou=1234">Attempt 2</a>'
        '<a href="quiz_submissions_attempt.d2l?isprv=&amp;qi=7&amp;ai=301&amp;ou=1234">again</a>')
check("attempt ids in order, once each", attempt_ids(subs), [301, 302])
check("not attempted: no ids", attempt_ids('<label>You have not attempted this quiz.</label>'), [])
check("only review pages are requested", (submissions_url(OU, 7).split("?")[0], attempt_url(OU, 7, 301).split("?")[0]),
      ("/d2l/lms/quizzing/user/quiz_submissions.d2l", "/d2l/lms/quizzing/user/quiz_submissions_attempt.d2l"))

# ---------- parsing an attempt ----------

a = parse_attempt(7, 301, 9, FULL)
check("title, number from title, written", (a.title, a.number, a.written), ("Attempt 1 of 3", 1, "Written Jan 10, 2024 12:20 AM - Jan 10, 2024 12:30 AM"))
check("scores", a.scores, [("Attempt Score", "1 / 2 - 50 %")])
check("questions, points, sections", [(q.label, q.points, q.section) for q in a.questions],
      [("Question 1", "0 / 1 point", "Part A"), ("Question 2", "1 / 1 point", "Part B"), ("Question 3", "1 / 1 point", "Part B")])
check("nothing hidden", (a.visibility, a.error), ("", None))
q1, q2, q3 = a.questions
check("prompt is the question's own text", (q1.prompt, q2.prompt), ("Is it true?", "Compute x"))
check("choice rows: answer, then verdict", re.findall(r'<div class="row">(.*?)</div>', re.sub(r"\s+", " ", q1.html)),
      [' ◉ <span class="q-html">True</span> <span class="mark bad">✗ incorrect</span>',
       ' ○ <span class="q-html">False</span> <span class="mark ok">✓ correct answer</span>'])
check("feedback kept, toggle button and Brightspace chrome dropped",
      ("<strong>Feedback</strong>" in q1.html, "Because." in q1.html, "Hide question" in q1.html, "d2l-" in q1.html, "dhdg" in q1.html),
      (True, True, False, False, False))
check("typed answer with verdict", re.search(r'<div class="row">\s*4\.00\s*<span class="mark ok">✓ correct</span></div>', q2.html) is not None, True)
check("math kept in the page", "<math>" in q2.html, True)
check("non-inline answer blocks flattened to one line", re.sub(r"\s+", " ", q3.html).count('<span class="q-html">none </span>'), 1)
check("answer image kept", '<img src="/content/enforced/1234-X/q3a.png"/>' in q3.html, True)

retake = page("Retaken Attempt 2 of 3", "Written Jan 12, 2024 2:00 PM - Jan 12, 2024 2:10 PM",
              header(1, "1 / 1 point", "Correct on previous attempt(s)", retake=True) + f'<div>{block("<p>Q</p>")}</div>')
r = parse_attempt(7, 302, 2, retake)
check("retake: title, number, note", (r.title, r.number, [(q.label, q.note) for q in r.questions]),
      ("Retaken Attempt 2 of 3", 2, [("Question 1", "Correct on previous attempt(s)")]))

partial = page("Attempt 1 of Unlimited", "Written Jan 22, 2025 3:12 PM - Jan 24, 2025 3:34 PM", header(9, "0 / 2 points") + f'<div>{block("<p>Q9</p>")}</div>')
check("only some questions shown", "only shows some" in parse_attempt(7, 1, 1, partial).visibility, True)
check("score only", "only shows the score" in parse_attempt(7, 1, 1, page("Attempt 1 of 3", "Written Sep 18, 2023", "")).visibility, True)
check("never submitted", parse_attempt(7, 1, 1, page("Attempt 1 of 10", "Started Feb 26, 2024 10:27 AM (still in progress)", "")).visibility,
      "This attempt was never submitted.")
check("unreadable page keeps raw and says so", (lambda x: (x.raw, x.title))(parse_attempt(7, 1, 4, b"<html></html>")), (b"<html></html>", "Attempt 4"))

# ---------- Markdown ----------

md = to_markdown(q1.html + q2.html)
check("markdown: one line per answer", ("◉ True ✗ incorrect" in md, "○ False ✓ correct answer" in md), (True, True))
check("markdown: LaTeX kept unescaped", "Compute $x^2$" in md, True)
check("markdown: MathML without LaTeX becomes text",
      to_markdown('<p>Let <math><mi>A</mi><mo>∩</mo><mi>B</mi><annotation encoding="wiris">{"x":1}</annotation></math>.</p>'), "Let A ∩ B.\n")
check("markdown: display math source", to_markdown('<p><math><annotation encoding="LaTeX">\\[a_1\\]</annotation></math></p>'), "$a_1$\n")

# ---------- crawl ----------

class FakeSession:
    versions = {"le": "1.99", "lp": "1.63"}
    def __init__(self, pages):
        self.pages, self.fetched = pages, []
    def get_json(self, path, params=None):
        return {"Objects": [{"QuizId": 7, "Name": "Quiz 1"}, {"QuizId": 8, "Name": "Quiz 2"}], "Next": None}
    def fetch(self, path):
        self.fetched.append(path)
        return self.pages[path]
    def map(self, fn, items, done=None):
        return [fn(item) for item in items]
    def head_many(self, paths, done=None):
        return [(True, 10, {"content-type": "image/png"}) for _ in paths]

session = FakeSession({
    submissions_url(OU, 7): subs.encode(),
    submissions_url(OU, 8): b"<label>You have not attempted this quiz.</label>",
    attempt_url(OU, 7, 301): FULL,
    attempt_url(OU, 7, 302): retake,
})
result = crawl_category(session, course, "quizzes", lambda _: None)
check("crawl: attempts read", [(a.quiz_id, a.attempt_id, a.number) for a in result.attempts], [(7, 301, 1), (7, 302, 2)])
check("crawl: only review pages fetched", all("/quizzing/user/quiz_submissions" in p for p in session.fetched), True)
check("crawl: raw pages kept as files", [("/".join(f.path), f.name, f.data is not None) for f in result.files],
      [("Quiz 1/_originals", "attempt 1.html", True), ("Quiz 1/_originals", "attempt 2.html", True)])
check("crawl: note", result.note, "2 attempts · 4 questions")
files = crawl_category(session, course, COURSE_FILES, lambda _: None, {"quizzes": result})
check("crawl: question images become linked files", [(f.path, f.name) for f in files.files], [(("_assets",), "q3a.png")])

# ---------- pages ----------

crawl = CourseCrawl(course, {"quizzes": result, COURSE_FILES: files})
root = tmp / "archive"
_, jobs, page_jobs = plan(root, [crawl], ["quizzes"])
for job in jobs:
    job.dest.parent.mkdir(parents=True, exist_ok=True)
    job.dest.write_bytes(job.file.data or b"\x89PNG")
written, md_written, failed = write_pages(page_jobs, jobs)
check("pages written with Markdown", (len(written), len(md_written), failed), (2, 2, []))
base = root / "Spring 2025 TEST 100" / "quizzes"
check("quiz files", sorted(str(p.relative_to(base)).replace("\\", "/") for p in base.rglob("*") if p.is_file()),
      ["Quiz 1/_originals/attempt 1.html", "Quiz 1/_originals/attempt 2.html", "Quiz 1/attempts.html", "Quiz 1/attempts.md",
       "quizzes.html", "quizzes.md"])
listing = (base / "quizzes.html").read_text(encoding="utf-8")
check("quizzes page links attempts", '<a href="Quiz%201/attempts.html">2 attempts, 4 questions</a>' in listing, True)
html = (base / "Quiz 1" / "attempts.html").read_text(encoding="utf-8")
check("attempts page: both attempts, newest last", html.index("Attempt 1 of 3") < html.index("Retaken Attempt 2 of 3"), True)
check("attempts page: sections and image embedded", ("<h3>Part A</h3>" in html, 'src="data:image/png;base64,' in html), (True, True))
check("attempts page: links original", '<a href="_originals/attempt%201.html">the page as Brightspace showed it</a>' in html, True)
check("attempts page: back to details", '<a href="../quizzes.html#quiz-7">Quiz details</a>' in html, True)
md = (base / "Quiz 1" / "attempts.md").read_text(encoding="utf-8")
check("attempts markdown: image linked, math as LaTeX", ("](../../_course-files/_assets/q3a.png)" in md, "$x^2$" in md), (True, True))
