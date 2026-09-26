"""Spreadsheet and calendar exports built from crawled JSON: grades.csv, classlist.csv, calendar.ics."""

import csv
import html
import re
from datetime import datetime, timezone
from pathlib import Path

from auth import BASE_URL


def _text(value) -> str:
    """Plain text from a D2L RichText ({"Text", "Html"}) or a string that may contain HTML."""
    if isinstance(value, dict):
        value = value.get("Text") or value.get("Html")
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value or "")).split())


def _number(value) -> str:
    return "" if value is None else f"{value:g}"


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    # utf-8-sig so Excel detects UTF-8 and shows accented names correctly
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def write_grades_csv(data: dict, path: Path) -> None:
    items = {str(i["Id"]): i for i in data["items"]}
    categories = {c["Id"]: c["Name"] for c in data["categories"]}

    rows = []
    for v in [*data["values"], *([data["final"]] if data["final"] else [])]:
        is_category = v["GradeObjectTypeName"] == "Category"
        item = items.get(v["GradeObjectIdentifier"], {})
        rows.append([
            v["GradeObjectName"] if is_category else categories.get(item.get("CategoryId"), ""),
            "" if is_category else v["GradeObjectName"],
            v["GradeObjectTypeName"],
            _number(v["PointsNumerator"]),
            _number(v["PointsDenominator"]),
            _number(v["WeightedNumerator"]),
            _number(v["WeightedDenominator"]),
            v.get("DisplayedGrade") or "",
            _text(v.get("Comments")),
            v.get("LastModified") or "",
        ])
    _write_csv(path, ["Category", "Item", "Type", "Points", "Out of", "Weighted", "Weight out of",
                      "Grade", "Comments", "Last modified"], rows)


def write_classlist_csv(data: dict, path: Path) -> None:
    rows = [[
        p.get("DisplayName") or "",
        p.get("FirstName") or "",
        p.get("LastName") or "",
        p.get("Username") or "",
        p.get("Email") or "",
        p.get("ClasslistRoleDisplayName") or "",
        p.get("OrgDefinedId") or "",
        p.get("LastAccessed") or "",
    ] for p in data["people"]]
    _write_csv(path, ["Name", "First name", "Last name", "Username", "Email", "Role", "Org ID", "Last accessed"], rows)


def _ics_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_fold(line: str) -> list[str]:
    """Split a content line into 75-octet chunks, continuation lines starting with a space (RFC 5545)."""
    out, current = [], ""
    for ch in line:
        limit = 75 if not out else 74  # continuation lines lose one octet to the leading space
        if len((current + ch).encode()) > limit:
            out.append(current)
            current = ch
        else:
            current += ch
    out.append(current)
    return [out[0], *(" " + part for part in out[1:])]


def _ics_time(iso: str) -> str:
    """"2025-01-26T07:59:59.000Z" -> "20250126T075959Z"."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%Y%m%dT%H%M%SZ")


def _ics_day(value: str) -> str:
    return value[:10].replace("-", "")


def write_calendar_ics(events: list[dict], path: Path) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    host = BASE_URL.removeprefix("https://")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//d2l-scraper//EN", "CALSCALE:GREGORIAN"]
    for e in events:
        lines += ["BEGIN:VEVENT", f"UID:{e['CalendarEventId']}@{host}", f"DTSTAMP:{stamp}"]
        if e.get("IsAllDayEvent") and e.get("StartDay"):
            lines.append(f"DTSTART;VALUE=DATE:{_ics_day(e['StartDay'])}")
            if e.get("EndDay"):
                lines.append(f"DTEND;VALUE=DATE:{_ics_day(e['EndDay'])}")
        else:
            lines.append(f"DTSTART:{_ics_time(e['StartDateTime'])}")
            if e.get("EndDateTime"):
                lines.append(f"DTEND:{_ics_time(e['EndDateTime'])}")
        lines.append(f"SUMMARY:{_ics_escape(e.get('Title') or '')}")
        if description := _text(e.get("Description")):
            lines.append(f"DESCRIPTION:{_ics_escape(description)}")
        if e.get("LocationName"):
            lines.append(f"LOCATION:{_ics_escape(e['LocationName'])}")
        if e.get("CalendarEventViewUrl"):
            lines.append(f"URL:{e['CalendarEventViewUrl']}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")

    folded = [part for line in lines for part in _ics_fold(line)]
    path.write_bytes(("\r\n".join(folded) + "\r\n").encode())
