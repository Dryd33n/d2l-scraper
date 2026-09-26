import base64, re, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root
from courses import Course
from crawl import COURSE_FILES, CategoryResult, HtmlPage, crawl_category
from embed import (Ref, absolute, brightspace_link, canonical, css_refs, html_refs, is_lti, local_folder,
                   rewrite_css, rewrite_html, view_attachment)

def check(name, got, want):
    print("PASS" if got == want else f"FAIL (got {got!r})", name)

B = "https://bright.uvic.ca"
ENF = "/content/enforced/397411-202501CSC230A01-A04XCO"

# ---------- URLs ----------

check("absolute: root-relative", absolute("/shared/a.css", None), f"{B}/shared/a.css")
check("absolute: relative with base", absolute("img/a.png", f"{B}{ENF}/Lab/page.html"), f"{B}{ENF}/Lab/img/a.png")
check("absolute: relative without base", absolute("img/a.png", None), None)
check("absolute: skips data/mailto/fragment", [absolute(u, B + "/") for u in ("data:x", "mailto:a@b", "#top", "javascript:void(0)")], [None] * 4)
check("absolute: protocol-relative", absolute("//cdn.x/a.js", None), "https://cdn.x/a.js")

check("canonical: enforced, query dropped, spaces quoted", canonical(f"{B}{ENF}/Lab 1/a b.mp4?isCourseFile=true"), f"{ENF}/Lab%201/a%20b.mp4")
check("canonical: same file, different spelling", canonical(f"{B}{ENF}/Lab%201/x/../a%20b.mp4"), f"{ENF}/Lab%201/a%20b.mp4")
check("canonical: shared ../ normalised", canonical(f"{B}/shared/T/pages/../../_assets/css/s.css"), "/shared/_assets/css/s.css")
check("canonical: post image keeps fileId", canonical(f"{B}/d2l/le/1/discussions/posts/2/ViewAttachment?fileId=3&ou=1"), "/d2l/le/1/discussions/posts/2/ViewAttachment?fileId=3")
check("canonical: other hosts and pages ignored", [canonical(u) for u in ("https://x.com/content/enforced/a.pdf", f"{B}/d2l/home/1", f"{B}{ENF}/")], [None] * 3)
check("view_attachment", view_attachment("/d2l/le/1/discussions/posts/2/ViewAttachment?fileId=3"), (1, 2, 3))

check("local_folder: linked file mirrors folders", local_folder(f"{ENF}/Lab1_Videos/a%20b.mp4", False), (("Lab1_Videos",), "a b.mp4"))
check("local_folder: embedded file in _assets", local_folder(f"{ENF}/img/x.png", True), (("_assets",), "x.png"))
check("local_folder: linked shared file", local_folder("/shared/docs/guide.pdf", False), (("shared", "docs"), "guide.pdf"))

check("brightspace_link: quickLink rcode (any case)", brightspace_link(f"{B}/d2l/common/dialogs/quickLink/quickLink.d2l?ou=1&type=quiz&rCode=ABC-12"), ("rcode", "abc-12"))
check("brightspace_link: viewContent", brightspace_link(f"{B}/d2l/le/content/1/viewContent/55/View"), ("content", "55"))
check("brightspace_link: discussion thread", brightspace_link(f"{B}/d2l/le/1/discussions/threads/9/View"), ("thread", "9"))
check("brightspace_link: external", brightspace_link("https://example.com/d2l/le/content/1/viewContent/55/View"), None)
check("is_lti", (is_lti(f"{B}/d2l/common/dialogs/quickLink/quickLink.d2l?ou=1&type=lti&rcode=x"), is_lti(f"{B}/d2l/home")), (True, False))

# ---------- finding references ----------

