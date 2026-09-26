"""Review screen: one box of counts and sizes, with ←/→ to page between courses."""

import io
import shutil

from prompt_toolkit import Application
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from crawl import LABELS, CategoryResult, CourseCrawl, RemoteFile, total_size, unknown_sizes
from ui import ACCENT, format_size, in_thread, plural

MAX_WIDTH = 110


def _files(results: list[CategoryResult], videos: bool) -> list[RemoteFile]:
    """Files from the crawlable results, either only videos or only everything else."""
    return [f for r in results if r.error is None for f in r.files if f.is_video == videos]


def _row(key: str, results: list[CategoryResult]) -> list[str]:
    """Table cells for one category, summed over one or more courses. Videos are counted separately."""
    ok = [r for r in results if r.error is None]
    failed = [r for r in results if r.error is not None]
    if not ok:
        return [LABELS[key], "[dim]–[/]", "[dim]–[/]", "[dim]–[/]", f"[red]{escape(failed[0].error)}[/]"]

    non_video = _files(ok, videos=False)
    files = len(non_video)
    size = total_size(non_video)
    links = sum(r.links for r in ok)
    unknown = unknown_sizes(non_video)

    notes = []
    if len(results) == 1 and ok[0].note:
        notes.append(escape(ok[0].note))
    if links:
        notes.append(f"{links} links")
    if unknown:
        notes.append(f"[yellow]{unknown} unknown sizes[/]")
    if failed:
        notes.append(f"[red]unavailable in {len(failed)} course{'s' if len(failed) > 1 else ''}[/]")

    items = sum(r.items for r in ok)
    count, unit = plural(items, ok[0].unit).split(" ", 1)
    cells = [
        LABELS[key],
        f"{count} [dim]{unit}[/]",
        str(files) if files else "0",
        format_size(size) if files else "–",
        " · ".join(notes),
    ]
    if not items and not failed:
        cells = [f"[dim]{cell}[/]" for cell in cells]  # nothing here: fade the whole row
    return cells


def _videos_row(videos: list[RemoteFile]) -> list[str]:
    if not videos:
        return ["[dim]Videos[/]", "", "[dim]0[/]", "[dim]–[/]", ""]
    return ["Videos", "", str(len(videos)), format_size(total_size(videos)), "[yellow]optional, asked next[/]"]


def _panel(crawls: list[CourseCrawl], page: int, pages: int) -> Panel:
    """The box for one page: a single course, or all courses combined when len(crawls) > 1."""
    all_results = [r for c in crawls for r in c.results.values()]
    non_video, videos = _files(all_results, videos=False), _files(all_results, videos=True)
    with_videos = f"+ {format_size(total_size(videos))} with videos" if videos else ""

    table = Table(
        box=box.SIMPLE, show_footer=True, show_edge=False, pad_edge=False, expand=True,
        header_style=f"bold {ACCENT}", footer_style="bold", border_style="dim",
    )
    table.add_column("Category", "Total", style="bold", no_wrap=True)
    table.add_column("Items", justify="right", no_wrap=True)
    table.add_column("Files", str(len(non_video)), justify="right", no_wrap=True)
    table.add_column("Size", format_size(total_size(non_video)), justify="right", no_wrap=True)
    # no_wrap keeps every page the same height, so the box doesn't jump when switching
    table.add_column("Notes", with_videos, style="dim", ratio=1, no_wrap=True, overflow="ellipsis")

    for key in crawls[0].results:
        table.add_row(*_row(key, [c.results[key] for c in crawls]))
    table.add_row(*_videos_row(videos))  # always present, also for fixed height

    if len(crawls) == 1:
        c = crawls[0].course
        heading = f"[bold]{escape(c.short_name)}[/] [dim]· {c.term_label}[/]"
    else:
        heading = f"[bold]All selected courses[/] [dim]· {len(crawls)} courses[/]"
    arrows = f"[{ACCENT}]◀[/]  " if pages > 1 else ""
    title = f"{arrows}{heading}  [dim]{page + 1}/{pages}[/]{f'  [{ACCENT}]▶[/]' if pages > 1 else ''}"

    hints = ["[bold]enter[/] continue", "[bold]esc[/] cancel"]
    if pages > 1:
        hints.insert(0, "[bold]←/→[/] switch course")
    return Panel(table, title=title, subtitle=" · ".join(hints), border_style=ACCENT, padding=(1, 2))


def _to_ansi(renderable, width: int) -> str:
    buf = io.StringIO()
    Console(file=buf, force_terminal=True, color_system="truecolor", width=width).print(renderable)
    return buf.getvalue().rstrip("\n")


def review(crawls: list[CourseCrawl], **app_kwargs) -> bool:
    """Show the crawl results. Returns True to continue to the download options, False to cancel.

    The first page combines all courses (only when there is more than one); each course follows.
    `app_kwargs` go to the prompt_toolkit Application (tests pass input/output here).
    """
    pages = [[c] for c in crawls]
    if len(crawls) > 1:
        pages.insert(0, crawls)
    width = min(shutil.get_terminal_size().columns, MAX_WIDTH)
    current = 0

    def render():
        return ANSI(_to_ansi(_panel(pages[current], current, len(pages)), width))

    kb = KeyBindings()

    @kb.add("left")
    @kb.add("h")
    def _prev(event):
        nonlocal current
        current = (current - 1) % len(pages)

    @kb.add("right")
    @kb.add("l")
    def _next(event):
        nonlocal current
        current = (current + 1) % len(pages)

    @kb.add("enter")
    def _proceed(event):
        event.app.exit(result=True)

    @kb.add("escape")
    @kb.add("q")
    @kb.add("c-c")
    def _cancel(event):
        event.app.exit(result=False)

    app = Application(
        layout=Layout(Window(FormattedTextControl(render), always_hide_cursor=True)),
        key_bindings=kb,
        full_screen=False,
        **app_kwargs,
    )
    return in_thread(app.run)
