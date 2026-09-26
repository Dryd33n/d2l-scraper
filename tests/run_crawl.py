from pathlib import Path
import pickle, sys, time
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root
from playwright.sync_api import sync_playwright
import auth, courses, crawl, review
from ui import console

IDS = {int(x) for x in sys.argv[2].split(",")}
with sync_playwright() as p:
    s = auth.connect(p)
    picked = [c for c in courses.list_courses(s) if c.id in IDS]
    t = time.time()
    crawls = crawl.crawl(s, picked, list(crawl.CATEGORIES))
    console.print(f"crawl took {time.time() - t:.1f}s")

pickle.dump(crawls, open(sys.argv[1], "wb"))
pages = [crawls] + [[c] for c in crawls]
for i, pg in enumerate(pages):
    console.print(review._panel(pg, i, len(pages)), width=100)
for c in crawls:
    for k, r in c.results.items():
        if r.error:
            console.print(c.course.short_name, k, r.error)

for c in crawls:
    ci = c.results["course_info"]
    console.print(c.course.short_name, "course info files:", [(f.name, f.size) for f in ci.files], "| calendar events:", c.results["calendar"].items)
    vids = [(f.name, f.size) for r in c.results.values() for f in r.files if f.is_video]
    if vids: console.print("  videos:", vids[:5])
