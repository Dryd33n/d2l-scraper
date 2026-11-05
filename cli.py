"""The d2l-scraper command: run the archiver, plus logout, school, studypack, and update."""

import argparse
import os
import subprocess
import sys
import traceback
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version

import httpx
from rich.markup import escape

import config
from ui import console, ok, warn

INSTALL_BASE = "https://raw.githubusercontent.com/Dryd33n/d2l-scraper/master"


def _version() -> str:
    try:
        return version("d2l-scraper")
    except PackageNotFoundError:
        return "development"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="d2l-scraper", description="Archive your own D2L Brightspace courses.")
    parser.add_argument("--version", action="version", version=f"d2l-scraper {_version()}")
    commands = parser.add_subparsers(dest="command", metavar="[command]")
    commands.add_parser("logout", help="forget your saved login")
    school = commands.add_parser("school", help="change which school's Brightspace to use")
    school.add_argument("address", nargs="?", help="a link to your school's Brightspace")
    pack = commands.add_parser("studypack", help="build NotebookLM study packs from an existing archive, no login needed")
    pack.add_argument("folder", nargs="?", help="the archive folder (default: the usual one)")
    commands.add_parser("update", help="install the latest version")
    return parser


def _update() -> None:
    """Re-run the install script. On Windows a running program can't be replaced, so it runs in its own
    window once this one has exited."""
    env = {**os.environ, "D2L_SCRAPER_NO_START": "1"}
    if sys.platform == "win32":
        command = (f"Start-Sleep 2; irm {INSTALL_BASE}/install.ps1 | iex; "
                   "Read-Host 'Press Enter to close this window'")
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                         env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)
        ok("Updating in a new window.")
    else:
        sys.exit(subprocess.call(["sh", "-c", f"curl -fsSL {INSTALL_BASE}/install.sh | sh"], env=env))


def _dispatch(args: argparse.Namespace) -> None:
    # imported here so --version and --help don't load the browser driver
    if args.command == "logout":
        import auth
        auth.logout()
        ok("Logged out.")
    elif args.command == "school":
        config.choose_school(args.address)
    elif args.command == "studypack":
        import studypack
        studypack.main(args.folder)
    elif args.command == "update":
        _update()
    else:
        import main as app
        app.main()


def _report_crash(error: Exception) -> None:
    """Explain what went wrong in plain words; the traceback goes to a log file for anyone debugging."""
    config.APP_DIR.mkdir(parents=True, exist_ok=True)
    with config.ERROR_LOG.open("a", encoding="utf-8") as log:
        log.write(f"--- {datetime.now().isoformat(timespec='seconds')} d2l-scraper {_version()}\n")
        log.write("".join(traceback.format_exception(error)) + "\n")
    console.print(f"[red]✗[/] Something went wrong: {escape(str(error))}")
    console.print(f"[dim]Details are in {escape(str(config.ERROR_LOG))}. Running it again is safe: "
                  "files already downloaded are skipped.[/]")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")  # a pipe or old console must not crash on ✓
    args = _parser().parse_args(argv)
    try:
        _dispatch(args)
    except KeyboardInterrupt:
        warn("Cancelled. Running it again picks up where this left off.")
        return 130
    except httpx.TransportError:
        console.print("[red]✗[/] Couldn't reach Brightspace. Check your internet connection and run it again: "
                      "files already downloaded are skipped.")
        return 1
    except Exception as e:
        _report_crash(e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
