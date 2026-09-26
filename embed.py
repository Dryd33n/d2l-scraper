"""Finding and rewriting the references inside Brightspace HTML.

The crawl uses `html_refs` and `css_refs` to find the files a page depends on. The download uses
`rewrite_html` to make a page work offline: images, stylesheets, and scripts are embedded; course
files are linked to their downloaded copies; Brightspace links point at the archived pages; embedded
tools that only work inside Brightspace become a visible link.
"""

import base64
import html
import mimetypes
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit

from auth import BASE_URL

HOST = urlsplit(BASE_URL).netloc
SAFE = "/()!$'*+,;=:@-._~&"  # characters left unescaped in canonical paths

# which attribute of which tag holds a reference, and whether its target is embedded into the page
# (True) or linked to (False); <link> only counts for stylesheets and icons, <script> is handled as a block
ATTRS = {
    ("img", "src"): True,
    ("video", "poster"): True,
    ("link", "href"): True,
    ("a", "href"): False,
    ("iframe", "src"): False,
    ("source", "src"): False,
    ("video", "src"): False,
    ("audio", "src"): False,
    ("embed", "src"): False,
}
TAG = re.compile(r"<(img|video|link|a|iframe|source|audio|embed)\b([^>]*)>", re.I)
ATTR = re.compile(r"""(\s)([\w:-]+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s"'>]+))?""")
BLOCK = re.compile(r"<(script|style)\b([^>]*)>(.*?)</\1\s*>", re.I | re.S)
STYLE_ATTR = re.compile(r"""(\sstyle\s*=\s*)("[^"]*"|'[^']*')""", re.I)
IFRAME = re.compile(r"<iframe\b([^>]*)>.*?</iframe\s*>", re.I | re.S)
META_CHARSET = re.compile(r"""<meta\b[^>]*charset\s*=\s*["']?[\w-]+[^>]*>""", re.I)
CSS_URL = re.compile(r"""url\(\s*(['"]?)([^'")]+?)\1\s*\)(\s*format\(\s*['"]?([\w-]+)['"]?\s*\))?""", re.I)
CSS_IMPORT = re.compile(r"""@import\s+(?:url\(\s*)?(['"]?)([^'")\s;]+)\1\s*\)?([^;]*);""", re.I)
VIEW_ATTACHMENT = re.compile(r"^/d2l/le/(\d+)/discussions/posts/(\d+)/ViewAttachment$", re.I)

FONT_EXTENSIONS = {".woff", ".woff2", ".ttf", ".otf", ".eot"}
MIME = {".woff2": "font/woff2", ".woff": "font/woff", ".svg": "image/svg+xml", ".webp": "image/webp", ".js": "text/javascript"}


@dataclass(frozen=True)
class Ref:
    url: str  # absolute URL
    embedded: bool  # embedded into the page (image, stylesheet, script) rather than linked to


class Links(Protocol):
    """What rewriting needs to know about the archive."""
    def local(self, url: str) -> Path | None: ...  # the downloaded copy of a Brightspace file, if on disk
    def internal(self, url: str) -> str | None: ...  # href to the archived copy of a Brightspace page
    def href(self, target: Path) -> str: ...  # relative href from the page being written


# ---------- URLs ----------

def _attr_value(raw: str | None) -> str | None:
    if raw is None:
        return None
    if raw[:1] in "\"'":
        raw = raw[1:-1]
    return html.unescape(raw).strip()


def _get_attr(attrs: str, name: str) -> str | None:
    return next((_attr_value(v) for _, k, v in ATTR.findall(attrs) if k.lower() == name), None)


def absolute(url: str, base: str | None) -> str | None:
    """The absolute URL of a reference, or None for ones that can't be resolved (fragments, data:,
    mailto:, javascript:, and relative references when there's no base)."""
    if not url or url.startswith("#") or re.match(r"^(data|mailto|javascript|tel):", url, re.I):
        return None
    if url.startswith("//"):
        return "https:" + url
    if re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I):
        return url
    if url.startswith("/"):
        return urljoin(BASE_URL, url)
    return urljoin(base, url) if base else None


def canonical(url: str) -> str | None:
    """The site path of a downloadable Brightspace file ("/content/enforced/…", "/shared/…", or a
    discussion post image), normalised so every spelling of the same file gives the same key."""
    parts = urlsplit(url)
    if parts.netloc.lower() != HOST:
        return None
    path = posixpath.normpath(unquote(parts.path))
    if VIEW_ATTACHMENT.match(path):
        file_id = parse_qs(parts.query).get("fileId", [""])[0]
        return f"{path}?fileId={file_id}" if file_id.isdigit() else None
    if not (path.startswith("/content/enforced/") or path.startswith("/shared/")) or parts.path.endswith("/"):
        return None
    return quote(path, safe=SAFE)


