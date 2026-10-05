# D2L Scraper — Requirements

> Status: In progress (phase 1 download built: files, raw JSON, CSV, ICS; generated HTML pages next)
> Last updated: 2026-10-05

---

## 0. Where we left off (2026-09-26)

**Done:** login + encrypted session, course/category pickers, deep crawl, review screen, download options (videos, Markdown, output folder), phase 1 download (all files, raw JSON, `grades.csv`, `classlist.csv`, `calendar.ics`, skip-if-present, retries, re-login mid-download), phase 2 generated HTML pages (`pages.py`), phase 3 self-contained content pages and linked files (`embed.py`), phase 4 Markdown copies (`markdown_copy.py`), phase 5 end-of-run logs (`runlog.py`, section 7); see 4.6. Tested on real courses; 183 tests in `tests/`.

**Phase 3 approach:** the crawl fetches each HTML content page (small) and lists what it references; every downloadable reference (images, `/shared/…` template CSS/JS, linked documents, linked videos) becomes an ordinary crawled file. So the review shows real sizes and linked-video counts, re-runs skip what's on disk, and nothing is fetched twice. The download then writes each HTML page self-contained, embedding its images/CSS/JS from those downloaded copies, and rewrites Brightspace links to the local copies (phase 2 pages, content files).

**Phase 3 decisions** (2026-09-26):
1. **Original HTML is kept** untouched in `_course-files/_originals/`, next to the self-contained page in the module folder.
2. **Embedded assets stay on disk** in `_course-files/_assets/` so re-runs don't fetch them again; they're still inlined into every page.
3. **`_course-files/` is per course** (`<course>/_course-files/`), shared by content, announcements, assignments, and discussions.
4. **The crawl fetches HTML pages** and checks the size of each linked file; a slower crawl is fine.

**Phase 6 (2026-10-05): quiz attempts** are archived from the review pages students see (see 4.6 and 5.2).

**Next:** the study pack for NotebookLM (section 11), which uses the quiz attempts. Other open items: sync of changed/removed items (section 6), a browsable `index.html` (section 6), any-D2L-instance support (section 1).

**Testing notes:** `tests/fixtures/*.pkl` are crawl results pickled from real courses (git-ignored, personal data). Regenerate with `python tests/run_crawl.py tests/fixtures/with_videos.pkl 382134,504907` and `… without_videos.pkl 397411,376123,507204,293541`. The pickles predate the current grades/course-info JSON shape, so `test_pages.py` uses hand-built records; regenerate them before relying on them for new tests. Prompt tests drive questionary with `create_pipe_input`; tests run inside `sync_playwright()` because prompts must work while Playwright owns the main thread's event loop.

---

## 1. Overview

**Purpose:** Archive course data from a D2L Brightspace instance for personal use, letting the user pick which courses and which kinds of content to download.

**Target instance(s):**
- [x] UVic only (`https://bright.uvic.ca`)
- [ ] Any D2L instance (configurable base URL)

UVic only for now, we will attempt to implement any D2L instance later

**Out of scope:**
- User-level (not per-course) tools: Locker, ePortfolio, awards/badges, profile, D2L email

---

## 2. Authentication — DECIDED

**Approach:** Playwright browser login with saved session state.

- [x] Open a headed browser; the user logs in manually (SSO + MFA handled by the user)
- [x] Save the session with `storage_state` to a local file
- [x] Before each run, check the session with `/d2l/api/lp/{ver}/users/whoami`
- [x] If the session is invalid or expired, prompt for a fresh login
- [x] Detect expiry during downloads (login redirect, or 403 + failed `whoami`), pause, re-login in the browser, resume

**Details:**
- Session file: `.auth/state.enc` (git-ignored)
- Security: encrypted with Fernet; the key is generated on first run and kept in the OS keychain (`keyring`, service `d2l-scraper`). Plaintext never touches disk.
- An invalid session answers `whoami` with HTTP 403 (not a redirect); API calls use `max_redirects=0` so a login redirect is never mistaken for data.
- Session expiry is detected on failure rather than by periodic re-checks
- Possible later hardening: keep only `bright.uvic.ca` cookies (the saved state also holds SSO provider cookies, ~87 KB)

---

## 3. Data Access

**Approach:** Read-only calls to the D2L Valence JSON API using session cookies. No HTML scraping unless an endpoint doesn't exist.

