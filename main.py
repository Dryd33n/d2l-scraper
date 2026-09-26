"""D2L scraper entry point: log in, pick courses and categories, crawl, review, choose options, download."""

import sys

from playwright.sync_api import sync_playwright
from rich.markup import escape

from auth import BASE_URL, connect
from courses import list_courses
from crawl import crawl
from download import Summary, download
from prompts import DownloadOptions, select_categories, select_courses, select_download_options
from review import review
from ui import ACCENT, console, format_size, ok, plural, warn


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
        summary = download(p, session, crawls, options)
        print_summary(summary, options)


def print_summary(summary: Summary, options: DownloadOptions) -> None:
    ok(f"Downloaded {plural(summary.downloaded, 'file')} [dim]({format_size(summary.downloaded_bytes)})[/]")
    if summary.skipped_existing:
        ok(f"Skipped {plural(summary.skipped_existing, 'file')} already in the archive")
    if summary.skipped_videos:
        ok(f"Skipped {plural(summary.skipped_videos, 'video')} [dim](not opted in)[/]")
    if options.markdown:
        warn("Markdown copies aren't implemented yet; nothing was converted.")
    for path, reason in summary.failed[:10]:
        console.print(f"[red]✗[/] {escape(str(path.relative_to(options.output)))} [dim]{escape(reason)}[/]")
    if len(summary.failed) > 10:
        console.print(f"[red]✗[/] …and {len(summary.failed) - 10} more failures")
    console.print(f"\nArchive: [bold]{escape(str(options.output))}[/]")


if __name__ == "__main__":
    main()
