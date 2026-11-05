"""Markdown copies of generated pages, for the kinds chosen in the download options.

The HTML stays the complete copy; the Markdown is for reading, searching, and pasting elsewhere.
Images link to their files on disk rather than being embedded, so the text stays readable.
"""

import html as htmllib
import re

from markdownify import markdownify

BODY = re.compile(r"<body\b[^>]*>(.*)</body\s*>", re.I | re.S)
DROP = re.compile(r"<(script|style|noscript|head|template)\b.*?</\1\s*>", re.I | re.S)
MATH = re.compile(r"<math\b.*?</math\s*>", re.I | re.S)
LATEX = re.compile(r"""<annotation\b[^>]*encoding=["']latex["'][^>]*>(.*?)</annotation\s*>""", re.I | re.S)
ANNOTATION = re.compile(r"<annotation(-xml)?\b.*?</annotation(-xml)?\s*>", re.I | re.S)


def to_markdown(html: str) -> str:
    """Markdown from an HTML page or fragment: only the body, without scripts and styles."""
    if m := BODY.search(html):
        html = m[1]
    formulas = []

    def hold(m) -> str:  # kept out of markdownify, which would escape the LaTeX
        formulas.append(_formula(m[0]))
        return f"MATHFORMULA{len(formulas) - 1}X"

    text = markdownify(MATH.sub(hold, DROP.sub("", html)), heading_style="ATX", bullets="-")
    text = re.sub(r"MATHFORMULA(\d+)X", lambda m: formulas[int(m[1])], text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def _formula(math: str) -> str:
    """A MathML formula as $LaTeX$ when it carries its source (Brightspace's equation editor adds it),
    otherwise as its plain text."""
    if m := LATEX.search(math):
        source = htmllib.unescape(m[1]).strip()
        if wrapped := re.search(r'"math"\s*:\s*"(.*)"\s*}\s*$', source, re.S):  # {"version":"1.1","math":"\(…\)"}
            source = wrapped[1]
        source = re.sub(r"^\\[(\[]|\\[)\]]$", "", source.strip()).strip()
        if source:
            return f"${source}$"
    return " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", ANNOTATION.sub("", math))).split())
