"""Interactive terminal prompts for choosing what to archive."""

from dataclasses import dataclass
from pathlib import Path

import questionary

from auth import DEFAULT_PROFILE, PROFILES
from courses import Course, by_term
from crawl import CATEGORIES, COURSE_INFO, CourseCrawl, total_size
from ui import PROMPT_STYLE, format_size, in_thread, plural

INSTRUCTION = "(space toggle · a all · enter confirm)"

# Generated pages that can get a Markdown copy. Downloaded files are never converted.
MARKDOWN_KINDS = {
    "content": "Content pages (HTML topics)",
    "announcements": "Announcements",
    "assignments": "Assignments",
    "discussions": "Discussions",
    "quizzes": "Quizzes",
    "grades": "Grades",
    COURSE_INFO: "Course info",
}


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = PROJECT_DIR / "D2L Archive"  # git-ignored (.gitignore); archives hold classmates' personal data


@dataclass
class DownloadOptions:
    videos: bool
    markdown: list[str]  # keys of MARKDOWN_KINDS to also save as .md
    output: Path = DEFAULT_OUTPUT
    profile: str = DEFAULT_PROFILE  # key of auth.PROFILES, chosen right after login


def _check_output(text: str) -> bool | str:
    path = Path(text).expanduser().resolve()
    in_repo = path == PROJECT_DIR or PROJECT_DIR in path.parents
    in_ignored = path == DEFAULT_OUTPUT or DEFAULT_OUTPUT in path.parents
    if in_repo and not in_ignored:
        # only the default archive folder is git-ignored; anywhere else in the repo could get committed
        return f"Inside this repository, only '{DEFAULT_OUTPUT.name}' is git-ignored. Use it or a folder outside the repo"
    if path.exists() and not path.is_dir():
        return "That's a file, not a folder"
    return True


def select_profile() -> str | None:
    """Ask how hard to hit the server (how many requests run at once). Returns a key of PROFILES, or None if cancelled."""
    choices = [questionary.Choice(title=f"{p.name} ({p.workers} at a time)", value=key, description=p.description)
               for key, p in PROFILES.items()]
    return in_thread(questionary.select(
        "Scraping profile:",
        choices=choices,
        default=next(c for c in choices if c.value == DEFAULT_PROFILE),
        instruction="(↑/↓ choose · enter confirm)",
        style=PROMPT_STYLE,
    ).ask)


def select_categories() -> list[str] | None:
    """Show a checkbox list of content categories, all checked. Returns keys, or None if cancelled."""
    return in_thread(questionary.checkbox(
        "What should be downloaded?",
        choices=[questionary.Choice(title=label, value=key, checked=True)
                 for key, label in CATEGORIES.items()],
        instruction=INSTRUCTION,
        validate=lambda picked: bool(picked) or "Select at least one category",
        style=PROMPT_STYLE,
    ).ask)


def select_download_options(crawls: list[CourseCrawl]) -> DownloadOptions | None:
    """Ask whether to download videos, which generated pages to also save as Markdown, and where to save.

    The video question is skipped when the crawl found no videos. Returns None if the user cancels.
    """
    videos = [f for c in crawls for r in c.results.values() if r.error is None for f in r.files if f.is_video]
    include_videos = False
    if videos:
        include_videos = in_thread(questionary.confirm(
            f"Download videos? ({plural(len(videos), 'video')}, {format_size(total_size(videos))})",
            default=False,
            style=PROMPT_STYLE,
        ).ask)
        if include_videos is None:
            return None

    crawled = set(crawls[0].results)
    markdown = in_thread(questionary.checkbox(
        "Also save Markdown copies of:",
        choices=[questionary.Choice(title=label, value=key)
                 for key, label in MARKDOWN_KINDS.items() if key in crawled],
        instruction="(space toggle · a all · enter confirm, none is fine)",
        style=PROMPT_STYLE,
    ).ask)
    if markdown is None:
        return None

    output = in_thread(questionary.path(
        "Save the archive to:",
        default=str(DEFAULT_OUTPUT),
        only_directories=True,
        validate=_check_output,
        style=PROMPT_STYLE,
    ).ask)
    if output is None:
        return None
    return DownloadOptions(videos=include_videos, markdown=markdown, output=Path(output).expanduser().resolve())


def select_courses(courses: list[Course]) -> list[Course] | None:
    """Show a checkbox list of courses grouped by term. Returns None if the user cancels."""
    choices = []
    for label, group in by_term(courses):
        if choices:
            choices.append(questionary.Separator(" "))  # blank line between terms
        choices.append(questionary.Separator(f"── {label} ──"))
        for c in group:
            choices.append(questionary.Choice(
                title=c.short_name,
                value=c,
                disabled=None if c.can_access else "no access",
            ))

    return in_thread(questionary.checkbox(
        "Which courses should be archived?",
        choices=choices,
        instruction=INSTRUCTION,
        validate=lambda picked: bool(picked) or "Select at least one course",
        style=PROMPT_STYLE,
    ).ask)
