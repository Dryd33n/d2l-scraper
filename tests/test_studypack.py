import io, json, re, sys, tempfile, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root
from pypdf import PdfReader, PdfWriter
import studypack
from studypack import MANIFEST, build_pack

def check(name, got, want):
    print("PASS" if got == want else f"FAIL (got {got!r})", name)

tmp = Path(tempfile.mkdtemp())
course = tmp / "archive" / "Fall 2026 TEST 100"
packs = tmp / "archive" / "Study Packs"

def write(rel, data):
    path = course / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)

made = 0
def pdf(pages=1):  # each one different, so they aren't taken for duplicates
    global made
    made += 1
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(72, 72)
    w.add_metadata({"/Title": f"test {made}"})
    buffer = io.BytesIO()
    w.write(buffer)
    return buffer.getvalue()

def pptx(*slides):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for i, text in enumerate(slides, 1):
            z.writestr(f"ppt/slides/slide{i}.xml", f'<p:sld><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:sld>')
        z.writestr("ppt/notesSlides/notesSlide1.xml", '<a:p><a:r><a:t>say this</a:t></a:r></a:p><a:p><a:r><a:t>1</a:t></a:r></a:p>')
    return buffer.getvalue()

def page(title, body):  # a generated page, as download.py writes them
    return f"<html><body><nav>Fall 2026 TEST 100 › x</nav><h1>{title}</h1>{body}<footer>Archived from Brightspace <time>Mon 5 Oct 2026, 1:00 PM</time></footer></body></html>"

# ---------- a small archive ----------

write("course info/course.html", page("Course info", "<p>Welcome to TEST 100.</p>"))
write("course info/course.json", "{}")
write("content/content.html", page("Content", "<p>outline</p>"))
write("content/links.html", page("Links", "<p>links</p>"))
write("content/content.json", json.dumps({"Modules": [
    {"Title": "Week 1", "SortOrder": 1, "Modules": [], "Topics": [
        {"Title": "Notes", "TypeIdentifier": "File", "Url": "/content/enforced/x/b-notes.pdf", "SortOrder": 1},
        {"Title": "Slides", "TypeIdentifier": "File", "Url": "/content/enforced/x/a-slides.pdf", "SortOrder": 2},
    ]},
    {"Title": "Week 2", "SortOrder": 2, "Modules": [], "Topics": []},
]}))
write("content/01 Week 1/b-notes.pdf", pdf(2))
write("content/01 Week 1/a-slides.pdf", pdf(1))
write("content/01 Week 1/copy of notes.pdf", (course / "content/01 Week 1/b-notes.pdf").read_bytes())
write("content/01 Week 1/Reading.html", "<html><body><h1>Reading</h1><p>Read chapter 1.</p><img src=\"data:image/png;base64,AAAA\"></body></html>")
write("content/01 Week 1/Quiz 1.html", '<!doctype html>\n<meta charset="utf-8">\n<meta http-equiv="refresh" content="0; url=../../quizzes/quizzes.html">')
write("content/01 Week 1/Textbook.url", "[InternetShortcut]\r\nURL=https://example.com/book\r\n")
write("content/01 Week 1/Main.java", "class Main {}\n")
write("content/01 Week 1/starter.zip", b"PK")
write("content/01 Week 1/lecture.mp4", b"\x00")
write("content/02 Week 2/w2.pdf", pdf(1))
write("content/02 Week 2/talk.pptx", pptx("Big idea", "Details"))
write("content/02 Week 2/talk2.pptx", pptx("Second talk"))
write("content/02 Week 2/diagram.png", b"")  # replaced below with a real image
from PIL import Image
Image.new("RGB", (4, 4), "red").save(course / "content/02 Week 2/diagram.png")
write("announcements/announcements.html", page("Announcements", "<h2>Midterm</h2><p>Covers weeks 1-2.</p>"))
write("assignments/assignments.json", json.dumps([{"folder": {"Name": "Lab 1"}}]))
write("assignments/Lab 1/assignment.html", page("Lab 1", "<h2>Instructions</h2><p>Do the lab.</p>"))
write("assignments/Lab 1/attachments/lab1.pdf", pdf(1))
write("assignments/Lab 1/attachments/Lab1.java", "class Lab1 {}\n")
write("assignments/Lab 1/submissions/2026-09-01/mine.pdf", pdf(1))
write("discussions/General/Questions.html", page("Questions", "<article><h3>When is the exam?</h3><p>Friday.</p></article>"))
write("discussions/General/Empty.html", page("Empty", '<p class="muted">No posts.</p>'))

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contextlib
with contextlib.redirect_stdout(io.StringIO()):
    import test_quiz_attempts as qa  # builds attempt pages in Brightspace's markup
write("quizzes/quizzes.json", json.dumps([{"QuizId": 7, "Name": "Quiz 1", "SortOrder": 1}, {"QuizId": 8, "Name": "Quiz 2", "SortOrder": 2}]))
write("quizzes/Quiz 1/_originals/attempt 1.html", qa.FULL)
write("quizzes/Quiz 1/_originals/attempt 2.html", qa.retake)
write("quizzes/Quiz 2/_originals/attempt 1.html", qa.page("Attempt 1 of 3", "Written Sep 18, 2023", ""))

# ---------- a pack that fits ----------

pack = build_pack(course, packs)
names = [p.name for p, _ in pack.written]
check("sources in order", names, [
    "01 Course overview.md", "02 Practice questions.md", "03 Assignments.md", "04 Discussions.md",
    "05 Week 1 (pages).md", "06 b-notes.pdf", "07 a-slides.pdf", "08 diagram.png", "09 talk.pptx", "10 talk2.pptx", "11 w2.pdf",
    "12 lab1.pdf"])
