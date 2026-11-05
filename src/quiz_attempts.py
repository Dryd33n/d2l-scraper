"""Quiz attempts: the review pages Brightspace shows students for the attempts they submitted.

The Valence API refuses students quiz questions and attempts (403), but the review pages a student
opens in Brightspace load with the same login. Only two pages are ever requested: a quiz's list of
submissions and an attempt's review page. Neither starts or changes an attempt; the pages that start a
quiz are never touched.

How much an attempt shows is up to the instructor: every question with the right answers and feedback,
only the questions answered wrongly, or just the score. Whatever the page shows is kept.
"""

import html
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

SUBMISSIONS = "/d2l/lms/quizzing/user/quiz_submissions.d2l"
ATTEMPT = "/d2l/lms/quizzing/user/quiz_submissions_attempt.d2l"

ATTEMPT_LINK = re.compile(r"quiz_submissions_attempt\.d2l\?[^\"'<>\s]*?\bai=(\d+)")
QUESTION_ANCHOR = re.compile(r"^Q\d+$")  # <a name="Q3"> starts each question's header
CHROME_BLOCKS = {"table", "tbody", "thead", "tfoot", "td", "th", "label", "span", "font", "center", "fieldset"}
FLATTEN = ["p", "div", "table", "tbody", "thead", "tr", "td", "th"]
DROP = ["script", "style", "input", "button", "iframe", "noscript", "select", "textarea", "legend"]
# icons next to answers, by their alt text: (css class, text shown instead)
MARKS = {
    "Correct Response": ("ok", "✓ correct"),
    "Incorrect Response": ("bad", "✗ incorrect"),
    "Correct Answer": ("ok", "✓ correct answer"),
}


def submissions_url(course_id: int, quiz_id: int) -> str:
    return f"{SUBMISSIONS}?qi={quiz_id}&ou={course_id}"


def attempt_url(course_id: int, quiz_id: int, attempt_id: int) -> str:
    return f"{ATTEMPT}?isprv=&qi={quiz_id}&ai={attempt_id}&isInPopup=0&cfql=0&fromQB=0&fromSubmissionsList=1&ou={course_id}"


def attempt_ids(page: str) -> list[int]:
    """The attempts a quiz's submissions page links to, in the order it lists them (none when the
    quiz wasn't attempted, or its attempts can't be reviewed)."""
    return list(dict.fromkeys(int(ai) for ai in ATTEMPT_LINK.findall(html.unescape(page))))


@dataclass
class Question:
    label: str  # "Question 2"
    note: str  # what Brightspace adds to the label, e.g. "Retaken", "Correct on previous attempt(s)"
    points: str  # "1 / 2 points", or "" when not shown
    section: str  # the section heading it's under, or ""
    html: str  # the question, the answers with yours and the right ones marked, and any feedback
    prompt: str  # the question's own text, to recognise the same question in another attempt


@dataclass
class Attempt:
    quiz_id: int
    attempt_id: int
    number: int  # 1 for the first attempt listed
    raw: bytes = field(repr=False)  # the review page as downloaded
    title: str = ""  # "Attempt 1 of 3"
    written: str = ""  # "Written Jan 10, 2024 12:20 AM - Jan 11, 2024 6:37 PM"
    scores: list[tuple[str, str]] = field(default_factory=list)  # [("Attempt Score", "11 / 16 - 68.75 %"), ...]
    questions: list[Question] = field(default_factory=list)
    error: str | None = None  # set when the page couldn't be read; the raw page is still kept

    @property
    def visibility(self) -> str:
        """Why questions might be missing, or "" when nothing suggests any are."""
        if self.error:
            return f"The page couldn't be read ({self.error}); the original is kept."
        if "in progress" in self.written:
            return "This attempt was never submitted."
        if not self.questions:
            return "Brightspace only shows the score for this attempt."
        numbers = [int(m[1]) for q in self.questions if (m := re.match(r"Question (\d+)", q.label))]
        if numbers and numbers != list(range(1, len(numbers) + 1)):
            return "Brightspace only shows some of this attempt's questions (often just the ones answered wrongly)."
        return ""


def parse_attempt(quiz_id: int, attempt_id: int, number: int, raw: bytes) -> Attempt:
    """Read an attempt's review page. A page that can't be read keeps its raw copy and an `error`."""
    a = Attempt(quiz_id, attempt_id, number, raw)
    try:
        soup = BeautifulSoup(raw.decode("utf-8", errors="replace"), "html.parser")
        title = soup.find(lambda t: t.name in ("h1", "h2") and re.search(r"Attempt \d+ of", _text(t)))
        a.title = _text(title) if title else f"Attempt {number}"
        if m := re.search(r"Attempt (\d+) of", a.title):
            a.number = int(m[1])
        written = soup.find(lambda t: t.name == "label" and re.match(r"(Written|Started) ", _text(t)))
        a.written = _text(written) if written else ""
        if score := soup.find("div", class_="score"):
            for row in score.find_all("tr"):
                cells = row.find_all("td", recursive=False)
                if len(cells) >= 2:
                    a.scores.append((_text(cells[0]), _text(cells[1])))
        a.questions = _questions(soup)
    except Exception as e:  # Brightspace's markup changed: keep the raw page, say so
        a.error = f"{type(e).__name__}: {e}"
    return a


