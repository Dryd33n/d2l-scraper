"""Interactive terminal prompts for choosing what to archive."""

from concurrent.futures import ThreadPoolExecutor

import questionary

from courses import Course, by_term
from ui import PROMPT_STYLE


def _ask(question: questionary.Question):
    """Run a prompt on its own thread.

    sync_playwright keeps an asyncio loop running on the main thread, and questionary
    (prompt_toolkit) refuses to start its own loop there. A worker thread has no loop.
    """
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(question.ask).result()


CATEGORIES = {
    "content": "Content",
    "classlist": "Classlist",
    "grades": "Grades",
    "discussions": "Discussions",
    "assignments": "Assignments",
    "quizzes": "Quizzes",
    "announcements": "Announcements",
}


INSTRUCTION = "(space toggle · a all · enter confirm)"


def select_categories() -> list[str] | None:
    """Show a checkbox list of content categories, all checked. Returns keys, or None if cancelled."""
    return _ask(questionary.checkbox(
        "What should be downloaded?",
        choices=[questionary.Choice(title=label, value=key, checked=True)
                 for key, label in CATEGORIES.items()],
        instruction=INSTRUCTION,
        validate=lambda picked: bool(picked) or "Select at least one category",
        style=PROMPT_STYLE,
    ))


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

    return _ask(questionary.checkbox(
        "Which courses should be archived?",
        choices=choices,
        instruction=INSTRUCTION,
        validate=lambda picked: bool(picked) or "Select at least one course",
        style=PROMPT_STYLE,
    ))