check("manifest written, nothing else", sorted(p.name for p in pack.folder.iterdir()), sorted(names + [MANIFEST]))
check("no merging needed", pack.steps, [])
left = dict(pack.left_out)
check("left out: duplicate, zip, video, own submissions", sorted(left), sorted([
    "Week 1 › copy of notes.pdf", "Week 1 › starter.zip", "Week 1 › lecture.mp4", "Assignments › Lab 1 › submissions"]))
check("duplicate names the original", left["Week 1 › copy of notes.pdf"], "same file as Week 1 › b-notes.pdf")
check("web links kept for the manifest", pack.links, [("Week 1 › Textbook", "https://example.com/book")])
check("score-only quiz noted", any("Quiz 2" in n for n in pack.notes), True)

overview = (pack.folder / "01 Course overview.md").read_text(encoding="utf-8")
check("overview: course info and announcements, no breadcrumb or footer",
      ("Welcome to TEST 100." in overview, "## Announcements" in overview, "Covers weeks 1-2." in overview, " › x" in overview, "Archived" in overview),
      (True, True, True, False, False))
pages = (pack.folder / "05 Week 1 (pages).md").read_text(encoding="utf-8")
check("module pages: page text, code, no redirect or data images",
      ("## Week 1 › Reading" in pages, "Read chapter 1." in pages, "```java\nclass Main {}\n```" in pages, "refresh" in pages, "base64" in pages),
      (True, True, True, False, False))
check("content outline and links pages left to the overview", "outline" in pages or "links" in pages, False)

practice = (pack.folder / "02 Practice questions.md").read_text(encoding="utf-8")
check("practice: unique questions across attempts", practice.count("### Question"), 4)
check("practice: answer key, no selections",
      ("**Correct answer:** B" in practice, "◉" in practice, "✓" in practice, "**Feedback:** Because." in practice),
      (True, False, False, True))
check("practice: typed answer", "**Correct answer:** 4.00" in practice, True)
check("practice: header", "4 questions from 2 attempts." in practice, True)
assignments = (pack.folder / "03 Assignments.md").read_text(encoding="utf-8")
check("assignments: instructions and attached code", ("Do the lab." in assignments, "class Lab1 {}" in assignments), (True, True))
check("discussions: empty topics skipped", ((pack.folder / "04 Discussions.md").read_text(encoding="utf-8").count("## General"), ), (1,))

# ---------- fitting a smaller limit ----------

pack = build_pack(course, packs, limit=10)
names = [p.name for p, _ in pack.written]
check("merged per module first", names[4:], ["05 Week 1 (pages).md", "06 Week 1.pdf", "07 Week 2.pdf", "08 talk.pptx", "09 talk2.pptx", "10 lab1.pdf"])
merged = PdfReader(pack.folder / "06 Week 1.pdf")
check("merged PDF: pages in instructor order, bookmarks", (len(merged.pages), [o.title for o in merged.outline]),
      (3, ["Week 1 › b-notes.pdf", "Week 1 › a-slides.pdf"]))
check("image merged as a PDF page", len(PdfReader(pack.folder / "07 Week 2.pdf").pages), 2)

pack = build_pack(course, packs, limit=9)
names = [p.name for p, _ in pack.written]
check("then slides become text", names[4:], ["05 Week 1 (pages).md", "06 Week 1.pdf", "07 Week 2.pdf", "08 Week 2 (pages).md", "09 lab1.pdf"])
text = (pack.folder / "08 Week 2 (pages).md").read_text(encoding="utf-8")
check("slide text and notes, no slide number", ("#### Slide 1" in text, "Big idea" in text, "Notes: say this" in text, "Notes: say this 1" in text, "Second talk" in text),
      (True, True, True, False, True))
check("steps recorded", [s.split(":")[0] for s in pack.steps],
      ["merged the PDFs of 2 modules", "turned 2 slide/Word files into text (their images are lost)"])
check("manifest lists steps and merged parts", ("into text" in (pack.folder / MANIFEST).read_text(encoding="utf-8"),
      "  - Week 2 › talk2.pptx" in (pack.folder / MANIFEST).read_text(encoding="utf-8")), (True, True))

pack = build_pack(course, packs, limit=11)
check("only as much merging as needed: the module with the most files", [p.name for p, _ in pack.written][4:7],
      ["05 Week 1 (pages).md", "06 Week 1.pdf", "07 diagram.png"])

pack = build_pack(course, packs, limit=6)
check("still over: the largest files are left out, documents kept", (len(pack.written), [p.name for p, _ in pack.written][:4]),
      (6, ["01 Course overview.md", "02 Practice questions.md", "03 Assignments.md", "04 Discussions.md"]))
check("left-out files listed", sum(why == "over the source limit" for _, why in pack.left_out) >= 1, True)

# ---------- safety ----------

other = packs / course.name
for f in other.iterdir():
    f.unlink()
(other / "my notes.txt").write_text("mine")
try:
    build_pack(course, packs)
    check("won't replace a folder that isn't a pack", "replaced", "refused")
except RuntimeError:
    check("won't replace a folder that isn't a pack", (other / "my notes.txt").exists(), True)
check("course folders exclude the packs folder", [p.name for p in studypack.course_folders(tmp / "archive")], ["Fall 2026 TEST 100"])
