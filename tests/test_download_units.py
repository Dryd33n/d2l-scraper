import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root
from download import safe_name, Namer, MAX_PATH
from exports import _ics_fold, write_calendar_ics, write_grades_csv

def check(name, got, want):
    print("PASS" if got == want else f"FAIL (got {got!r})", name)

check("invalid chars", safe_name('a<b>c:d"e/f\\g|h?i*j.pdf'), "a_b_c_d_e_f_g_h_i_j.pdf")
check("trailing dots/spaces", safe_name("Notes. . "), "Notes")
check("reserved name", safe_name("CON.txt"), "_CON.txt")
check("whitespace collapsed", safe_name("  Week   1\tSlides "), "Week 1 Slides")
check("empty", safe_name("   "), "_")
long = "x" * 200 + ".pdf"
check("long name keeps extension", (len(safe_name(long)), safe_name(long)[-4:]), (80, ".pdf"))
check("unicode space normalised", safe_name("Screenshot 1\u202fPM.png"), "Screenshot 1 PM.png")

n = Namer()
d = Path("C:/root/course/content/01 Week")
check("first claim", n.claim(d, "slides.pdf").name, "slides.pdf")
check("duplicate", n.claim(d, "slides.pdf").name, "slides (2).pdf")
check("case-insensitive duplicate", n.claim(d, "SLIDES.pdf").name, "SLIDES (3).pdf")
check("other dir independent", n.claim(d / "x", "slides.pdf").name, "slides.pdf")
deep = Path("C:/" + "/".join(["d" * 40] * 5))
p = n.claim(deep, "y" * 100 + ".pdf")
check("path fits MAX_PATH", (len(str(p)) <= MAX_PATH, p.suffix), (True, ".pdf"))
n2 = Namer()
check("deterministic", [n2.claim(d, "slides.pdf").name, n2.claim(d, "slides.pdf").name], ["slides.pdf", "slides (2).pdf"])

folded = _ics_fold("DESCRIPTION:" + "é" * 100)
check("ics folding <= 75 octets", all(len(l.encode()) <= 75 for l in folded), True)
check("ics folding lossless", folded[0] + "".join(l[1:] for l in folded[1:]), "DESCRIPTION:" + "é" * 100)

tmp = Path(tempfile.mkdtemp())
write_calendar_ics([
    {"CalendarEventId": 1, "Title": "Lab 2, due; soon", "StartDateTime": "2025-01-26T07:59:59.000Z",
     "EndDateTime": "2025-01-26T07:59:59.000Z", "Description": "<p>Bring &amp; submit</p>", "IsAllDayEvent": False},
    {"CalendarEventId": 2, "Title": "Reading break", "IsAllDayEvent": True, "StartDay": "2025-02-17T00:00:00",
     "EndDay": "2025-02-21T00:00:00", "StartDateTime": None},
], tmp / "c.ics")
ics = (tmp / "c.ics").read_bytes().decode()
check("ics CRLF", "\r\n" in ics and "\n" not in ics.replace("\r\n", ""), True)
check("ics escaped summary", "SUMMARY:Lab 2\\, due\\; soon" in ics, True)
check("ics utc time", "DTSTART:20250126T075959Z" in ics, True)
check("ics all-day", "DTSTART;VALUE=DATE:20250217" in ics, True)
check("ics html stripped", "DESCRIPTION:Bring & submit" in ics, True)

write_grades_csv({
    "values": [
        {"GradeObjectIdentifier": "1", "GradeObjectName": "Labs", "GradeObjectTypeName": "Category", "PointsNumerator": 8.5,
         "PointsDenominator": 10.0, "WeightedNumerator": 17.0, "WeightedDenominator": 20.0, "DisplayedGrade": None,
         "Comments": {"Text": "", "Html": ""}, "LastModified": None},
        {"GradeObjectIdentifier": "2", "GradeObjectName": "Lab 1", "GradeObjectTypeName": "Numeric", "PointsNumerator": 4.0,
         "PointsDenominator": 5.0, "WeightedNumerator": None, "WeightedDenominator": None, "DisplayedGrade": "80 %",
         "Comments": {"Text": "Nice, work", "Html": "<p>Nice, work</p>"}, "LastModified": "2025-01-01T00:00:00Z"},
    ],
    "items": [{"Id": 2, "CategoryId": 9}], "categories": [{"Id": 9, "Name": "Labs"}], "final": None,
}, tmp / "g.csv")
rows = (tmp / "g.csv").read_text(encoding="utf-8-sig").splitlines()
check("grades csv category row", rows[1].split(",")[:3], ["Labs", "", "Category"])
check("grades csv item joined to category", rows[2].startswith("Labs,Lab 1,Numeric,4,5,,,80 %,\"Nice, work\""), True)

