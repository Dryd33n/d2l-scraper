# D2L Scraper

A command-line tool for archiving your own course data from a D2L Brightspace instance before you lose access to it. You log in through a normal browser window, pick the courses and kinds of content you want, review exactly what will be downloaded, and the tool fetches it through D2L's read-only Valence API.

The result is a folder per course that works offline: every file in its original format, readable HTML pages for announcements, assignments, discussions, grades, and the rest, spreadsheets and a calendar you can import, and the raw API data underneath it all.

Currently targets the University of Victoria's Brightspace (`bright.uvic.ca`).

## Features

- **Browser login**: sign in yourself in a real browser window, so SSO and MFA just work. The tool never sees your password.
- **Saved, encrypted session**: the login session is encrypted on disk with a key kept in your OS keychain, and reused until it expires. If it expires mid-download, the tool pauses, lets you log in again, and carries on.
- **Pick what you want**: every course you're enrolled in, grouped by term, and eight categories: content, classlist, grades, discussions, assignments, quizzes, announcements, calendar. Course info (overview, syllabus attachment, banner image) is always included.
- **Review before downloading**: every selected course is crawled first and summarised: items, files, and sizes per category, with videos counted separately. Nothing is downloaded until you confirm.
- **Readable offline pages**: announcements, assignments (instructions, rubric, your submissions, feedback), discussion threads, quizzes, grades, and course info become clean HTML pages. Course content pages are saved self-contained, with images, styles, and scripts embedded, and links between Brightspace items point at the archived copies.
- **Optional Markdown**: any kind of generated page can also be saved as `.md`.
- **Re-runnable**: files already in the archive are skipped, so an interrupted download resumes where it stopped.
- **Logged**: each run is recorded in a detailed log per course and a summary for the whole archive.

## Requirements