- [x] Resolve API versions at startup with `/d2l/api/versions/` (currently `lp` 1.63, `le` 1.99)
- [x] Rate limit: a **scraping profile** chosen right after login sets how many requests are in flight at once: Polite 3, Fair 6 (default), Aggressive 12 (`PROFILES` in `auth.py`); every profile is parallel. One semaphore in `Session` enforces it across every thread, so nested parallel work (courses × categories × topics) never exceeds it. No extra delay; 429/5xx are retried with back-off. The profile is written in the logs. Changed 2026-09-26 from fully sequential. Measured on 3 real courses: crawl 75s sequential → 31s Polite, 15s Fair, 12s Aggressive (identical results); full download without videos (470 MB) 35s Polite, 20s Fair, 20s Aggressive (connection-bound)
- [x] Retry policy: up to 3 retries on network errors, 429, and 5xx, waiting 1s, 2s, 4s
- [x] Handling of 403s (hidden or unreleased content): the crawl records the category as "not available" and continues

---

## 4. Pipeline

```
login/validate → list courses → select courses → select categories → deep crawl → review → download options → download + metadata
```

### 4.1 Course discovery — DONE
The CLI will list all current and or available courses, the user will be able to select which courses they would like to proceed with

- Courses grouped by term (parsed from the `YYYYMM` course-code prefix), newest first; non-term org units under "Other"
- Courses with `CanAccess: false` are shown greyed out and can't be selected

### 4.2 Review summary — DONE
- [x] After selection, a deep crawl counts items, files, and total size per category
- [x] Shown in one box; ←/→ switches between courses, first page totals all courses

### 4.3 Selection — DECIDED granularity
Once courses have been selected, the user will go on to select which categories of data to collect, the list of categories will be as follows:
content, classlist, grades, discussions, assignments, quizzes, announcements, calendar

- One set of categories applies to all selected courses
- Own submissions and instructor feedback belong to **assignments**
- **Course info** (overview, image, details) is always included and not shown in the picker
- [x] **Calendar** added to the picker and crawler (events fetched for 2000–2100, paged)
- [x] Course info crawled for every course: enrollment data (course details endpoint is 403 for students), overview, overview attachment, banner image

### 4.4 Deep fetch — DONE
- [x] Walk the full content tree only for selected courses and types
- [x] Crawl keeps each file's download URL and the raw API JSON, so the download step doesn't re-crawl

### 4.5 Download options — DECIDED
One more dialog after the review screen, before anything is downloaded:
- [x] **Download videos?** Off by default. Covers MP4 content topics and videos linked from HTML pages. Skipped videos are recorded as links back to Brightspace. The review shows videos as their own row (count, size) and excludes them from the total. Skipped when the crawl found none. _Videos linked from inside HTML pages aren't counted until the HTML pipeline parses pages._
- [x] **Convert to Markdown:** choose which kinds of generated page also get a `.md` copy: content HTML pages, announcements, assignments, discussions, quizzes, grades, course info. Downloaded files are never converted; the `.html` is always kept.

### 4.6 Download
Phase 1 — DONE: raw JSON, all files, `grades.csv`, `classlist.csv`, `calendar.ics`.

Phase 2 — DONE: generated HTML pages, written after the files and rewritten every run (`pages.py`)
- One shared inline style (light and dark), breadcrumb back to `course.html`, dates in local time
- `course info/course.html`: banner, code, dates, role, Brightspace link, overview + attachment
- `announcements/announcements.html`: newest first; author name looked up in the classlist when it was crawled
- `assignments/<name>/assignment.html`: due date, instructions, attachments and link attachments, rubric table (spare empty levels hidden; chosen levels highlighted with score and feedback when `RubricAssessments` exist), my submissions, feedback (score, text, files, links)
- `discussions/<forum>/<topic>.html`: pinned threads first, then newest thread first; replies nested, oldest first; replies whose parent wasn't returned become threads; topics that failed get a note
- `quizzes/quizzes.html`: dates, time limit, attempts, description/instructions, note that questions aren't available
- `grades/grades.html`: uncategorised items, then each category row with its items; ungraded items shown as `– / max`; comments under their row; final grade on top
- Links to downloaded files are relative; files not on disk (skipped videos, failures) are listed with "(not downloaded)"
- Rich text goes through the same rewriting as content pages (phase 3): images embedded, Brightspace links pointed at the archive
- Page names are claimed before files, so existing file paths don't change
- Not tested on a real filled-in rubric (no assessments in the data yet); built from the Valence `RubricAssessment` shape

