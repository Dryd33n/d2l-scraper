"""Markdown copies of generated pages, for the kinds chosen in the download options.

The HTML stays the complete copy; the Markdown is for reading, searching, and pasting elsewhere.
Images link to their files on disk rather than being embedded, so the text stays readable.
"""

import re

from markdownify import markdownify

BODY = re.compile(r"<body\b[^>]*>(.*)</body\s*>", re.I | re.S)
DROP = re.compile(r"<(script|style|noscript|head|template)\b.*?</\1\s*>", re.I | re.S)


def to_markdown(html: str) -> str:
    """Markdown from an HTML page or fragment: only the body, without scripts and styles."""
    if m := BODY.search(html):
        html = m[1]
    text = markdownify(DROP.sub("", html), heading_style="ATX", bullets="-")
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
