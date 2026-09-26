"""Shared terminal styling: the rich console and the matching questionary style."""

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

import questionary
from rich.console import Console

T = TypeVar("T")

console = Console(highlight=False)

ACCENT = "#5fafff"

PROMPT_STYLE = questionary.Style([
    ("qmark", f"fg:{ACCENT} bold"),
    ("question", "bold"),
    ("instruction", "fg:#808080 italic"),
    ("pointer", f"fg:{ACCENT} bold"),
    ("highlighted", f"fg:{ACCENT} bold"),
    ("selected", "fg:#87d787"),
    ("separator", "fg:#d7af5f bold"),
    ("disabled", "fg:#6c6c6c italic"),
    ("answer", f"fg:{ACCENT}"),
])


IRREGULAR_PLURALS = {"person": "people", "quiz": "quizzes", "group category": "group categories"}


def plural(n: int, noun: str) -> str:
    """plural(1, "quiz") -> "1 quiz", plural(2, "quiz") -> "2 quizzes"."""
    return f"{n} {noun if n == 1 else IRREGULAR_PLURALS.get(noun, noun + 's')}"


def format_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def in_thread(fn: Callable[[], T]) -> T:
    """Run an interactive prompt_toolkit app (questionary prompt, review screen) on its own thread.

    sync_playwright keeps an asyncio loop running on the main thread, and prompt_toolkit
    refuses to start its own loop there. A worker thread has no loop.
    """
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(fn).result()


def ok(message: str) -> None:
    console.print(f"[green]✓[/] {message}")


def warn(message: str) -> None:
    console.print(f"[yellow]![/] {message}")
