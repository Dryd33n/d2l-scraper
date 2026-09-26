from pathlib import Path
import pickle, sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from playwright.sync_api import sync_playwright
import crawl, review

FIXTURES = Path(__file__).resolve().parent / "fixtures"  # git-ignored: crawl pickles hold real course data
crawls = pickle.load(open(sys.argv[1] if len(sys.argv) > 1 else FIXTURES / "with_videos.pkl", "rb"))
cats = list(crawl.CATEGORIES)
LEFT, RIGHT, ENTER = "\x1b[D", "\x1b[C", "\r"

seen = []
real_panel = review._panel
def spy(pg, page, pages):
    seen.append(page)
    return real_panel(pg, page, pages)
review._panel = spy

def run(keys, data=crawls):
    seen.clear()
    with create_pipe_input() as inp:
        inp.send_text(keys)
        result = review.review(data, input=inp, output=DummyOutput())
    return result, seen[-1]

def check(name, got, want):
    print("PASS" if got == want else f"FAIL (got {got})", name)

with sync_playwright():  # same conditions as main.py
    check("enter proceeds on totals page", run(ENTER), (True, 0))
    check("right twice -> page 2", run(RIGHT + RIGHT + ENTER), (True, 2))
    check("left wraps to last page", run(LEFT + ENTER), (True, len(crawls)))
    check("right wraps to first page", run(RIGHT * (len(crawls) + 1) + ENTER), (True, 0))
    check("h/l also navigate", run("l" + "l" + "h" + ENTER), (True, 1))
    check("q cancels", run(RIGHT + "q")[0], False)
    check("ctrl-c cancels", run("\x03")[0], False)
    check("single course: no totals page", run(RIGHT + ENTER, crawls[:1]), (True, 0))

# every page must render at the same height so the box doesn't jump when switching
heights = {review._to_ansi(real_panel(pg, i, len(crawls) + 1), 80).count("\n")
           for i, pg in enumerate([crawls] + [[c] for c in crawls])}
check("all pages same height at 80 cols", len(heights), 1)


