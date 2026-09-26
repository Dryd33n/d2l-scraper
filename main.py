"""D2L scraper entry point: log in, pick courses and categories."""

import sys

from playwright.sync_api import sync_playwright
from rich.table import Table

from auth import BASE_URL, connect
from courses import list_courses
from prompts import CATEGORIES, select_categories, select_courses
from ui import ACCENT, console, ok, warn


def main() -> None:
    console.rule(f"[bold {ACCENT}]D2L Scraper[/] [dim]· {BASE_URL.removeprefix('https://')}[/]")

    with sync_playwright() as p:
        session = connect(p)

        with console.status("Loading courses..."):
            courses = list_courses(session)
        accessible = sum(c.can_access for c in courses)
        ok(f"Found {len(courses)} courses [dim]({accessible} accessible)[/]")
        console.print()

        selected = select_courses(courses)
        if selected is None:
            warn("Cancelled.")
            sys.exit(1)

        categories = select_categories()
        if categories is None:
            warn("Cancelled.")
            sys.exit(1)

        table = Table(title="Selection", title_style="bold", header_style=f"bold {ACCENT}")
        table.add_column("Term")
        table.add_column("Course")
        table.add_column("ID", justify="right", style="dim")
        for c in selected:
            table.add_row(c.term_label, c.short_name, str(c.id))

        console.print()
        console.print(table)
        console.print(f"[bold]Categories:[/] {', '.join(CATEGORIES[k] for k in categories)}")


if __name__ == "__main__":
    main()
