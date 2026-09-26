# D2L Scraper

A command-line tool for archiving your own course data from a D2L Brightspace instance. You log in through a normal browser window, pick the courses and kinds of content you want, review exactly what will be downloaded, and the tool fetches it through D2L's read-only Valence API.

> **Status: work in progress.** The full flow works end to end: every file is downloaded, raw JSON is saved, grades, classlist, and calendar are exported to CSV and `.ics`, and readable HTML pages are generated for course info, announcements, assignments, discussions, quizzes, and grades. Still to come: self-contained content pages (with images embedded), and Markdown copies.

Currently targets the University of Victoria's Brightspace (`bright.uvic.ca`). Support for other D2L instances is planned.

## Features

- **Browser login**: sign in yourself in a real browser window, so SSO and MFA just work. The tool never sees your password.
- **Saved, encrypted session**: the login session is encrypted on disk with a key kept in your OS keychain, and reused until it expires.
- **Course picker**: lists every course you are enrolled in, grouped by term. Courses you no longer have access to are greyed out.
- **Category picker**: content, classlist, grades, discussions, assignments, quizzes, announcements, calendar. Course info (overview, syllabus attachment, banner image) is always included.
- **Deep crawl and review**: before anything is downloaded, every selected course is crawled and summarised: items, files, and sizes per category, with videos counted separately. Page through courses with the arrow keys.
- **Download options**: videos are opt-in (they can easily triple the download size), and generated pages can optionally get Markdown copies.
- **Fault tolerant**: a category the server refuses (hidden classlist, disabled tool, server error) is marked in the review instead of stopping the crawl.
- **Read-only**: only ever makes `GET` and `HEAD` requests; nothing in your courses is changed.

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

1. **Log in.** The first time you run it (or whenever your session has expired), a Chromium window opens on the Brightspace login page. Log in as usual; the window closes once you reach the Brightspace home page.
2. **Pick courses.** **Space** toggles, **a** toggles all, **enter** confirms.
3. **Pick categories** the same way. All are checked by default.
4. **Review.** The tool crawls every selected course and shows a summary box. **←/→** switches between courses (the first page totals all of them), **enter** continues, **esc** cancels.

   ```
   ┌──────────────── ◀  All selected courses · 2 courses  1/3  ▶ ────────────────┐
   │  Category                   Items   Files       Size   Notes                │
   │  ─────────────────────────────────────────────────────────────────────────  │
   │  Course info              2 pages       2    41.8 KB                        │
   │  Content               107 topics      84   331.1 MB   11 links             │
   │  Classlist             173 people       0          –                        │
   │  Grades            11 grade items       0          –                        │
   │  Discussions            479 posts      88    20.9 MB                        │
   │  Assignments       15 assignments       7     1.3 MB                        │
   │  Quizzes                   1 quiz       0          –                        │
   │  Announcements   40 announcements       0          –                        │
   │  Calendar               23 events       0          –                        │
   │  Videos                                12   916.2 MB   optional, asked next │
   │  ─────────────────────────────────────────────────────────────────────────  │
   │  Total                                181   353.3 MB   + 916.2 MB with videos│
   └────────────── ←/→ switch course · enter continue · esc cancel ──────────────┘
   ```

5. **Choose download options.** Whether to include videos (off by default; skipped if there are none), which generated pages should also get a Markdown copy, and where to save the archive (default: the git-ignored `D2L Archive/` folder in this repository; other folders inside the repository are refused, since they could get committed).
6. **Download.** A progress bar shows bytes and time remaining, then a summary of what was downloaded, skipped, and failed.

Running it again with the same selection only fetches what's missing: files already in the archive with the right size are skipped, so an interrupted download resumes where it stopped. If your Brightspace session expires mid-download, the tool pauses, opens the browser for you to log in again, and carries on.

Other entry points, useful while developing:

| Command | What it does |
|---|---|
| `python auth.py` | Log in if needed and print who you are authenticated as |
| `python courses.py` | Print all enrolled courses grouped by term |

### Logging out

Delete `.auth/state.enc`. To also remove the encryption key, delete the `d2l-scraper` entry from your OS keychain (on Windows: Credential Manager → Windows Credentials).

## What gets archived

Details in [`d2l-scraper-requirements.md`](d2l-scraper-requirements.md), section 5.

Working now:

- **Files stay in their original format.** PDFs, slides, documents, code, images, and (if opted in) videos are saved byte-for-byte under their original names: content files in numbered module folders, assignment attachments, your submissions (by date), feedback files, announcement and discussion attachments, the syllabus attachment, and the course banner.
- **Raw API JSON is always kept**, one file per category, so pages can be regenerated and future runs can sync.
- **Grades and classlist become CSV** (opens in Excel), grades joined to their categories with instructor comments.
- **Calendar becomes `.ics`**, importable into any calendar app.

Coming next:

- **Text becomes self-contained HTML.** Announcements, assignment instructions and feedback, discussion threads, content pages, quizzes, grades, and course info as HTML pages with their images and styles embedded, so each page works offline as a single file. Optional Markdown copies next to them.
- **Links are recorded, not followed.** External links, embedded video players (YuJa/Kaltura), and other tools go into a `links.html` per course, plus `.url` shortcuts.