Phase 3 — DONE: self-contained content pages and linked files (`embed.py`, course files step in `crawl.py`)
- Crawl: HTML content topics are fetched (not listed as plain files). A last "Linked files" step per course scans those pages and every rich-text string in the crawled JSON, HEADs each Brightspace file referenced (`/content/enforced/…`, `/shared/…`, post `ViewAttachment` images), and fetches stylesheets to find their fonts/images. Missing files (HEAD fails, e.g. another course's folder) are counted as "missing on Brightspace" and left as absolute links
- `_course-files/`: `_originals/<module path>/` (HTML as downloaded), `_assets/` (anything embedded: images, CSS, JS, woff2 fonts), everything else mirrors its Brightspace folder (e.g. `Lab1_Videos/…`); linked videos follow the video option
- Embedding: `<img>`, `poster`, stylesheets (with their `url()` images and woff2 fonts; other font formats left as absolute URLs, browsers use woff2) and scripts are inlined; `<a>`, `<iframe>`, `<video>/<source>` link to the local copy. Tags inside `<script>`/`<style>` blocks are never rewritten. Charset declarations become UTF-8
- Brightspace links: quickLinks resolve offline by matching `rcode` (any case) to the `ActivityId` of assignments, quizzes, discussion topics, and content topics; `viewContent`, discussion topic/thread, dropbox `db=`, and quiz `qi=` links are resolved too. Targets: assignment/topic pages, `quizzes.html#quiz-N`, content files/pages, else the topic's entry in `content.html`. LTI links and iframes always go to Brightspace (iframes become a visible "only works inside Brightspace" box)
- Post images that are also post attachments reuse the downloaded attachment (MATH 211: all 141)
- `content/content.html`: every module and topic in instructor order (topics and submodules interleaved by `SortOrder`), module/topic descriptions and dates, broken topics noted
- `content/links.html`: link topics grouped by module (title → archived copy or web address, kind, address)
- Shortcuts in module folders: `.url` for web links and LTI tools; a small redirect `.html` for Brightspace tool links (assignment, quiz, discussion, content) so it opens the archived copy
- The review shows a "Linked files" row; linked videos count in the Videos row (CSC 230: 39 videos, 1.0 GB)
- Tested live on ATWP 135 (UVic template pages, ~690 KB each with Bootstrap/Font Awesome inlined; they render with the network blocked), CSC 230 (lab video pages), MATH 211 (post images)
- Left for later: files from earlier runs that are no longer produced aren't removed (sync); Google Fonts and `s.brightspace.com` stylesheets stay external (decided in 5.2); relative image paths in rich text can't be resolved (no base URL); the instructor-only `dropbox/admin` links stay absolute

Phase 4 — DONE: Markdown copies (`markdown_copy.py`, `markdownify`)
- For the kinds ticked in the options dialog, each generated page gets a `.md` next to its `.html` (same name; claimed in the plan so it can't collide with a downloaded file). Content: the HTML topic pages, `content.html`, and `links.html`; shortcuts never get one
- Generated pages: breadcrumb line, `# Title`, the body, and the archive date. Content pages: the page body only (scripts, styles, `<head>` dropped)
- **Images link to their files on disk** (`_course-files/_assets/…`, `attachments/…`) instead of being embedded (decided 2026-09-26): the `.md` stays readable and images show in any Markdown viewer. Links are the same as in the HTML (archived copies, else Brightspace)
- Grade category rows are bold; tables (grades, rubrics, links) become Markdown tables
- Tested live on the same three courses with every kind ticked: 75 copies, no failures

Phase 6 — DONE (2026-10-05): quiz attempts (`quiz_attempts.py`)
- The crawl fetches each quiz's submissions page and every attempt it links to. Only those two review pages are requested, never a page that starts a quiz, so an attempt can't be started or used up. The same login cookies work; no browser
- What an attempt shows is the instructor's setting, and all of it occurs in the real data: every question with right answers and feedback (CSC 320, CSC 370, MATH 101), only the wrongly answered questions (STAT 260, GEOG 104), the score only (MATH 100), or nothing because it was never submitted ("still in progress"). The page says which
- Parsing (BeautifulSoup): questions start at `<a name="Q<n>">` headers (two header styles: normal and retake); section headings are `h2.dhdg_1`; the instructor's HTML is in `<d2l-html-block html="…">`; answer icons are read by `alt` (`Selected`/`Unselected` radio or checkbox, `Correct Response`, `Incorrect Response`, `Correct Answer`) and shown as ◉ ○ ☑ ☐ and "✓ correct", "✗ incorrect", "✓ correct answer" after the answer. Typed answers keep the right value in brackets. Feedback, retake notes ("Retaken", "Correct on previous attempt(s)"), and points are kept
- An unreadable page keeps its raw copy and is noted on the page
- Question images (`/content/enforced/…`) go through the linked files step and are embedded like any other page image
- MathML stays in the HTML (browsers render it). Markdown copies turn formulas into `$LaTeX$` from the equation editor's annotation, else plain text (any page, not only quizzes)
- `quizzes.html` links each quiz's attempts; the review row shows "N attempts · M questions"
- Tested live: crawl and download of CSC 320, CSC 370, MATH 101 (26 attempts, 333 questions, no failures); parser checked on all 51 attempts in the archive

- Folder structure: see 5.3
- Filename rules: whitespace collapsed; `<>:"/\|?*` and control characters → `_`; trailing dots/spaces trimmed; Windows reserved names (`CON`, `COM1`, …) prefixed with `_`; names capped at 80 characters keeping the extension; file names shortened to keep paths under 250 characters where the folder allows
- Duplicates in the same folder (case-insensitive) → `name (2).ext`; the same crawl always yields the same paths
- Skip-if-present: a file is skipped when it exists with the size the crawl reported (or is non-empty when the size is unknown). JSON and exports are rewritten every run
- Files are written to `<name>.part` and renamed when complete
- Metadata: raw API JSON per category (`<category>.json`; `course info/course.json`)

---

## 5. Content Inventory & Save Formats

> Built from a scan of all 26 accessible courses on 2026-09-26. Counts are across those courses unless noted.

### 5.1 Format principles — DECIDED

1. **Files are saved byte-for-byte** under their original filename. No conversion (a PDF stays a PDF, a PPTX stays a PPTX).
2. **Raw API JSON is always kept**, one file per category per course. It's lossless and lets readable views be regenerated later without re-downloading.
3. **Rich text becomes self-contained HTML.** D2L stores descriptions, instructions, announcements, posts, and feedback as HTML, so it's saved as HTML pages. Images, stylesheets, and scripts they depend on are downloaded and embedded into the page itself (images as `data:` URIs, CSS/JS inlined), so each page is a single file that works offline. Linked documents (PDF, DOCX, …) are downloaded as separate files and links rewritten to them. A Markdown copy of generated pages can be requested in the download options (4.5); downloaded files are never converted.
4. **Tables become CSV** (grades, classlist) for spreadsheets, alongside the raw JSON.
5. **Link-only items are recorded, not downloaded**: title, URL, where it appeared.
6. **Dates stay ISO 8601 UTC** as the API returns them; readable pages show local time.

### 5.2 Inventory

Tier: **Easy** = direct API download · **Medium** = needs assembling or rewriting · **Link** = recorded only · **Blocked** = API refuses students

#### Content (table of contents)

| Item | Found | Source | Saved as | Tier |
|---|---|---|---|---|
| Module (folder) | 135 with descriptions | `content/toc` | Directory; title, dates, description in `content.json` and on the module's page | Easy |
| File topic: document | 624 PDF, 48 PPTX, 14 DOCX, 4 ZIP, 14 TeX, code (`.asm`, `.c`, `.java`, `.h`, `.inc`), 11 images, 5 with no extension | `content/topics/{id}/file` | Original file | Easy |
| File topic: video | 14 MP4 | same | Original file, only if videos are opted in (4.5); otherwise a link record | Easy |
| File topic: HTML page | 129 | same, or the topic's `/content/enforced/…` URL | `.html` with its dependencies downloaded and links rewritten (below) | Medium |
| Topic description | 72 | `content/toc` | In `content.json` and on the module page | Easy |
| Link topic: web link (ActivityType 2) | 117 (Google Docs/Drive, YouTube, textbooks, Zoom, Teams, Crowdmark, WeBWorK, …) | `content/toc` | Link record | Link |
| Link topic: Brightspace tool shortcut (ActivityType 3–6: assignment 17, quiz 13, forum 4, discussion topic 58) | 92 | `content/toc` | Cross-reference to the archived item in its own category; web URL if that category wasn't selected | Link |
| Link topic: LTI tool (ActivityType 7: YuJa/Kaltura video, publisher tools) | 49 | `content/toc` | Link record (launch URL only works while enrolled) | Link |
| Link topic: survey / checklist (ActivityType 12, 10) | 3 / 1 | `content/toc` | Link record | Link |

**HTML page dependencies** (references found inside the 129 pages):

| Reference | Found | Handling |
|---|---|---|
| Images under `/content/enforced/…` or relative | ~90 | Download and embed as `data:` URI |
| Course files linked but not listed as topics (PDFs, PPTX, DOCX, XLSX) | ~65 links | Download into `_course-files/`, rewrite `href` |
| Course videos linked from pages (e.g. CSC 230 lab `.mp4`s) | ~40 links | Download into `_course-files/` only if videos are opted in; otherwise absolute Brightspace URL |
| UVic HTML template assets under `/shared/…` (CSS, JS, images) | ~480 refs | Download and inline into each page (cache the downloads so each asset is fetched once per run) |
| `s.brightspace.com` scripts/fonts (web components) | ~670 refs | Leave as-is; pages stay readable without them |
| LTI video iframes (quickLink `type=lti`) | 49 | Replace with a visible link box: "Embedded video (only viewable in Brightspace)" |
| YouTube / Google iframes | 9 | Leave as-is (works online) |
| Internal Brightspace links (`/d2l/le/…`, quickLinks) | ~110 | Rewrite to the local archived copy when possible, else absolute Brightspace URL |
| `data:` images, `mailto:`, external links | many | Leave as-is |

#### Announcements

| Item | Found | Source | Saved as | Tier |
|---|---|---|---|---|
| Announcement (title, body, dates) | 53 in 3 test courses | `news/` | One `announcements.html` feed (newest first) + `announcements.json` | Easy |
| Attachment | 2 in 3 test courses | `news/{id}/attachments/{fileId}` | Original file under `attachments/` | Easy |
| Images embedded in body | 155 | `/content/enforced/…` | Downloaded + embedded, as for HTML pages | Medium |
| Brightspace links in body (quickLinks, `/d2l/le/…`) | ~155 | — | Rewritten like HTML pages | Medium |

#### Assignments (dropbox)

| Item | Found | Source | Saved as | Tier |
|---|---|---|---|---|
| Assignment (name, due date, instructions HTML) | 62 folders, 38 with instructions | `dropbox/folders/` | `assignment.html` per assignment + `assignments.json` | Easy |
| Instructor attachment | — | `…/attachments/{fileId}` | Original file under `attachments/` | Easy |
| Rubric definition (criteria, levels, points) | 16 assignments | Inline in folder `Assessment.Rubrics` | Rendered as a table in `assignment.html`; raw in JSON | Easy |
| My submission (files, comment, date) | e.g. 6 in CSC 230 | `…/submissions/mysubmissions/` | Files under `submissions/<date>/`, comment in `assignment.html` | Easy |
| Feedback (text, score, links) | 29 (25 with text) | same (`Feedback` field) | In `assignment.html` | Easy |
| Feedback file | 1 | `…/feedback/{type}/{id}/attachments/{fileId}` | Original file under `feedback/` | Easy |
| Rubric assessment (levels picked, scores, criterion feedback) | 5 | same (`RubricAssessments`) | Filled-in rubric table in `assignment.html` | Medium |
| Dropbox unavailable | 3 courses (HTTP 403) | — | Noted in crawl | — |

#### Grades

| Item | Found | Source | Saved as | Tier |
|---|---|---|---|---|
| My grade values (points, weighted, displayed grade) | 191 | `grades/values/myGradeValues/` | `grades.csv` + `grades.html` + `grades.json` | Easy |
| Grade comments | 28 | same (`Comments`) | Column in CSV (plain text), HTML in `grades.html` | Easy |
| Grade item definitions (max points, weight, category) | e.g. 19 in CSC 230 | `grades/` | Joined into the grade rows | Easy |
| Grade categories | e.g. 7 in CSC 230 | `grades/categories/` | Grouping in CSV/HTML | Easy |
| Final grade | Released in 1 course (404 otherwise) | `grades/final/values/myGradeValue` | Row in grades files | Easy |
| Grade schemes | HTTP 403 | — | Not available | Blocked |

#### Discussions

| Item | Found | Source | Saved as | Tier |
|---|---|---|---|---|
| Forum / topic (name, description, dates) | e.g. 4 forums in CSC 320 | `discussions/forums/…/topics/` | Directory per forum; details in the topic page | Easy |
| Post (subject, message HTML, author, date, thread structure) | 201 in 3 test courses | `…/topics/{id}/posts/` | One `<Topic>.html` per topic showing threads + `discussions.json` | Medium |
| Post attachment | 34 in 3 test courses | `…/posts/{id}/attachments/{fileId}` | Original file under `<Topic>/attachments/` | Easy |
| Images embedded in posts | not measured | `/content/enforced/…` | Downloaded + embedded | Medium |

#### Quizzes

| Item | Found | Source | Saved as | Tier |
|---|---|---|---|---|
| Quiz (name, instructions, description, dates, time limit) | e.g. 4 in 3 test courses | `quizzes/` | `quizzes.html` + `quizzes.json` (+ `quizzes.md` if chosen) | Easy |
| Questions / my attempts (API) | — | `quizzes/{id}/questions/`, `/attempts/` | HTTP 403 for students in every course tried | Blocked |
| My attempts (review pages) | 51 attempts, 426 questions in 12 courses | `/d2l/lms/quizzing/user/quiz_submissions.d2l?qi=&ou=` lists them; `quiz_submissions_attempt.d2l?qi=&ai=&ou=` shows one | `<Quiz>/attempts.html` (+ `.md`), raw page in `<Quiz>/_originals/attempt N.html` | Medium |

#### Classlist

| Item | Found | Source | Saved as | Tier |
|---|---|---|---|---|
| People (name, username, email, role) | e.g. 279 in 3 test courses | `classlist/` | `classlist.csv` + `classlist.json` (privacy: see 5.4) | Easy |
| Groups / sections | e.g. 1 group category in CSC 230 | `lp/{ou}/groupcategories/` | In `classlist.json` | Easy |

#### Course info (always included)

| Item | Found | Source | Saved as | Tier |
|---|---|---|---|---|
| Course details (name, code, term, dates) | all | enrollment data | `course.html` + `course.json` | Easy |
| Course image (banner) | all | `lp/courses/{ou}/image` | `course-image.jpg` | Easy |
| Course overview / syllabus | 5 courses (1 with attachment) | `overview`, `overview/attachment` | In `course.html` + attachment | Easy |

#### Calendar

| Item | Found | Source | Saved as | Tier |
|---|---|---|---|---|
| Calendar events | e.g. 6 in CSC 230 (mostly due dates) | `calendar/events/myEvents/` (needs a date range) | `calendar.ics` (importable) + `calendar.json` | Easy |

### 5.3 Folder layout

```
<output root>/                          default <repo>/D2L Archive/, git-ignored (contains classlist personal data)
  Spring 2025 CSC 230 A01 - A04 X/      course folder = D2L course name, which already includes the term
    course info/                        always included
      course.html   course.json   course-image.jpg   (+ overview attachment, if any)
    content/
      01 Course Outline/                modules in instructor order
        Welcome Letter.pdf              files in their original format
        Office Hours.html               self-contained page (images/CSS/JS embedded)
        Course Notes Link.url           shortcut for a web link or external tool
        Lab 2.html                      redirect to the archived copy of a Brightspace tool link
      02 Week 1/…
      content.html                      outline: every module and topic with descriptions
      links.html                        every link-only item, grouped by module
      content.json
    announcements/
      announcements.html   announcements.json
      attachments/…
    assignments/
      Lab2 Submissions/
        assignment.html                 instructions, rubric, my submissions, feedback
        attachments/  submissions/2025-01-24/  feedback/
      assignments.json
    discussions/
      <Forum>/<Topic>.html
      <Forum>/<Topic>/attachments/…
    _course-files/                      per course, shared by all categories
      _originals/01 Course Outline/…    HTML content pages as downloaded
      _assets/…                         images, CSS, JS, fonts embedded into pages
      Lab1_Videos/…                     linked documents (and opted-in videos), in their Brightspace folders
      discussions.json
    grades/        grades.html   grades.csv   grades.json
    quizzes/       quizzes.html   quizzes.json
      <Quiz>/attempts.html          every attempt: score, questions, your answers, right answers, feedback
      <Quiz>/_originals/attempt 1.html   each attempt's review page as downloaded
    classlist/     classlist.csv   classlist.json
    calendar/      calendar.ics   calendar.json
```

When Markdown conversion is chosen for a category, each generated `.html` gets a `.md` next to it (e.g. `announcements.md`, `Lab2 Submissions/assignment.md`). The `.html` is always kept as the backup.

Non-term org units (advising, makerspace, …) have no term in their name, so their folder is just the name. Folder names sort alphabetically, not by term.

### 5.4 Decisions

1. **Rich text:** HTML is the default readable format for everything the tool generates.
2. **Link-only items:** one `links.html` per course, plus `.url` shortcut files inside module folders (`.url` opens natively on Windows only).
3. **Module folder order:** prefix with `01 `, `02 ` to keep the instructor's order.
4. **Videos:** opt-in, asked in the download options dialog after the review (4.5).
5. **HTML page dependencies:** downloaded and embedded into the HTML files (self-contained pages). Linked documents are saved as separate files. Trade-off: template CSS/JS is duplicated in every page, so pages are larger.
6. **New categories:** **calendar** is added to the category picker. **Course info** is always included, without asking.
7. **Classlist:** keep everything, including other students' emails. The archive lives in the repo's git-ignored `D2L Archive/` folder (or outside the repo); it must never be committed.
8. **Quizzes:** metadata from the API, plus my attempts from the review pages students see (decided 2026-10-05; the API blocks questions and attempts). Part of the quizzes category, no extra prompt. Every attempt is kept, since attempts can show different questions. Per quiz: one generated page with all attempts, a Markdown copy when quizzes are chosen for Markdown, and the raw review pages. No JSON for attempts.
9. **Out of scope:** Locker, ePortfolio, awards, and email.
10. **Markdown conversion scope:** only pages the tool generates from HTML/JSON (content HTML pages, announcements, assignments, discussions, quizzes, grades, course info). Downloaded files (PDF, slides, images, video, …) always stay in their original format. The `.html` is kept alongside as the backup.
11. **Metadata:** raw API JSON is kept for every category (`<category>.json`). It's the source for sync and for regenerating pages.
12. **Term in folder name:** course folders use the D2L course name (e.g. `Spring 2025 CSC 230 A01 - A04 X`), which includes the term, instead of a separate term folder level.

### 5.5 Implementation notes

- HTML topics: use the API `…/file` endpoint. It returns the page as authored; the topic's `/content/enforced/…` URL wraps it in Brightspace viewer scripts (447 vs 6273 bytes for the same page).
- Broken content topics (`IsBroken: true`, `Url: null`) have no file on Brightspace (404). The crawl skips them and notes "N broken files" (5 in ENGR 240).
- Some discussion topics return HTTP 500 on every attempt (2 of 21 in ATWP 135). The crawl records them in `discussions.json` with an `error` and keeps the rest of the category.
- Course details (`lp/courses/{ou}`) is 403 for students; `course.json` uses the enrollment record instead.
- All file endpoints tested (content, news/post/dropbox attachments, submissions, overview attachment, course image) return 200 with the file directly, no redirects.
- Discussion posts endpoint returned all posts without paging (71 in one topic); watch for paging on very large topics.
- Quizzes list is paged (`Next`); enrollments are paged (`Bookmark`).

---

## 6. Output

- Format: _TBD_ (plain folder tree / browsable offline `index.html` / both). The per-item HTML pages in 5.3 make an `index.html` cheap to add.
- Output root location: `<repo>/D2L Archive/` by default (git-ignored as `/D2L Archive/`), asked in the download options. Other folders inside the repo are refused, since only that one is ignored
- Mode: re-runnable; files already present are skipped (full sync of changed/removed items: later)
- If sync: how to detect changed or removed items: _TBD_

---

## 7. Logging & Reporting

DONE (phase 5, `runlog.py`); decided 2026-09-26: a log in each course folder plus one for the whole archive, both detailed.

- **`<course>/download log.txt`:** run start/end and length, result (completed, or stopped early with the reason: cancelled, session expired, error), options, course code/id/term; the crawl per category (items, files, size, links, notes, or why it couldn't be crawled); every file downloaded with its size; the number already in the archive (not listed, so re-runs stay short); every video skipped with its size; files linked from pages but missing on Brightspace; every page and Markdown copy written; every failure with its reason
- **`<archive>/download log.txt`:** the same header, a table with one row per course (downloaded, size, skipped, videos skipped, pages, failures) and a total, categories that couldn't be crawled, and every failure across courses (paths from the archive root)
- Each run is **appended**, so the logs keep every run's history. Logs are written even when a run stops early (in a `finally`), so a cancelled or expired run still records what it did
- The terminal summary ends with the log's path; its counts now come from the same per-course records as the logs

---

## 8. Tech Stack

- Language: Python (3.10+)
- Auth / HTTP: Playwright (`sync_playwright`) only for the browser login; every request goes through one `httpx` client built from the saved cookies (thread-safe, rebuilt on re-login), files streamed to disk
- Session encryption: `cryptography` (Fernet) + `keyring`
- Selection UI: `questionary` (prompts run on a worker thread because `sync_playwright` owns the main thread's event loop)
- Display: `rich` (spinners, progress, review box rendered into a `prompt_toolkit` app)

---

## 9. Constraints & Etiquette

- [x] Read-only: no write or modify calls
- [x] Personal use, own courses only
- [x] Polite rate limiting
- [ ] Review the institution's acceptable-use policy

---

## 10. Open Questions

- Session re-check interval and pause/re-login during downloads (section 2)

---

## 11. Study pack for NotebookLM — DONE (2026-10-05)

Built in `studypack.py` (`python studypack.py [archive]` on its own; "Build a study pack for NotebookLM for:" after the course picker in the main run). Answer keys come from `quiz_attempts.study_card`. Implementation notes:
- Pages: the `.md` copy when there is one, else the `.html` converted; breadcrumb, page title, and footer dropped (each page is merged under its own heading); images become `[image]`
- Content order: `content.json` topic order per module, then anything else alphabetically; each top-level module's text document comes first in that module. `content.html`/`links.html` at the content root are skipped (the outline is in the overview)
- Code and text files (`.java`, `.c`, `.asm`, `.tex`, `.txt`, …, up to 200 KB) go into the module's text document in code blocks, also when attached to assignments
- Assignment attachments are sources in an "Assignment files" group; submissions and returned feedback files are left out
- Linked documents in `_course-files/` (not `_assets`, `_originals`) are included as a "Linked files" group
- Duplicates by SHA-1 of the file
- Turning slides into text only saves sources when a module has several slide/Word files or already has a text document
- The pack is written to `.<course>.building` and swapped in; an existing folder without `manifest.md` is never replaced
- A failed pack in the main run is a failure in the course log; the archive itself is unaffected
- Tested: synthetic archive (`tests/test_studypack.py`), and every course in the real archive

Goal: per course, a small set of clean sources to upload to a NotebookLM (Gemini) notebook. NotebookLM does the concept extraction; the pack's job is low noise, few files, clear provenance.

**NotebookLM limits (checked 2026-10-05):** 50 sources per notebook on Free (Plus 100, Pro 300); each source up to 500,000 words or 200 MB. Accepts PDF, Word, PowerPoint, Markdown, text, images, audio, websites, YouTube. No conversion is needed for Office files.

**Decisions (2026-10-05):**
1. **Entry points:**
   - **In the main run (decided 2026-10-05):** right after the course picker, a checkbox "Build a study pack for:" lists the courses just picked, none ticked (enter skips it). Packs are built after the download finishes, from what's on disk, so files from earlier runs count too. The summary prints each pack's folder and source count; the course's download log records the build.
   - **`python studypack.py`:** the same builder, offline over an existing archive (no login, no Brightspace requests); pick from the archive's course folders. For rebuilding a pack without downloading again.
   - Either way, re-running rebuilds the pack from scratch.
   - If a category the pack draws on (content, assignments, quizzes, discussions, announcements) is unticked in the category picker, the pack uses whatever an earlier run left on disk, and the manifest says which parts are missing.
2. **One pack per course.** Combined multi-course packs: later, if wanted.
3. **Location:** `<archive>/Study Packs/<course>/`, apart from the course folders.
4. **Source limit:** Free plan; the pack targets **45 sources**, leaving room for a few of your own.
5. **Practice questions: answer key only.** Per question: the question, its choices, `Correct answer: …`, and feedback. Your own selections aren't shown. "Answer not shown" when the attempt doesn't reveal it.
6. **Unique questions:** all questions from every attempt of a quiz are combined into one section per quiz. The same question appears once, matched on its text plus its answer choices (`Question.prompt` + choices). Questions that differ per attempt, like MATH 101's numbers, stay separate. The version kept is one that shows the correct answer, else the latest attempt.

**Layout:**
```
Study Packs/Fall 2026 CSC 320 A01 A02 X/
  01 Course overview.md       course info, content outline, announcements (dated)
  02 Practice questions.md    a section per quiz
  03 Assignments.md           instructions, rubrics, feedback
  04 Discussions.md           threads, replies nested
  10 Lectures - Unit I - 02-FA.pdf    downloaded files in their own format, named by module path, instructor order
  30 Tutorials.md             HTML content pages of a module, merged as text
  manifest.md                 what's in, what was left out and why, web links to add by hand (not a source)
```

**Content rules:**
- Kept: content files (PDF, pptx, docx, xlsx, images), HTML content pages (as text), assignments, quiz questions, discussions, announcements, course info and outline
- Left out: classlist, grades, calendar, raw JSON, `_course-files/_assets`, `.url`/redirect shortcuts, videos. Web links are listed in the manifest
- Generated pages: use the `.md` copy when it exists, else convert the `.html` (data-URI images dropped)
- The same file in two places (same content hash) is included once

**Answer key from the attempt marks:**
- Single choice: the option marked "✓ correct answer", or selected and "✓ correct"
- Multi-select: selected and ✓, plus unselected and ✗ (each row's mark is whether that row was answered right)
- Typed answer: the value when ✓, the bracketed value when ✗
- Matching: the pairs when marked ✓; otherwise "Answer not shown"

**Fitting 45 sources**, in order, one module at a time (the one with the most files first), stopping as soon as it fits, so as much as possible stays as it was:
1. Merge a module's PDFs and images into one PDF (pypdf; images become pages via Pillow), with the original file names as bookmarks, in parts over 190 MB; then the same per top-level module (CSC 225 has 64 files in 41 module folders, so per-module merging alone lands near the limit)
2. Move a top-level module's pptx/docx text into its text document (read straight from the Office XML: slide text and speaker notes, paragraphs). Loses visuals, so last
3. Whatever still doesn't fit is left out, largest file first, and listed in the manifest; nothing is dropped silently

Merging is slow on large PDFs (pypdf): a few seconds for most courses, 2 to 10 minutes for courses with hundreds of MB of scanned notes (MATH 211, STAT 260). The build shows which source it's on.

**Upload:** by hand, dragging the pack folder's files (not `manifest.md`) into a new notebook. No automation; consumer NotebookLM has no API.
