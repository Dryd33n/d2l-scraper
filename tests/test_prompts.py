import functools, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root
import questionary
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
import prompts
from courses import Course

courses = [
    Course(1, "", "Fall 2026 CSC 320", True, "202609"),
    Course(2, "", "Fall 2026 CSC 370", True, "202609"),
    Course(3, "", "Spring 2026 CSC 226", False, "202601"),
    Course(4, "", "Spring 2026 CSC 305", True, "202601"),
    Course(5, "", "Advising", True, None),
]
DOWN, SPACE, ENTER = "\x1b[B", " ", "\r"
real = questionary.checkbox

def run(keys):
    with create_pipe_input() as inp:
        inp.send_text(keys)
        prompts.questionary.checkbox = functools.partial(real, input=inp, output=DummyOutput())
        return prompts.select_courses(courses)

def check(name, got, want):
    ids = None if got is None else [c.id for c in got]
    print("PASS" if ids == want else f"FAIL (got {ids})", name)

from playwright.sync_api import sync_playwright
with sync_playwright():  # main.py prompts while Playwright's loop is running
    check("pick first + third selectable (skips disabled + separators)",
          run(SPACE + DOWN + DOWN + SPACE + ENTER), [1, 4])
    check("empty submit blocked by validation, then pick", run(ENTER + SPACE + ENTER), [1])
    check("toggle all skips disabled", run("a" + ENTER), [1, 2, 4, 5])
    check("ctrl-c cancels", run("\x03"), None)


    def run_cat(keys):
        with create_pipe_input() as inp:
            inp.send_text(keys)
            prompts.questionary.checkbox = functools.partial(real, input=inp, output=DummyOutput())
            return prompts.select_categories()

    def check_cat(name, got, want):
        print("PASS" if got == want else f"FAIL (got {got})", name)

    ALL = ["content", "classlist", "grades", "discussions", "assignments", "quizzes", "announcements", "calendar"]
    check_cat("categories default to all", run_cat(ENTER), ALL)
    check_cat("untick classlist + quizzes", run_cat(DOWN + SPACE + DOWN * 4 + SPACE + ENTER),
              [k for k in ALL if k not in ("classlist", "quizzes")])
    check_cat("untick all blocked, then pick first", run_cat("a" + ENTER + SPACE + ENTER), ["content"])
    check_cat("ctrl-c cancels", run_cat("\x03"), None)


    import pickle
    from prompts import DownloadOptions
    real_confirm = questionary.confirm
    FIXTURES = Path(__file__).resolve().parent / "fixtures"  # git-ignored: crawl pickles hold real course data
    with_videos = pickle.load(open(FIXTURES / "with_videos.pkl", "rb"))
    without_videos = pickle.load(open(FIXTURES / "without_videos.pkl", "rb"))

    real_path = questionary.path
    def run_opts(keys, data):
        with create_pipe_input() as inp:
            inp.send_text(keys)
            prompts.questionary.checkbox = functools.partial(real, input=inp, output=DummyOutput())
            prompts.questionary.confirm = functools.partial(real_confirm, input=inp, output=DummyOutput())
            prompts.questionary.path = functools.partial(real_path, input=inp, output=DummyOutput())
            return prompts.select_download_options(data)

    check_cat("videos default no, no markdown", run_opts(ENTER + ENTER + ENTER, with_videos), DownloadOptions(False, [], prompts.DEFAULT_OUTPUT))
    check_cat("videos yes + all markdown", run_opts("y" + "a" + ENTER + ENTER, with_videos),
              DownloadOptions(True, ["content", "announcements", "assignments", "discussions", "quizzes", "grades", "course_info"], prompts.DEFAULT_OUTPUT))
    check_cat("no videos found: skips video question", run_opts(SPACE + ENTER + ENTER, without_videos), DownloadOptions(False, ["content"], prompts.DEFAULT_OUTPUT))
    check_cat("ctrl-c on video question cancels", run_opts("\x03", with_videos), None)
    check_cat("ctrl-c on markdown cancels", run_opts("n" + "\x03", with_videos), None)

    import tempfile
    other = Path(tempfile.mkdtemp()) / "My Archive"
    CLEAR = "\x7f" * 200  # backspace over the default
    check_cat("custom output folder", run_opts(ENTER + ENTER + CLEAR + str(other) + ENTER, with_videos).output, other.resolve())
    inside = str(prompts.PROJECT_DIR / "archive")
    check_cat("folder inside repo rejected, then default accepted",
              run_opts(ENTER + ENTER + CLEAR + inside + ENTER + CLEAR + str(other) + ENTER, with_videos).output, other.resolve())
    check_cat("ctrl-c on output folder cancels", run_opts(ENTER + ENTER + "\x03", with_videos), None)
    check_cat("subfolder of the ignored archive folder accepted",
              run_opts(ENTER + ENTER + CLEAR + str(prompts.DEFAULT_OUTPUT / "Fall 2026") + ENTER, with_videos).output,
              (prompts.DEFAULT_OUTPUT / "Fall 2026").resolve())
    check_cat("default is the repo's D2L Archive folder", prompts.DEFAULT_OUTPUT, prompts.PROJECT_DIR / "D2L Archive")

# scraping profile
real_select = questionary.select

def run_profile(keys):
    with create_pipe_input() as inp:
        inp.send_text(keys)
        prompts.questionary.select = functools.partial(real_select, input=inp, output=DummyOutput())
        try:
            return prompts.select_profile()
        finally:
            prompts.questionary.select = real_select

def check_value(name, got, want):
    print("PASS" if got == want else f"FAIL (got {got!r})", name)

with sync_playwright():
    check_value("profile: enter keeps the default (fair)", run_profile(ENTER), "fair")
    check_value("profile: down picks aggressive", run_profile(DOWN + ENTER), "aggressive")
    check_value("profile: up picks polite", run_profile("\x1b[A" + ENTER), "polite")
    check_value("profile: ctrl-c cancels", run_profile("\x03"), None)
