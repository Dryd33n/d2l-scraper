"""D2L scraper entry point: log in, pick courses and categories, crawl, review, choose options, download."""

import sys
from datetime import datetime

from playwright.sync_api import sync_playwright
from rich.markup import escape

from auth import BASE_URL, PROFILES, connect
from courses import list_courses
from crawl import crawl
from download import Summary, download
from prompts import (DownloadOptions, select_categories, select_courses, select_download_options, select_profile,
                     select_study_packs)
from review import review
from ui import ACCENT, console, format_size, ok, plural, warn


def main() -> None:
    console.rule(f"[bold {ACCENT}]D2L Scraper[/] [dim]· {BASE_URL.removeprefix('https://')}[/]")

    with sync_playwright() as p:
        session = connect(p)

        profile = select_profile()
        if profile is None:
            warn("Cancelled.")
            sys.exit(1)
        session.set_workers(PROFILES[profile].workers)

        with console.status("Loading courses..."):
            courses = list_courses(session)
        accessible = sum(c.can_access for c in courses)
        ok(f"Found {len(courses)} courses [dim]({accessible} accessible)[/]")
        console.print()

        selected = select_courses(courses)
        if selected is None:
            warn("Cancelled.")
            sys.exit(1)

        study_packs = select_study_packs(selected)
        if study_packs is None:
            warn("Cancelled.")
            sys.exit(1)

        categories = select_categories()
        if categories is None:
            warn("Cancelled.")
            sys.exit(1)

        console.print()
        started = datetime.now().astimezone()
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
        options.profile = profile
        options.study_packs = study_packs
        summary = download(p, session, crawls, options, started)
        print_summary(summary, options)


def print_summary(summary: Summary, options: DownloadOptions) -> None:
    ok(f"Downloaded {plural(summary.downloaded, 'file')} [dim]({format_size(summary.downloaded_bytes)})[/]")
    if summary.skipped_existing:
        ok(f"Skipped {plural(summary.skipped_existing, 'file')} already in the archive")
    if summary.skipped_videos:
        ok(f"Skipped {plural(summary.skipped_videos, 'video')} [dim](not opted in)[/]")
    if summary.pages:
        copies = f" [dim](+ {summary.markdown} as Markdown)[/]" if summary.markdown else ""
        ok(f"Wrote {plural(summary.pages, 'page')}{copies}")
    for path, reason in summary.failed[:10]:
        console.print(f"[red]✗[/] {escape(str(path.relative_to(options.output)))} [dim]{escape(reason)}[/]")
    if len(summary.failed) > 10:
        console.print(f"[red]✗[/] …and {len(summary.failed) - 10} more failures")
    for log in summary.courses:
        if pack := log.study_pack:
            ok(f"Study pack for {escape(log.crawl.course.short_name)}: {plural(len(pack.written), 'source')}"
               f"{' [dim](' + str(len(pack.left_out)) + ' left out, see manifest.md)[/]' if pack.left_out else ''}")
    console.print(f"\nArchive: [bold]{escape(str(options.output))}[/]")
    if any(log.study_pack for log in summary.courses):
        console.print(f"Study packs: [bold]{escape(str(options.output / 'Study Packs'))}[/] "
                      "[dim](upload each pack's files, except manifest.md, to a NotebookLM notebook)[/]")
    if summary.log:
        console.print(f"Log: [bold]{escape(str(summary.log))}[/] [dim](and one in each course folder)[/]")


if __name__ == "__main__":
    main()