```
<output root>/
  Spring 2025 CSC 230 A01 - A04 X/
    course info/     course.html  course.json  course-image.jpg
    content/         01 Course Outline/…  links.html  content.json
    announcements/   announcements.html  attachments/  announcements.json
    assignments/     <Assignment>/assignment.html  attachments/  submissions/  feedback/
    discussions/     <Forum>/<Topic>.html
    grades/          grades.html  grades.csv  grades.json
    quizzes/         quizzes.html  quizzes.json
    classlist/       classlist.csv  classlist.json
    calendar/        calendar.ics  calendar.json
```

Quiz questions and attempts can't be archived: the API refuses them to students, so only quiz details are saved. Content topics whose file is missing on Brightspace itself ("broken" topics) are listed in the review and skipped.

## How it works

- **Authentication**: [Playwright](https://playwright.dev/python/) opens a visible browser for you to log in. The resulting cookies are saved with `storage_state`, encrypted with [Fernet](https://cryptography.io/en/latest/fernet/), and written to `.auth/state.enc`. The key is generated on first run and stored in the OS keychain, so the file is useless if copied to another machine.
- **Session check**: before each run the tool calls `/d2l/api/lp/{version}/users/whoami`. If the session is missing, unreadable, or rejected, it opens the browser to log in again.
- **API access**: API versions are discovered at startup from `/d2l/api/versions/`. Courses come from `/d2l/api/lp/{version}/enrollments/myenrollments/`.
- **Deep crawl**: for each course and category the tool walks the relevant endpoints (content table of contents, dropbox folders and your submissions, forum topics and posts, news, grades, quizzes, calendar). File sizes come from the API where it reports them, and from a `HEAD` request for content files. The crawl keeps every file's download URL and the raw JSON, so the download step doesn't crawl again.
- **Download**: requests run one at a time and are retried up to 3 times on network errors, 429, and 5xx. Each file is written to a `.part` file first and renamed when complete. Names are made safe for Windows, macOS, and Linux, duplicates get ` (2)`, and paths are kept under Windows' 260-character limit where possible. An expired session answers with the same 403 as hidden content, so on a 403 the tool checks `whoami` to tell the two apart before asking you to log in again.

## Project layout

```
main.py        Entry point: login → select → crawl → review → options → download
auth.py        Browser login, encrypted session, API session (retries, file fetch, re-login)
courses.py     Fetch and group course enrollments
crawl.py       Deep crawl of each course/category: counts, files, sizes, raw JSON
review.py      Review screen: counts and sizes per course, ←/→ to switch
prompts.py     Interactive prompts: courses, categories, download options, output folder
download.py    Output paths, raw JSON, file downloads with skip-if-present and re-login
exports.py     grades.csv, classlist.csv, calendar.ics
tests/         Test scripts (fixtures in tests/fixtures/ are git-ignored)
ui.py          Shared terminal styling and helpers
d2l-scraper-requirements.md   Design notes, content inventory, and decisions
```

## Tests

Plain scripts that print `PASS`/`FAIL` per check:

```bash
python tests/test_download_units.py   # filenames, path limits, CSV and .ics output
python tests/test_expiry.py           # re-login when the session expires mid-download
python tests/test_review.py           # review screen keys and layout
python tests/test_prompts.py          # course/category/options prompts via simulated keypresses
python tests/test_auth.py             # session encryption and validation (needs a logged-in session)
```

`test_review.py` and `test_prompts.py` use crawl fixtures in `tests/fixtures/`. They contain real course data, so they're git-ignored; generate them with `tests/run_crawl.py` (see section 0 of the requirements doc).

## Roadmap

- [x] Browser login with saved, encrypted session
- [x] Course and category selection
- [x] Deep crawl with per-course counts and sizes, reviewed before downloading
- [x] Download options: videos opt-in, Markdown copies
- [x] Download every file, raw JSON, grades/classlist CSV, calendar `.ics`
- [x] Pause and re-login if the session expires mid-download
- [x] Re-runs skip files already downloaded
- [x] Generated HTML pages: announcements, assignments, discussions, quizzes, grades, course info
- [ ] Embed images in generated pages (they link to Brightspace for now)
- [ ] Self-contained content HTML pages; record link-only items (`links.html`, `.url`)
- [ ] Count videos linked from inside HTML pages
- [ ] Markdown conversion of generated pages
- [ ] End-of-run log file
- [ ] Full sync (detect changed and removed items)
- [ ] Support for other D2L instances

## Security and privacy

- `.auth/` is git-ignored. Never commit it or share it: while the session is valid, the saved state grants access to your Brightspace account.
- Encryption protects the session file if it is copied off your machine (backups, cloud sync, accidental sharing). It does not protect against software running as your own user account.
- Archives can contain other people's personal data (the classlist includes names and emails). The default `D2L Archive/` folder is git-ignored, so it isn't committed, but it is included if you zip, copy, or cloud-sync the project folder. Don't share archives publicly.

## Disclaimer

This is a personal project for archiving your own course materials. It is not affiliated with or endorsed by D2L or the University of Victoria. Use it only on courses you are enrolled in, keep request rates reasonable, and follow your institution's acceptable-use policy.