page = f"""<html><head>
<link rel="stylesheet" href="/shared/T/css/s.css"><link rel="alternate" href="/shared/feed.xml">
<script src="/shared/T/js/a.js"></script>
<script>var tpl = '<img src="/shared/in-a-string.png">';</script>
<style>.b {{ background: url('img/bg.png') }}</style>
</head><body>
<img src="img/a.png" srcset="img/a@2x.png 2x"><a href="notes.pdf#page=2">notes</a>
<a href="https://example.com">x</a><a href="#top">top</a>
<div style="background-image: url(&quot;img/c.png&quot;)"></div>
<video src="/content/enforced/x/v.mp4" poster="img/p.jpg"></video>
</body></html>"""
base = f"{B}{ENF}/Lab/page.html"
refs = html_refs(page, base)
check("html_refs: embedded", sorted(r.url.removeprefix(B) for r in refs if r.embedded), sorted([
    "/shared/T/css/s.css", "/shared/T/js/a.js", f"{ENF}/Lab/img/bg.png", f"{ENF}/Lab/img/a.png", f"{ENF}/Lab/img/c.png", f"{ENF}/Lab/img/p.jpg"]))
check("html_refs: linked", sorted(r.url.removeprefix(B) for r in refs if not r.embedded),
      sorted([f"{ENF}/Lab/notes.pdf#page=2", "https://example.com", "/content/enforced/x/v.mp4"]))
check("html_refs: nothing from inside scripts", any("in-a-string" in r.url for r in refs), False)

css = """@import url("more.css");
@font-face { src: url(f.eot); src: url(f.eot?#iefix) format("embedded-opentype"), url(f.woff2) format("woff2"), url(f.woff) format("woff"); }
.x { background: url(../img/x.png) }"""
check("css_refs: import, woff2 and images only", [r.url for r in css_refs(css, f"{B}/shared/T/css/s.css")],
      [f"{B}/shared/T/css/more.css", f"{B}/shared/T/css/f.woff2", f"{B}/shared/T/img/x.png"])

# ---------- rewriting ----------

tmp = Path(tempfile.mkdtemp())
disk = {}
def put(key, content):
    path = tmp / key.strip("/").replace("?", "_")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    disk[key] = path

put("/shared/T/css/s.css", b".b{background:url(../img/bg.png)} @import 'more.css';")
put("/shared/T/css/more.css", b".more{color:red}")
put("/shared/T/img/bg.png", b"PNG1")
put("/shared/T/js/a.js", b"var s = '</script>';")
put(f"{ENF}/Lab/img/a.png", b"PNG2")
put(f"{ENF}/Lab/notes.pdf", b"%PDF")

class FakeLinks:
    def __init__(self, dest):
        self.dest = dest
    def local(self, url):
        return disk.get(canonical(url) or "")
    def internal(self, url):
        return "../quizzes/quizzes.html#quiz-7" if brightspace_link(url) == ("rcode", "q7") else None
    def href(self, target):
        import os
        return os.path.relpath(target, self.dest.parent).replace(os.sep, "/")

links = FakeLinks(tmp / "out" / "page.html")
out = rewrite_html(page.replace("<a href=\"#top\">", f'<a href="/d2l/common/dialogs/quickLink/quickLink.d2l?ou=1&amp;type=quiz&amp;rcode=Q7">')
                   + '<iframe src="/d2l/common/dialogs/quickLink/quickLink.d2l?ou=1&amp;type=lti&amp;rcode=L1"></iframe>'
                   + '<meta http-equiv="Content-Type" content="text/html; charset=windows-1252">', base, links)