def view_attachment(key: str) -> tuple[int, int, int] | None:
    """(course id, post id, file id) for a discussion post image key from `canonical`."""
    path, _, file_id = key.partition("?fileId=")
    m = VIEW_ATTACHMENT.match(path)
    return (int(m[1]), int(m[2]), int(file_id)) if m else None


def local_folder(key: str, embedded: bool) -> tuple[tuple[str, ...], str]:
    """Where a course file goes inside _course-files: embedded assets flat in _assets, linked files
    mirroring their Brightspace folders (/content/enforced/<course>/Lab9_Videos/a.mp4 -> Lab9_Videos/a.mp4)."""
    parts = [p for p in unquote(key.partition("?")[0]).split("/") if p]
    name = parts[-1]
    if embedded or view_attachment(key):
        return ("_assets",), name
    if parts[:2] == ["content", "enforced"]:
        return tuple(parts[3:-1]), name  # parts[2] is the course's own folder
    return ("shared", *parts[1:-1]), name


def is_lti(url: str) -> bool:
    return bool(re.search(r"[?&]type=lti\b|/d2l/le/lti/|/d2l/lti/", url, re.I))


def brightspace_link(url: str) -> tuple[str, str] | None:
    """What a link to a Brightspace page points at, as (kind, id): ("rcode", …) for quickLinks,
    ("content", topic), ("topic", id), ("thread", id), ("dropbox", folder), ("quiz", id)."""
    parts = urlsplit(url)
    if parts.netloc.lower() != HOST:
        return None
    path, query = parts.path, {k.lower(): v[0] for k, v in parse_qs(parts.query).items()}
    if path.lower().endswith("/quicklink/quicklink.d2l") and query.get("rcode"):
        return "rcode", query["rcode"].lower()
    if m := re.match(r"^/d2l/le/content/\d+/viewContent/(\d+)/View", path, re.I):
        return "content", m[1]
    if m := re.match(r"^/d2l/le/\d+/discussions/(topic|thread)s/(\d+)/View", path, re.I):
        return m[1].lower(), m[2]
    if "/dropbox/" in path.lower() and query.get("db", "").isdigit():
        return "dropbox", query["db"]
    if "/quizzing/" in path.lower() and query.get("qi", "").isdigit():
        return "quiz", query["qi"]
    return None


def _is_embedded_link(attrs: str) -> bool:
    return bool(re.search(r"stylesheet|icon", _get_attr(attrs, "rel") or "", re.I))


def _wanted_font(url: str, fmt: str | None) -> bool:
    """Only woff2 fonts are embedded. Browsers use the first format they support, every current one
    supports woff2, so the other formats would only make pages bigger. Non-font URLs are always wanted."""
    suffix = posixpath.splitext(urlsplit(url).path)[1].lower()
    if fmt:
        return fmt.lower() == "woff2"
    return suffix not in FONT_EXTENSIONS or suffix == ".woff2"


def _split(text: str) -> Iterator[tuple[bool, "str | re.Match"]]:
    """Walk an HTML string as markup between <script>/<style> blocks, (False, str), and the blocks
    themselves, (True, match). Tags are never looked for inside a block: scripts often hold HTML in strings."""
    pos = 0
    for m in BLOCK.finditer(text):
        yield False, text[pos:m.start()]
        yield True, m
        pos = m.end()
    yield False, text[pos:]


# ---------- finding references (crawl) ----------

def html_refs(text: str, base: str | None) -> list[Ref]:
    """Every reference in an HTML page or fragment, including those inside its CSS."""
    refs = []
    for is_block, part in _split(text):
        if is_block:
            if part[1].lower() == "style":
                refs += css_refs(part[3], base)
            elif (src := _get_attr(part[2], "src")) and (url := absolute(src, base)):
                refs.append(Ref(url, True))
            continue
        for m in TAG.finditer(part):
            tag, attrs = m[1].lower(), m[2]
            if tag == "link" and not _is_embedded_link(attrs):
                continue
            for _, name, raw in ATTR.findall(attrs):
                embedded = ATTRS.get((tag, name.lower()))
                if embedded is not None and (url := absolute(_attr_value(raw) or "", base)):
                    refs.append(Ref(url, embedded))
        for m in STYLE_ATTR.finditer(part):
            refs += css_refs(_attr_value(m[2]) or "", base)
    return refs


def css_refs(css: str, base: str | None) -> list[Ref]:
    refs = [Ref(url, True) for m in CSS_IMPORT.finditer(css) if (url := absolute(m[2], base))]
    for m in CSS_URL.finditer(css):
        url = absolute(m[2].strip(), base)
        if url and _wanted_font(url, m[4]):
            refs.append(Ref(url, True))
    return list(dict.fromkeys(refs))  # @import url(...) matches both patterns


# ---------- rewriting (download) ----------

def decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def data_uri(path: Path) -> str:
    mime = MIME.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _set_attr(attrs: str, name: str, value: str | None) -> str:
    """Replace (or with None, remove) one attribute in a tag's attribute string."""
    def repl(m):
        if m[2].lower() != name:
            return m[0]
        return "" if value is None else f'{m[1]}{m[2]}="{html.escape(value)}"'
    return ATTR.sub(repl, attrs)


def rewrite_css(css: str, base: str | None, links: Links, depth: int = 0) -> str:
    """Embed a stylesheet's images and woff2 fonts and inline its @imports; anything not downloaded
    gets an absolute URL."""
    def import_(m):
        url = absolute(m[2], base)
        path = links.local(url) if url else None
        if path is None or depth >= 3:
            return f'@import "{url or m[2]}"{m[3]};'
        return rewrite_css(decode(path.read_bytes()), url, links, depth + 1)

    def url_(m):
        url = absolute(m[2].strip(), base)
        if url is None:
            return m[0]
        path = links.local(url) if _wanted_font(url, m[4]) else None
        return f'url("{data_uri(path) if path else url}")' + (m[3] or "")

    return CSS_URL.sub(url_, CSS_IMPORT.sub(import_, css))


def rewrite_html(text: str, base: str | None, links: Links, embed: bool = True) -> str:
    """Rewrite every reference in an HTML page or fragment (see the module docstring). With no base,
    relative references are left alone, which keeps the generated pages' own relative links intact.
    With embed=False (for Markdown copies) images link to their files on disk instead of being
    embedded, and scripts and stylesheets are left as they are."""

    def block(m) -> str:
        if not embed:
            return m[0]
        kind, attrs, body = m[1].lower(), m[2], m[3]
        if kind == "style":
            return f"<{m[1]}{attrs}>{rewrite_css(body, base, links)}</{m[1]}>"
        src = _get_attr(attrs, "src")
        url = absolute(src, base) if src else None
        if url is None:
            return m[0]
        path = links.local(url)
        if path is None:
            return f"<script{_set_attr(attrs, 'src', url)}></script>"
        attrs = _set_attr(_set_attr(_set_attr(attrs, "src", None), "integrity", None), "crossorigin", None)
        js = decode(path.read_bytes()).replace("</script", "<\\/script")
        return f"<script{attrs}>{js}</script>"

    def iframe(m) -> str:
        src = _get_attr(m[1], "src")
        url = absolute(src, base) if src else None
        if not url or not is_lti(url):
            return m[0]
        return (
            '<div style="border:1px solid #d1d9e0;border-radius:8px;padding:.75rem 1rem;margin:.75rem 0">'
            "Embedded content that only works inside Brightspace. "
            f'<a href="{html.escape(url)}">Open it in Brightspace</a></div>'
        )

    def link_tag(m, attrs: str) -> str:
        url = absolute(_get_attr(attrs, "href") or "", base)
        path = links.local(url) if url and embed else None
        if path is not None and re.search(r"stylesheet", _get_attr(attrs, "rel") or "", re.I):
            media = _get_attr(attrs, "media")
            media_attr = f' media="{html.escape(media)}"' if media else ""
            css = rewrite_css(decode(path.read_bytes()), url, links).replace("</style", "<\\/style")
            return f"<style{media_attr}>{css}</style>"
        if path is not None:  # icon
            return f"<{m[1]}{_set_attr(attrs, 'href', data_uri(path))}>"
        return f"<{m[1]}{_set_attr(attrs, 'href', url)}>" if url else m[0]

    def tag(m) -> str:
        name, attrs = m[1].lower(), m[2]
        if name == "link":
            return link_tag(m, attrs) if _is_embedded_link(attrs) else m[0]
        for _, attr, raw in ATTR.findall(attrs):
            embedded = ATTRS.get((name, attr.lower()))
            url = absolute(_attr_value(raw) or "", base) if embedded is not None else None
            if url is None:
                continue
            path = links.local(url)
            if embedded:
                value = (data_uri(path) if embed else links.href(path)) if path else url
                if path and name == "img":
                    attrs = _set_attr(attrs, "srcset", None)  # would otherwise win over the embedded src
            elif path is not None:
                fragment = urlsplit(url).fragment
                value = links.href(path) + (f"#{fragment}" if fragment else "")
            else:
                value = links.internal(url) or url
            attrs = _set_attr(attrs, attr.lower(), value)
        return f"<{m[1]}{attrs}>"

    def markup(part: str) -> str:
        part = META_CHARSET.sub('<meta charset="utf-8">', part)  # the page is written as UTF-8
        part = STYLE_ATTR.sub(lambda m: f'{m[1]}"{html.escape(rewrite_css(_attr_value(m[2]) or "", base, links))}"', part)
        part = IFRAME.sub(iframe, part)
        return TAG.sub(tag, part)

    return "".join(block(part) if is_block else markup(part) for is_block, part in _split(text))
