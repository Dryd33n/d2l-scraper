# D2L Scraper

A command-line tool for archiving your own course data from a D2L Brightspace instance. You log in through a normal browser window, pick the courses and kinds of content you want, and the tool downloads them through D2L's read-only Valence API.

> **Status: early work in progress.** Login, course listing, and course/category selection work. Downloading content is not implemented yet.

Currently targets the University of Victoria's Brightspace (`bright.uvic.ca`). Support for other D2L instances is planned.

## Features

- **Browser login**: sign in yourself in a real browser window, so SSO and MFA just work. The tool never sees your password.
- **Saved, encrypted session**: the login session is encrypted on disk with a key kept in your OS keychain, and reused until it expires.
- **Course picker**: lists every course you are enrolled in, grouped by term, and lets you check the ones to archive. Courses you no longer have access to are greyed out.
- **Category picker**: choose which kinds of data to fetch: content, classlist, grades, discussions, assignments, quizzes, announcements.
- **Read-only**: only ever makes `GET` requests; nothing in your courses is changed.

## Requirements

- Python 3.10 or newer
- A working OS keychain, used through [`keyring`](https://pypi.org/project/keyring/): Windows Credential Manager and macOS Keychain work out of the box. On Linux you need a Secret Service provider such as GNOME Keyring or KWallet.

## Setup

```bash
git clone https://github.com/<your-username>/d2l-scraper.git
cd d2l-scraper

python -m venv .venv
# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python -m playwright install chromium
```

## Usage

```bash
python main.py
```

1. The first time you run it (or whenever your session has expired), a Chromium window opens on the Brightspace login page. Log in as usual. The window closes once you reach the Brightspace home page.
2. Pick courses: **space** toggles, **a** toggles all, **enter** confirms.
3. Pick categories the same way (all are checked by default).
4. The tool prints a summary of what you selected.

Other entry points, useful while developing:

| Command | What it does |
|---|---|
| `python auth.py` | Log in if needed and print who you are authenticated as |
| `python courses.py` | Print all enrolled courses grouped by term |

### Logging out

Delete `.auth/state.enc`. To also remove the encryption key, delete the `d2l-scraper` entry from your OS keychain (on Windows: Credential Manager → Windows Credentials).

## How it works

- **Authentication**: [Playwright](https://playwright.dev/python/) opens a visible browser for you to log in. The resulting cookies are saved with `storage_state`, encrypted with [Fernet](https://cryptography.io/en/latest/fernet/), and written to `.auth/state.enc`. The key is generated on first run and stored in the OS keychain, so the file is useless if copied to another machine.
- **Session check**: before each run the tool calls `/d2l/api/lp/{version}/users/whoami`. If the session is missing, unreadable, or rejected, it opens the browser to log in again.
- **API access**: API versions are discovered at startup from `/d2l/api/versions/`. Courses come from `/d2l/api/lp/{version}/enrollments/myenrollments/`, following the API's bookmark paging.

## Project layout

```
main.py        Entry point: login, course selection, category selection
auth.py        Browser login, encrypted session storage, API session wrapper
courses.py     Fetch and group course enrollments
prompts.py     Interactive checkbox prompts (questionary)
ui.py          Shared terminal styling (rich console, prompt colours)
d2l-scraper-requirements.md   Design notes and open decisions
```

## Roadmap

- [x] Browser login with saved, encrypted session
- [x] List enrolled courses
- [x] Course and category selection
- [ ] Per-category item counts shown before selection
- [ ] Download content files, announcements, grades, assignments, discussions
- [ ] Metadata JSON alongside downloads
- [ ] Record links for embedded video and external tools
- [ ] Re-runnable sync (skip already-downloaded files)
- [ ] Support for other D2L instances

See [`d2l-scraper-requirements.md`](d2l-scraper-requirements.md) for the full plan.

## Security notes

- `.auth/` is git-ignored. Never commit it or share it: while the session is valid, the saved state grants access to your Brightspace account.
- Encryption protects the session file if it is copied off your machine (backups, cloud sync, accidental sharing). It does not protect against software running as your own user account.

## Disclaimer

This is a personal project for archiving your own course materials. It is not affiliated with or endorsed by D2L or the University of Victoria. Use it only on courses you are enrolled in, keep request rates reasonable, and follow your institution's acceptable-use policy.