b64 = lambda data: base64.b64encode(data).decode()
check("stylesheet inlined with its image and @import", f"url(\"data:image/png;base64,{b64(b'PNG1')}\")" in out and ".more{color:red}" in out and "<link rel=\"stylesheet\"" not in out, True)
check("unrelated <link> left alone", '<link rel="alternate" href="/shared/feed.xml">' in out, True)
check("script inlined, </script> escaped", "<script>var s = '<\\/script>';</script>" in out, True)
check("inline script untouched", "var tpl = '<img src=\"/shared/in-a-string.png\">';" in out, True)
check("image embedded and srcset dropped", f'<img src="data:image/png;base64,{b64(b"PNG2")}">' in out, True)
check("missing image made absolute", f'url("{B}{ENF}/Lab/img/bg.png")' in out and f'url(&quot;{B}{ENF}/Lab/img/c.png&quot;)' in out, True)
check("linked file relative, fragment kept", 'href="../content/enforced/397411-202501CSC230A01-A04XCO/Lab/notes.pdf#page=2"' in out, True)
check("quickLink to archived quiz", 'href="../quizzes/quizzes.html#quiz-7"' in out, True)
check("video not downloaded keeps absolute URL", f'src="{B}/content/enforced/x/v.mp4"' in out, True)
check("external link untouched", '<a href="https://example.com">' in out, True)
check("LTI iframe becomes a link box", "<iframe" not in out and "only works inside Brightspace" in out, True)
check("charset declared as utf-8", 'charset="utf-8"' in out and "windows-1252" not in out, True)
check("no base: relative links in generated pages untouched",
      rewrite_html('<a href="attachments/a.pdf">a</a><img src="../course-image.jpg">', None, links),
      '<a href="attachments/a.pdf">a</a><img src="../course-image.jpg">')
check("@import depth-limited on missing files", rewrite_css("@import 'nope.css';", f"{B}/shared/T/css/s.css", links),
      f'@import "{B}/shared/T/css/nope.css";')

# ---------- course files crawl (fake session) ----------

class FakeSession:
    def __init__(self, files):
        self.files = files  # path -> (bytes, content type)
        self.heads = []
    def head(self, path):
        self.heads.append(path)
        if path not in self.files:
            return False, None, {}
        data, ctype = self.files[path]
        headers = {"content-type": ctype}
        if "ViewAttachment" in path:
            headers["content-disposition"] = "inline; filename*=UTF-8''photo.png"
        return True, len(data), headers
    def fetch(self, path):
        return self.files[path][0]

course = Course(1, "", "Spring 2025 TEST 100", True, "202501")
html = f'<link rel="stylesheet" href="/shared/T/s.css"><img src="img/a.png"><a href="Lab1/v.mp4">v</a><a href="gone.pdf">g</a>'.encode()
session = FakeSession({
    "/shared/T/s.css": (b".x{background:url(bg.png)}", "text/css"),
    "/shared/T/bg.png": (b"PNG", "image/png"),
    f"{ENF}/img/a.png": (b"PNG", "image/png"),
    f"{ENF}/Lab1/v.mp4": (b"MP4" * 10, "video/mp4"),
    "/d2l/le/1/discussions/posts/5/ViewAttachment?fileId=77": (b"PNG", "image/png"),
})
content = CategoryResult(data={"Modules": []}, html_pages=[HtmlPage(9, ("01 Week",), "page.html", "/api/topics/9/file", f"{B}{ENF}/page.html", html)])
posts = [{"PostId": 5, "Attachments": [{"FileId": 6}], "Message": {"Html": '<img src="/d2l/le/1/discussions/posts/5/ViewAttachment?fileId=6"><img src="/d2l/le/1/discussions/posts/5/ViewAttachment?fileId=77">'}}]
discussions = CategoryResult(data=[{"forum": {}, "topics": [{"topic": {}, "posts": posts}]}])
result = crawl_category(session, course, COURSE_FILES, lambda _: None, {"content": content, "discussions": discussions})
got = {("/".join(f.path), f.name, f.data is not None) for f in result.files}
check("course files found", got, {
    ("_originals/01 Week", "page.html", True),
    ("_assets", "s.css", True),
    ("_assets", "a.png", False),
    ("_assets", "bg.png", False),
    ("Lab1", "v.mp4", False),
    ("_assets", "photo.png", False),
})
check("post image already attached isn't fetched again", "/d2l/le/1/discussions/posts/5/ViewAttachment?fileId=6" in session.heads, False)
check("missing file noted", result.note, "1 HTML page · 1 missing on Brightspace")
check("video counted as video", [f.name for f in result.files if f.is_video], ["v.mp4"])
