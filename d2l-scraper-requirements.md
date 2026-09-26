# D2L Scraper — Requirements

> Status: Planning
> Last updated: YYYY-MM-DD

---

## 1. Overview

**Purpose:** Archive course data from a D2L Brightspace instance for personal use, letting the user pick which courses and which kinds of content to download.

**Target instance(s):**
- [ ] UVic only (`https://bright.uvic.ca`)
- [ ] Any D2L instance (configurable base URL)

UVic only for now, we will attempt to implement any D2L instance later

**Out of scope:**
- _TBD_

---

## 2. Authentication — DECIDED

**Approach:** Playwright browser login with saved session state.

- [x] Open a headed browser; the user logs in manually (SSO + MFA handled by the user)
- [x] Save the session with `storage_state` to a local file
- [x] Before each run, check the session with `/d2l/api/lp/{ver}/users/whoami`
- [x] If the session is invalid or expired, prompt for a fresh login
- [x] Re-check periodically during long downloads; pause instead of failing silently

**Open details:**
- Where the session file is stored: _TBD_
- How often to re-check the session during downloads: _TBD_
- Security of the saved session file (gitignore, file permissions, encryption?): _TBD_

---

## 3. Data Access

**Approach:** Read-only calls to the D2L Valence JSON API using session cookies. No HTML scraping unless an endpoint doesn't exist.

- [x] Resolve API versions at startup with `/d2l/api/versions/`
- [ ] Rate limit: _TBD_ (delay between requests, max concurrency)
- [ ] Retry policy for failed requests: _TBD_
- [ ] Handling of 403s (hidden or unreleased content): skip and log? _TBD_

---

## 4. Pipeline

```
login/validate → list courses → per-type summary → user selection → deep fetch → download + metadata
```

### 4.1 Course discovery
The CLI will list all current and or available courses, the user will be able to select which courses they would like to proceed with

### 4.2 Per-type summary (shown before selection)
- [x] Show rough counts/sizes per content type for each course, without a full tree walk
- Fields to show per course: _TBD_

### 4.3 Selection — DECIDED granularity
Once courses have been selected, the user will go on to select which categories of data to collect, the list of categories will be as follows:
content, classlist, grades, discussions, assignments, quizzes, announcements

### 4.4 Deep fetch
- [x] Walk the full content tree only for selected courses and types

### 4.5 Download
- Folder structure: _TBD_ (mirror module tree / group by type)
- Filename sanitizing rules: _TBD_
- Skip already-downloaded files: _TBD_
- Metadata JSON stored with downloads: _TBD_ (fields: dates, descriptions, grades, feedback, source URLs...)

---

## 5. Content Types

| Content type | Include? | Difficulty | Notes |
|---|---|---|---|
| Content files (PDFs, slides, docs) | | Easy | |
| Announcements | | Easy | |
| Grades | | Easy | |
| Assignment instructions + attachments | | Easy | |
| Own submissions | | Easy | |
| Calendar events | | Easy | |
| HTML content pages (+ embedded files) | | Medium | Rewrite internal links? |
| Discussions | | Medium | Paging |
| Instructor feedback / rubrics | | Medium | |
| Embedded video (Kaltura / YuJa / Panopto) | | Hard | Probably record link only |
| External links / LTI tools | | Hard | Record link only |
| Quizzes | | Hard | Often unavailable after close |

**Handling for the hard tier:** record that the item exists, with its link, instead of downloading it. _Confirm or change._

---

## 6. Output

- Format: _TBD_ (plain folder tree / browsable offline `index.html` / both)
- Output root location: _TBD_
- Mode: _TBD_ (one-shot archive / re-runnable sync)
- If sync: how to detect changed or removed items: _TBD_

---

## 7. Logging & Reporting

- End-of-run summary (downloaded / skipped / failed / link-only): _TBD_
- Log file location and verbosity: _TBD_

---

## 8. Tech Stack

- Language: Python
- Auth / HTTP: Playwright (`sync_playwright`, `request.new_context`)
- Selection UI library: _TBD_
- Other dependencies: _TBD_

---

## 9. Constraints & Etiquette

- [x] Read-only: no write or modify calls
- [x] Personal use, own courses only
- [x] Polite rate limiting
- [ ] Review the institution's acceptable-use policy

---

## 10. Open Questions

- _Add as they come up_