def _text(tag: Tag) -> str:
    return " ".join(tag.get_text(" ", strip=True).split())


def _words(tag: Tag) -> str:
    """A tag's visible text: like `_text`, without the source that math formulas carry along."""
    return " ".join(" ".join(s for s in tag.find_all(string=True) if s.parent.name != "annotation").split())


def _questions(soup: BeautifulSoup) -> list[Question]:
    """Each question header is followed by its body, with section headings between them, as siblings."""
    questions = []
    headers = [a.find_parent("div", class_="dco") for a in soup.find_all("a", attrs={"name": QUESTION_ANCHOR})]
    headers = [h for h in headers if h is not None]
    is_header = {id(h) for h in headers}
    parents = list({id(h.parent): h.parent for h in headers}.values())  # bs4 tags compare by content
    for parent in parents:
        section, header, body = "", None, []

        def flush():
            if header is not None:
                questions.append(_question(header, body, section))

        for el in parent.children:
            if not isinstance(el, Tag):
                continue
            if id(el) in is_header:
                flush()
                header, body = el, []
            elif heading := (el if el.name in ("h1", "h2") else el.find(["h1", "h2"], class_="dhdg_1")):
                if el.find("d2l-html-block") is None:  # a section heading, not a question's own "Feedback"
                    flush()
                    header, section = None, _text(heading)
                    continue
                body.append(el)
            elif el.find("button", string=re.compile(r"^\s*Done\s*$")):
                break
            elif header is not None:
                body.append(el)
        flush()
    return questions


def _question(header: Tag, body: list[Tag], section: str) -> Question:
    left, right = header.find("td", class_="dlay_l"), header.find("td", class_="dlay_r")
    label_text = _text(left) if left else _text(header)
    m = re.match(r"(Question \d+)\s*(.*)", label_text)
    label, note = (m[1], m[2]) if m else (label_text, "")
    frag = BeautifulSoup("".join(str(el) for el in body), "html.parser")
    prompt = _clean(frag)
    return Question(label, note, _text(right) if right else "", section, str(frag).strip(), prompt)


def _clean(frag: BeautifulSoup) -> str:
    """Turn a question's Brightspace markup into plain HTML: the instructor's HTML put in place, answer
    icons as text, layout tables as one row per line. Returns the question's own text."""
    for t in frag.find_all(DROP):
        t.decompose()

    # the instructor's HTML lives in <d2l-html-block html="...">
    for block in frag.find_all("d2l-html-block"):
        inner = BeautifulSoup(block.get("html") or "", "html.parser")
        answer = block.find_parent("tr") is not None and (
            block.has_attr("inline") or block.find_parent(class_="d2l-quiz-answer-container") is not None)
        if answer:  # keep it on its row's line
            for t in inner.find_all(FLATTEN):
                t.insert_after(" ")
                t.unwrap()
            for t in inner.find_all("br"):
                t.replace_with(" ")
        wrapper = frag.new_tag("span" if answer else "div", attrs={"class": "q-html"})
        wrapper.extend(list(inner.contents))
        block.replace_with(wrapper)

    def ours(t: Tag) -> bool:  # not part of the instructor's HTML
        return t.find_parent(class_="q-html") is None and "q-html" not in (t.get("class") or [])

    for t in frag.find_all(["img", "d2l-icon"]):
        if not ours(t):
            continue
        alt = t.get("alt") or t.get("title") or ""
        src = t.get("src") or ""
        if alt in MARKS:
            cls, text = MARKS[alt]
            mark = frag.new_tag("span", attrs={"class": f"mark {cls}"})
            mark.string = text
            t.replace_with(mark)
        elif alt in ("Selected", "Unselected"):
            box = "check-box" in src
            t.replace_with(("☑" if box else "◉") if alt == "Selected" else ("☐" if box else "○"))
        else:
            t.decompose()

    prompt = next((text for t in frag.find_all("div", class_="q-html") if (text := _words(t))), _words(frag))

    for t in list(frag.find_all(True)):
        if not ours(t) or "mark" in (t.get("class") or []):
            continue
        if t.name == "tr":
            t.name, t.attrs = "div", {"class": "row"}
        elif t.name in ("h1", "h2", "h3", "h4"):  # "Feedback" inside a question
            t.name, t.attrs = "p", {}
            strong = frag.new_tag("strong")
            strong.extend(list(t.contents))
            t.append(strong)
        elif t.name in CHROME_BLOCKS or t.name == "div" or t.name.startswith("d2l-"):
            t.insert_after(" ")
            t.unwrap()
        elif t.name == "a":
            t.attrs = {"href": t["href"]} if t.get("href") and not t["href"].startswith("javascript:") else {}
            if not t.attrs:
                t.unwrap()
        else:
            t.attrs = {}

    for row in frag.find_all("div", class_="row"):
        if row.find("div", class_="row"):  # a layout table around the answer table (matching questions)
            row.unwrap()
        elif row.find(["div", "p"]):  # feedback and other blocks laid out in a table: not an answer line
            row.attrs = {}
    for row in frag.find_all("div", class_="row"):  # the verdict reads best after the answer
        for mark in row.find_all("span", class_="mark"):
            if ours(mark):
                row.append(" ")
                row.append(mark.extract())
    for t in reversed(frag.find_all(["div", "p", "strong"])):
        if ours(t) and not t.get_text(strip=True) and t.find(["img", "math"]) is None:
            t.decompose()
    return prompt


