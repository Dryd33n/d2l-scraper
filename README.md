# D2L Scraper

Download your D2L Brightspace courses before you lose access to them. You get one folder per course that works offline, and you can turn any course into a study pack for [NotebookLM](https://notebooklm.google.com).

It's been used in full at UVic. Other schools run the same API and should work, but [open an issue](https://github.com/Dryd33n/d2l-scraper/issues) if yours doesn't.

## Install

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/Dryd33n/d2l-scraper/master/install.ps1 | iex
```

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/Dryd33n/d2l-scraper/master/install.sh | sh
```

You don't need Python or admin rights. The script uses [uv](https://docs.astral.sh/uv/) to set up its own private copy of Python.

## Usage

Run `d2l-scraper` and follow the prompts. The first time, it asks for a link to your school's Brightspace and opens a browser window for you to log in, so SSO and MFA work as usual.

Pick your courses and what to download from each. Everything gets crawled first, and nothing downloads until you've seen what it adds up to:

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

Run it again any time to pick up anything new or resume an interrupted download. Files you already have are skipped.

| Command | |
|---|---|
| `d2l-scraper update` | Install the latest version |
| `d2l-scraper logout` | Forget your saved login |
| `d2l-scraper school [link]` | Switch to another school |
| `d2l-scraper studypack [folder]` | Rebuild study packs from an existing archive, no login needed |

To uninstall, run `d2l-scraper logout`, then `uv tool uninstall d2l-scraper`.

## What you get

```
D2L Archive/
  Study Packs/                 if you asked for any
  Spring 2025 CSC 230 A01/
    content/                   files in their original format, in the instructor's order
    announcements/
    assignments/               instructions, rubrics, your submissions, feedback
    discussions/               threads with replies nested
    grades/                    also as a spreadsheet
    quizzes/                   your attempts, with answers and feedback where the quiz shows them
    classlist/                 spreadsheet
    calendar/                  .ics you can import
    course info/
```

Pages are saved as HTML with their images embedded, and links between Brightspace items point at your local copies. You can also get a Markdown copy of any page, with formulas as LaTeX. Videos are optional and off by default.

## Study packs

NotebookLM's free plan allows 50 sources per notebook, so a study pack squeezes a course into at most 45: lecture files, the course overview, assignments, discussions, and a practice sheet of every quiz question you've seen, with its answer when the quiz showed one. If a course has too many files, PDFs get merged by module.

Create a notebook and upload everything in the course's folder except `manifest.md`. That file lists what's in each source and anything that was left out.

## Privacy

The tool reads from Brightspace and never changes anything. It uses the read-only API, plus your quiz review pages because the API doesn't expose those. It never opens a page that starts a quiz, so it can't use up an attempt.

Your password never reaches the tool, since you type it into the browser. The login session is stored encrypted, with the key in your OS keychain. On Linux without a keychain service, you log in on every run.

## Development

```bash
git clone https://github.com/Dryd33n/d2l-scraper.git
cd d2l-scraper
python -m venv .venv
.venv/Scripts/activate      # macOS / Linux: source .venv/bin/activate
pip install -e .
d2l-scraper
```

Tests are plain scripts, for example `python tests/test_setup.py`. `tests/test_auth.py` needs a real login. Design notes are in [`d2l-scraper-requirements.md`](d2l-scraper-requirements.md).

## Disclaimer

This is a personal project, not affiliated with D2L or any school. Only use it on courses you're enrolled in, and follow your school's acceptable-use policy.
