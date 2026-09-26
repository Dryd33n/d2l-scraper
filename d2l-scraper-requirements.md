# D2L Scraper — Requirements

> Status: In progress (phase 1 download built: files, raw JSON, CSV, ICS; generated HTML pages next)
> Last updated: 2026-09-26

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
- [x] Rate limit: sequential requests, one at a time, no extra delay
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
| Questions / my attempts | — | `quizzes/{id}/questions/`, `/attempts/` | HTTP 403 for students in every course tried | Blocked |

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
        Course Notes Link.url           shortcut for a link-only item
      02 Week 1/…
      _course-files/…                   documents (and opted-in videos) linked from HTML pages
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
      discussions.json
    grades/        grades.html   grades.csv   grades.json
    quizzes/       quizzes.html   quizzes.json
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
8. **Quizzes:** metadata only (the API blocks questions and attempts). HTML by default, Markdown if chosen, like other generated pages. Scraping attempt-review pages through the browser is possible later.
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

- End-of-run summary (downloaded / skipped / failed / link-only): _TBD_
- Log file location and verbosity: _TBD_

---

## 8. Tech Stack

- Language: Python (3.10+)
- Auth / HTTP: Playwright (`sync_playwright`, `request.new_context`)
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
- Rate limit and retry policy (section 3)
