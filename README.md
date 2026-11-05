# D2L Scraper

A command-line tool for archiving your own course data from a D2L Brightspace instance before you lose access to it, and for turning it into study material. You log in through a normal browser window, pick the courses and kinds of content you want, review exactly what will be downloaded, and the tool fetches it through D2L's read-only Valence API (plus the quiz review pages you can already see, which the API doesn't offer).

The result is a folder per course that works offline: every file in its original format, readable HTML pages for announcements, assignments, discussions, quiz attempts, grades, and the rest, spreadsheets and a calendar you can import, and the raw API data underneath it all. Optionally, each course also gets a study pack: a ready-to-upload set of sources for a [NotebookLM](https://notebooklm.google.com) notebook.

Works with any school's Brightspace: the first time you run it, you paste in a link from your school's Brightspace. It has been used in full at the University of Victoria; other schools run the same Brightspace API, but tell me if something behaves differently at yours.

## Install

You don't need Python or anything else first, and you don't need admin rights.

**Windows:** open PowerShell and paste:

```powershell
irm https://raw.githubusercontent.com/Dryd33n/d2l-scraper/master/install.ps1 | iex
```

**macOS / Linux:** open a terminal and paste:

```bash
curl -fsSL https://raw.githubusercontent.com/Dryd33n/d2l-scraper/master/install.sh | sh
```

It installs and starts straight away. After that, open a terminal and type `d2l-scraper`.

The script is short and you can read it first: [`install.ps1`](install.ps1), [`install.sh`](install.sh). It uses [uv](https://docs.astral.sh/uv/) to get a private copy of Python and the libraries, so nothing else on your computer changes.

## Features

- **Browser login**: sign in yourself in a real browser window (your installed Chrome or Edge), so SSO and MFA just work. The tool never sees your password.
- **Saved, encrypted session**: the login session is encrypted on disk with a key kept in your OS keychain (Windows Credential Manager, macOS Keychain, or on Linux a Secret Service provider such as GNOME Keyring; without one you log in each run), and reused until it expires. If it expires mid-download, the tool pauses, lets you log in again, and carries on.
- **Pick what you want**: every course you're enrolled in, grouped by term, and eight categories: content, classlist, grades, discussions, assignments, quizzes, announcements, calendar. Course info (overview, syllabus attachment, banner image) is always included.
- **Review before downloading**: every selected course is crawled first and summarised: items, files, and sizes per category, with videos counted separately. Nothing is downloaded until you confirm.
- **Your quiz attempts**: every attempt you submitted, with the questions, your answers, the right answers, and feedback, as far as each quiz lets students review them. The API doesn't allow this, so the tool reads the same review pages you see in Brightspace (never a page that starts a quiz).
- **Readable offline pages**: announcements, assignments (instructions, rubric, your submissions, feedback), discussion threads, quizzes, grades, and course info become clean HTML pages. Course content pages are saved self-contained, with images, styles, and scripts embedded, and links between Brightspace items point at the archived copies.
- **Optional Markdown**: any kind of generated page can also be saved as `.md`, with formulas as LaTeX.
- **Study packs for NotebookLM**: for the courses you pick, a folder of at most 45 sources to drop into a NotebookLM notebook: lecture files in their own format, the course overview, assignments, discussions, and every quiz question you've seen, once each, with its answer. See [Study packs](#study-packs).
- **Re-runnable**: files already in the archive are skipped, so an interrupted download resumes where it stopped.
- **Logged**: each run is recorded in a detailed log per course and a summary for the whole archive.

## Usage

```bash
d2l-scraper
```

1. **Your school.** The first time only, it asks for a link to your school's Brightspace. Copy one from your browser while you're on any Brightspace page and paste it in.
2. **Log in.** The first time you run it (or whenever your session has expired), a browser window opens on the Brightspace login page. Log in as usual; the window closes once you reach the Brightspace home page. This uses Chrome or Edge if you have one; otherwise a browser is downloaded once, for this window only.
3. **Pick a scraping profile**: how many requests run at once. **Polite** (3), **Fair** (6, the default), or **Aggressive** (12). Everything runs in parallel; the profile only sets how hard Brightspace gets hit.
4. **Pick courses.** **Space** toggles, **a** toggles all, **enter** confirms. Courses you no longer have access to are greyed out. Then pick which of them should get a study pack (none is fine); see [Study packs](#study-packs).
5. **Pick categories** the same way. All are checked by default.
6. **Review.** The tool crawls every selected course and shows a summary box. **←/→** switches between courses (with several courses, the first page totals all of them), **enter** continues, **esc** cancels.

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
   │  Quizzes                   1 quiz       1    48.1 KB   1 attempt · 0 questions…  │
   │  Announcements   22 announcements       2   405.7 KB                             │
   │  Calendar                6 events       0          –                             │
   │  Linked files            50 files      11    10.6 KB   11 HTML pages             │
   │  Videos                                39     1.0 GB   optional, asked next      │
   │  ──────────────────────────────────────────────────────────────────────────────  │
   │  Total                                103    33.4 MB   + 1.0 GB with videos      │
   └────────────────────────── enter continue · esc cancel ───────────────────────────┘
   ```

   "Linked files" are files that pages point to rather than list as topics: documents and videos linked from content pages, and the images, stylesheets, and scripts that get embedded into pages. The quizzes row counts your attempts and the questions they show; each attempt's review page is one file.

7. **Choose download options.** Whether to include videos (off by default; not asked if there are none), which kinds of generated page should also get a Markdown copy, and where to save the archive. The default is `D2L Archive` in your Documents folder.
8. **Download.** A progress bar shows bytes and time remaining. Then the study packs you picked are built from the archive, and a summary shows what was downloaded, skipped, and failed, each study pack's source count, and where the logs are. It offers to open the archive folder.

Run it again with the same selection to fill in anything missing: files already in the archive with the right size are skipped. Pages, JSON, exports, and study packs are rewritten every run.

### Other commands

| Command | What it does |
|---|---|
| `d2l-scraper update` | Install the latest version |
| `d2l-scraper logout` | Forget your saved login and its encryption key |
| `d2l-scraper school [link]` | Switch to a different school's Brightspace |
| `d2l-scraper studypack [archive folder]` | Build or rebuild study packs from an existing archive, without logging in |
| `d2l-scraper --help` | List all of these |

If something goes wrong, the error is explained on screen and the technical details go to `error.log` in the program's data folder (on Windows, `%LOCALAPPDATA%\d2l-scraper`). Running it again is always safe.

To uninstall: `d2l-scraper logout`, then `uv tool uninstall d2l-scraper`.

## What gets archived

```
D2L Archive/
  download log.txt                  summary of every run: a row per course, totals, all failures
  Study Packs/<course>/             study packs, when picked (see below)
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
      Quiz 1/
        attempts.html               every attempt: score, questions, your answers, right answers, feedback
        _originals/attempt 1.html   each attempt's review page as Brightspace served it
    classlist/                      classlist.csv  classlist.json
    calendar/                       calendar.ics  calendar.json
    _course-files/
      _originals/                   content pages exactly as downloaded
      _assets/                      images, stylesheets, scripts, and fonts embedded into pages
      Lab1_Videos/…                 files linked from pages, in their Brightspace folders
```

## Study packs

A study pack is a folder in `D2L Archive/Study Packs/<course>/` made for a NotebookLM notebook, whose free plan takes 50 sources. Create a notebook and upload every file in the folder except `manifest.md`; NotebookLM then answers questions, quizzes you, and makes study guides from your own course material.

Pick courses for a pack right after the course picker, or rebuild packs from an existing archive at any time with `d2l-scraper studypack` (no login needed).

```
Study Packs/Fall 2026 CSC 320 A01 A02 X/
  01 Course overview.md       course info, content outline, announcements
  02 Practice questions.md    every quiz question from your attempts, once each, with the right answer and feedback
  03 Assignments.md           instructions, rubrics, feedback
  04 Discussions.md
  05 Lectures (pages).md      a module's HTML pages and code files as text
  06 02-FA.pdf                lecture files as they are, in the instructor's order
  manifest.md                 what's in each source, web links to add by hand, what was left out and why
```

- It's built from what's on disk, so earlier runs count too, and it's rebuilt from scratch each time. A folder in `Study Packs/` that isn't a pack (no `manifest.md`) is never replaced.
- Practice questions come from your saved quiz attempts: each question appears once even if several attempts showed it, with its choices, the correct answer worked out from Brightspace's marks, and any feedback. Your own selections aren't included. When a quiz doesn't reveal the answer, the pack says "not shown". Archives downloaded before quiz attempts were saved need a run with Quizzes ticked first.
- PDFs, PowerPoint, Word, and images stay as they are. Videos, zip files, your own submissions, the classlist, grades, and calendar are left out.
- To stay at 45 sources it merges PDFs (and images) module by module, biggest module first, only as far as needed; then whole top-level modules; then turns slides and Word documents into text. Anything that still doesn't fit is listed in the manifest. Courses with hundreds of MB of PDFs can take a few minutes.
- The same file in two places is included once.

## How it works

- **Authentication**: [Playwright](https://playwright.dev/python/) opens a visible browser for you to log in, preferring installed Chrome or Edge and downloading Chromium only if neither is there. The resulting cookies are saved with `storage_state`, encrypted with [Fernet](https://cryptography.io/en/latest/fernet/), and written to `state.enc` in the program's data folder. The key is generated on first run and stored in the OS keychain, so the file is useless if copied to another machine. Before each run the tool checks the session with `/d2l/api/lp/{version}/users/whoami`.
- **API access**: API versions are discovered at startup from `/d2l/api/versions/`. All requests go through [httpx](https://www.python-httpx.org/) with the login cookies, in parallel: courses, categories, and the items inside them are crawled at the same time, and files download at the same time, never more requests in flight than the profile allows. Everything is retried up to 3 times on network errors, 429, and 5xx. An expired session answers with the same 403 as hidden content, so on a 403 the tool checks `whoami` to tell the two apart before asking you to log in again.
- **Crawl**: for each course and category the tool walks the relevant endpoints (content table of contents, dropbox folders and your submissions, forum topics and posts, news, grades, quizzes, calendar). HTML content pages are fetched during the crawl, and every page and piece of rich text is scanned for the Brightspace files it references; each one's size is checked with a `HEAD` request. The crawl keeps every file's download URL and the raw JSON, so the download step doesn't crawl again.
- **Download**: files are streamed to a `.part` file and renamed when complete; if the session expires, files still waiting are held until you've logged in again. Names are made safe for Windows, macOS, and Linux, duplicates get ` (2)`, and paths are kept under Windows' 260-character limit where possible. The same crawl always produces the same paths, which is how a re-run recognises what it already has.
- **Quiz attempts**: the API refuses students their quiz questions and attempts, so for each quiz the crawl reads the submissions list and each attempt's review page, the same pages you open in Brightspace, with the same login. Only those two kinds of page are ever requested, never one that starts a quiz, so an attempt can't be started or used up. The page is parsed with BeautifulSoup: questions, your selections, the correct-answer marks, feedback, and images. How much shows depends on the quiz (every question, only wrong answers, or just the score), and the archived page says which.
- **Pages**: generated after the files, so links know what's on disk. Embedded files are read from `_course-files/_assets/` and inlined as `data:` URIs, `<style>`, and `<script>`. Brightspace quickLinks are resolved offline by matching their `rcode` to the `ActivityId` of the crawled assignments, quizzes, discussion topics, and content topics. Markdown copies use [markdownify](https://pypi.org/project/markdownify/); MathML formulas become `$LaTeX$` from the equation editor's source.
- **Study packs**: built offline from the archive folder. Pages become Markdown, quiz attempts become an answer key, and files are copied. To stay under the source limit, PDFs and images are merged module by module with [pypdf](https://pypi.org/project/pypdf/) and [Pillow](https://pypi.org/project/pillow/), largest module first and only as far as needed, then slide decks and Word documents are turned into text one at a time, read straight from their XML. Duplicates are found by content hash.

## Project layout

```
cli.py            The d2l-scraper command: subcommands and plain-language errors
main.py           The main run: login → select → crawl → review → options → download → study packs
config.py         Data locations and which school's Brightspace to use
auth.py           Browser login, encrypted session, API session (retries, file fetch, re-login)
courses.py        Fetch and group course enrollments
crawl.py          Crawl of each course/category: counts, files, sizes, raw JSON, linked files
review.py         Review screen: counts and sizes per course, ←/→ to switch
prompts.py        Interactive prompts: courses, study packs, categories, download options, output folder
download.py       Output paths, raw JSON, file downloads with skip-if-present and re-login, page writing
exports.py        grades.csv, classlist.csv, calendar.ics
pages.py          Generated HTML pages, content outline, links page, shortcuts
embed.py          Finding and rewriting references in Brightspace HTML (embedding, local links)
quiz_attempts.py  Reading quiz attempt review pages: questions, answers, right answers, feedback, answer keys
markdown_copy.py  Markdown copies of generated pages (formulas as LaTeX)
runlog.py         Per-course and archive-wide download logs
studypack.py      Study packs for NotebookLM, built from the archive on disk (also runs on its own)
ui.py             Shared terminal styling and helpers
tests/            Test scripts (fixtures in tests/fixtures/ are git-ignored)
install.ps1, install.sh   The one-line installers
d2l-scraper-requirements.md   Design notes, content inventory, and decisions
```

## Developing

```bash
git clone https://github.com/Dryd33n/d2l-scraper.git
cd d2l-scraper
python -m venv .venv
.venv/Scripts/activate      # macOS / Linux: source .venv/bin/activate
pip install -e .
python cli.py
```

Tests are plain scripts: `python tests/test_setup.py` prints a PASS or FAIL line per check. `tests/test_auth.py` needs a real login.

## Disclaimer

This is a personal project for archiving your own course materials. It is not affiliated with or endorsed by D2L or any school. Use it only on courses you are enrolled in, keep request rates reasonable, and follow your institution's acceptable-use policy.
