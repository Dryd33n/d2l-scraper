"""List the user's course enrollments, grouped by term."""

import re
from dataclasses import dataclass, field
from itertools import groupby

from playwright.sync_api import sync_playwright

from auth import Session, connect

COURSE_OFFERING = 3  # D2L org unit type id for course offerings
TERM_SEASONS = {"01": "Spring", "05": "Summer", "09": "Fall"}  # UVic term codes: YYYYMM


@dataclass
class Course:
    id: int
    code: str
    name: str
    can_access: bool
    term: str | None  # "202609", or None for non-term org units (advising, makerspace, ...)
    enrollment: dict = field(default_factory=dict, repr=False)  # raw enrollment JSON, saved as course.json

    @property
    def term_label(self) -> str:
        if self.term is None:
            return "Other"
        return f"{TERM_SEASONS.get(self.term[4:], self.term[4:])} {self.term[:4]}"

    @property
    def short_name(self) -> str:
        """The name without its leading term ("Fall 2026 CSC 320 ..." -> "CSC 320 ..."), for use under a term heading."""
        return self.name.removeprefix(f"{self.term_label} ")


def list_courses(session: Session) -> list[Course]:
    """Fetch every course-offering enrollment, following the API's bookmark paging."""
    courses = []
    bookmark = None
    while True:
        params = {"orgUnitTypeId": COURSE_OFFERING}
        if bookmark:
            params["bookmark"] = bookmark
        page = session.get_json("/d2l/api/lp/{lp}/enrollments/myenrollments/", params)

        for item in page["Items"]:
            org, access = item["OrgUnit"], item["Access"]
            term = re.match(r"(\d{4}(?:01|05|09)) ", org["Code"])
            courses.append(Course(
                id=org["Id"],
                code=org["Code"],
                name=org["Name"],
                can_access=access["CanAccess"],
                term=term.group(1) if term else None,
                enrollment=item,
            ))

        if not page["PagingInfo"]["HasMoreItems"]:
            return courses
        bookmark = page["PagingInfo"]["Bookmark"]


def by_term(courses: list[Course]) -> list[tuple[str, list[Course]]]:
    """Group courses by term label, newest term first, non-term org units last, names A-Z."""
    ordered = sorted(courses, key=lambda c: c.name)
    ordered.sort(key=lambda c: c.term or "", reverse=True)  # stable: names stay A-Z within a term
    return [(label, list(group)) for label, group in groupby(ordered, key=lambda c: c.term_label)]


def print_courses(courses: list[Course]) -> None:
    for label, group in by_term(courses):
        print(f"\n{label}")
        for c in group:
            flag = "" if c.can_access else "  [no access]"
            print(f"  {c.id:>7}  {c.name}{flag}")


def main() -> None:
    with sync_playwright() as p:
        session = connect(p)
        courses = list_courses(session)
        print(f"{len(courses)} courses for {session.user['FirstName']} {session.user['LastName']}")
        print_courses(courses)


if __name__ == "__main__":
    main()