- Python 3.10 or newer
- A working OS keychain, used through [`keyring`](https://pypi.org/project/keyring/): Windows Credential Manager and macOS Keychain work out of the box. On Linux you need a Secret Service provider such as GNOME Keyring or KWallet.

## Setup

```bash
git clone https://github.com/Dryd33n/d2l-scraper.git
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
2. **Pick courses.** **Space** toggles, **a** toggles all, **enter** confirms. Courses you no longer have access to are greyed out.
3. **Pick categories** the same way. All are checked by default.
4. **Review.** The tool crawls every selected course and shows a summary box. **←/→** switches between courses (with several courses, the first page totals all of them), **enter** continues, **esc** cancels.

   ```
   ┌───────────────────── CSC 230 A01 - A04 X · Spring 2025  1/1 ─────────────────────┐
   │  Category                   Items   Files       Size   Notes                     │
   │  ──────────────────────────────────────────────────────────────────────────────  │
   │  Course info               1 page       1    21.5 KB   banner image              │
   │  Content               102 topics      64    31.7 MB   22 modules · 27 links     │
   │  Classlist              88 people       0          –   1 group category          │
   │  Grades            15 grade items       0          –   final grade released      │
   │  Discussions              0 posts       0          –                             │
   │  Assignments        6 assignments      24     1.2 MB   6 submissions             │
   │  Quizzes                   1 quiz       0          –                             │
   │  Announcements   22 announcements       2   405.7 KB                             │
   │  Calendar                6 events       0          –                             │
   │  Linked files            50 files      11    10.6 KB   11 HTML pages             │
   │  Videos                                39     1.0 GB   optional, asked next      │
   │  ──────────────────────────────────────────────────────────────────────────────  │
   │  Total                                102    33.3 MB   + 1.0 GB with videos      │
   └────────────────────────── enter continue · esc cancel ───────────────────────────┘
   ```

   "Linked files" are files that pages point to rather than list as topics: documents and videos linked from content pages, and the images, stylesheets, and scripts that get embedded into pages.

5. **Choose download options.** Whether to include videos (off by default; not asked if there are none), which kinds of generated page should also get a Markdown copy, and where to save the archive. The default is the git-ignored `D2L Archive/` folder in this repository. Other folders inside the repository are refused, since they could get committed.
6. **Download.** A progress bar shows bytes and time remaining, then a summary of what was downloaded, skipped, and failed, and where the log is.

Run it again with the same selection to fill in anything missing: files already in the archive with the right size are skipped. Pages, JSON, and exports are rewritten every run.

Other entry points, useful while developing:

| Command | What it does |
|---|---|
| `python auth.py` | Log in if needed and print who you are authenticated as |
| `python courses.py` | Print all enrolled courses grouped by term |

### Logging out

Delete `.auth/state.enc`. To also remove the encryption key, delete the `d2l-scraper` entry from your OS keychain (on Windows: Credential Manager → Windows Credentials).

## What gets archived

```
D2L Archive/
  download log.txt                  summary of every run: a row per course, totals, all failures
  Spring 2025 CSC 230 A01 - A04 X/  one folder per course, named as in Brightspace (includes the term)
    download log.txt                every run in detail: crawl counts, each file downloaded, failures
    course info/                    course.html  course.json  course-image.jpg  (+ syllabus attachment)
    content/
      01 Course Outline/            modules in the instructor's order
        Welcome Letter.pdf          files in their original format
        Office Hours.html           content page, self-contained
        Course Notes.url            shortcut to a web link or external tool
        Lab 2.html                  shortcut to the archived copy of a Brightspace item
      content.html                  outline: every module and topic, with descriptions
      links.html                    every link, grouped by module
      content.json
    announcements/                  announcements.html  attachments/  announcements.json
    assignments/
      Lab 2/                        assignment.html  attachments/  submissions/2025-01-24/  feedback/
      assignments.json
    discussions/
      <Forum>/<Topic>.html          threads with replies nested
      <Forum>/<Topic>/attachments/
      discussions.json
    grades/                         grades.html  grades.csv  grades.json
    quizzes/                        quizzes.html  quizzes.json
    classlist/                      classlist.csv  classlist.json
    calendar/                       calendar.ics  calendar.json
    _course-files/
      _originals/                   content pages exactly as downloaded
      _assets/                      images, stylesheets, scripts, and fonts embedded into pages
      Lab1_Videos/…                 files linked from pages, in their Brightspace folders
```

## How it works

- **Authentication**: [Playwright](https://playwright.dev/python/) opens a visible browser for you to log in. The resulting cookies are saved with `storage_state`, encrypted with [Fernet](https://cryptography.io/en/latest/fernet/), and written to `.auth/state.enc`. The key is generated on first run and stored in the OS keychain, so the file is useless if copied to another machine. Before each run the tool checks the session with `/d2l/api/lp/{version}/users/whoami`.
- **API access**: API versions are discovered at startup from `/d2l/api/versions/`. Requests run one at a time and are retried up to 3 times on network errors, 429, and 5xx. An expired session answers with the same 403 as hidden content, so on a 403 the tool checks `whoami` to tell the two apart before asking you to log in again.
- **Crawl**: for each course and category the tool walks the relevant endpoints (content table of contents, dropbox folders and your submissions, forum topics and posts, news, grades, quizzes, calendar). HTML content pages are fetched during the crawl, and every page and piece of rich text is scanned for the Brightspace files it references; each one's size is checked with a `HEAD` request. The crawl keeps every file's download URL and the raw JSON, so the download step doesn't crawl again.
- **Download**: each file is written to a `.part` file first and renamed when complete. Names are made safe for Windows, macOS, and Linux, duplicates get ` (2)`, and paths are kept under Windows' 260-character limit where possible. The same crawl always produces the same paths, which is how a re-run recognises what it already has.
- **Pages**: generated after the files, so links know what's on disk. Embedded files are read from `_course-files/_assets/` and inlined as `data:` URIs, `<style>`, and `<script>`. Brightspace quickLinks are resolved offline by matching their `rcode` to the `ActivityId` of the crawled assignments, quizzes, discussion topics, and content topics.

## Project layout

```
main.py           Entry point: login → select → crawl → review → options → download
auth.py           Browser login, encrypted session, API session (retries, file fetch, re-login)
courses.py        Fetch and group course enrollments
crawl.py          Crawl of each course/category: counts, files, sizes, raw JSON, linked files
review.py         Review screen: counts and sizes per course, ←/→ to switch
prompts.py        Interactive prompts: courses, categories, download options, output folder
download.py       Output paths, raw JSON, file downloads with skip-if-present and re-login, page writing
exports.py        grades.csv, classlist.csv, calendar.ics
pages.py          Generated HTML pages, content outline, links page, shortcuts
embed.py          Finding and rewriting references in Brightspace HTML (embedding, local links)
markdown_copy.py  Markdown copies of generated pages
runlog.py         Per-course and archive-wide download logs
ui.py             Shared terminal styling and helpers
tests/            Test scripts (fixtures in tests/fixtures/ are git-ignored)
d2l-scraper-requirements.md   Design notes, content inventory, and decisions
```

## Disclaimer

This is a personal project for archiving your own course materials. It is not affiliated with or endorsed by D2L or the University of Victoria. Use it only on courses you are enrolled in, keep request rates reasonable, and follow your institution's acceptable-use policy.