# ---------- study cards (for the study pack) ----------

SYMBOLS = {"◉": "selected", "☑": "selected", "○": "unselected", "☐": "unselected"}


@dataclass
class Card:
    """A question as a study card: the question, its choices, the right answer, and feedback, without
    the attempt's own selections."""
    prompt: str  # HTML
    choices: list[str]  # HTML of each choice, in order; empty for typed answers
    answer: list[str] | None  # letters ("B") for choice questions, values for typed and matching answers; None when not shown
    feedback: str  # HTML, or ""
    key: str  # text of the question and its choices, to spot the same question in another attempt
    lettered: bool  # a choice question: answers are letters of `choices`


def study_card(q: Question) -> Card:
    """Read a parsed question back into a card, working out the right answer from the attempt's marks:
    a choice marked "correct answer", or selected and marked correct; for multi-select, each row's mark
    says whether that row was answered right; a typed answer that was wrong shows the right one in brackets."""
    frag = BeautifulSoup(q.html, "html.parser")
    feedback = ""
    if label := frag.find("strong", string=re.compile(r"^\s*Feedback\s*$")):
        para = label.find_parent("p") or label
        rest = list(para.next_siblings)
        feedback = "".join(str(t) for t in rest).strip()
        for t in rest:
            t.extract()
        container = para.parent
        para.decompose()
        if container is not None and container.name == "div" and not container.get_text(strip=True) and container.find("img") is None:
            container.decompose()

    rows = []
    for row in frag.find_all("div", class_="row"):
        marks = [m.get_text(strip=True) for m in row.find_all("span", class_="mark")]
        for m in row.find_all("span", class_="mark"):
            m.decompose()
        text = row.decode_contents()
        state = next((SYMBOLS[s] for s in SYMBOLS if s in text), None)
        box = "☑" in text or "☐" in text
        for s in SYMBOLS:
            text = text.replace(s, "")
        rows.append((state, box, marks, text.strip()))
        row.decompose()
    for t in frag.find_all(string=re.compile(r"^\s*Answer:\s*$")):
        t.extract()
    prompt = str(frag).strip()

    choice_rows = [r for r in rows if r[0] is not None]
    other_rows = [r for r in rows if r[0] is None]
    choices = [text for _, _, _, text in choice_rows]
    answer: list[str] | None = None
    if choice_rows:
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        multi = any(box for _, box, _, _ in choice_rows)
        right = []
        known = True
        for i, (state, _, marks, _) in enumerate(choice_rows):
            correct_answer = "✓ correct answer" in marks
            ok, bad = "✓ correct" in marks, "✗ incorrect" in marks
            if multi:
                if not (ok or bad or correct_answer):
                    known = False
                elif correct_answer or (state == "selected") == ok:
                    right.append(letters[i % 26])
            elif correct_answer or (state == "selected" and ok):
                right.append(letters[i % 26])
        answer = right if known and right else None
    elif other_rows:  # typed answers and matching: each marked row is one answer
        values = []
        for _, _, marks, text in other_rows:
            if "✓ correct" in marks:
                values.append(_inline(text))
            elif "✗ incorrect" in marks:
                bracket = re.search(r"<strong>\s*\((.*?)\)\s*</strong>", text, re.S)
                values.append(_inline(bracket[1]) if bracket else None)
            else:
                choices.append(text)  # e.g. the list a matching question's items are matched against
        answer = values if values and None not in values else None

    words = lambda html: " ".join(BeautifulSoup(html, "html.parser").get_text(" ", strip=True).split())
    srcs = lambda html: " ".join(re.findall(r'src="([^"]+)"', html))
    key = " | ".join([q.prompt, *(f"{words(c)} {srcs(c)}".strip() for c in choices)]).lower()
    return Card(prompt, choices, answer, feedback, key, bool(choice_rows))


def _inline(html: str) -> str:
    """A short answer's text, keeping math and images as they are."""
    return " ".join(html.split())
