"""D2L scraper entry point: log in, pick courses and categories, crawl, review, choose download options."""

import sys

from playwright.sync_api import sync_playwright

from auth import BASE_URL, connect
from courses import list_courses
from crawl import crawl
from prompts import MARKDOWN_KINDS, select_categories, select_courses, select_download_options
from review import review
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

        console.print()
        crawls = crawl(session, selected, categories)
        ok(f"Crawled {len(selected)} course{'s' if len(selected) > 1 else ''}")
        console.print()

        if not review(crawls):
            warn("Cancelled, nothing downloaded.")
            sys.exit(1)

        console.print()
        options = select_download_options(crawls)
        if options is None:
            warn("Cancelled, nothing downloaded.")
            sys.exit(1)

        console.print()
        ok(f"Videos: {'included' if options.videos else 'skipped (recorded as links)'}")
        markdown = ", ".join(MARKDOWN_KINDS[k] for k in options.markdown) or "none"
        ok(f"Markdown copies: {markdown}")
        warn("Downloading isn't implemented yet.")


if __name__ == "__main__":
    main()
