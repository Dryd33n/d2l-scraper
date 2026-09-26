"""Shared terminal styling: the rich console and the matching questionary style."""

import questionary
from rich.console import Console

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


def ok(message: str) -> None:
    console.print(f"[green]✓[/] {message}")


def warn(message: str) -> None:
    console.print(f"[yellow]![/] {message}")
