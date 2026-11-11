"""SEC staff comment letters (EDGAR form UPLOAD): find, fetch, classify, split into comments.

EDGAR full-text search indexes a text extract of every letter, so no PDF parsing is needed.
Search pages are capped (~10k results per query), so queries run one month at a time.
"""
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{name}"
# phrases that open a letter which actually raises comments
SUBSTANTIVE_Q = '"following comment" OR "following comments"'


@dataclass
class Comment:
    number: int
    section: str          # heading the comment sits under, e.g. "Risk Factors, page 6"
    text: str
    follow_up: bool       # "We note your response to comment 2..." (continues an earlier round)


@dataclass
class Letter:
    accession: str
    cik: int
    company: str
    sic: str
    letter_date: str
    kind: str                                    # substantive | closing | no_review
    references: list[dict] = field(default_factory=list)   # [{"form","period","filed"}]
    comments: list[Comment] = field(default_factory=list)
    text: str = ""

    def to_dict(self, with_text: bool = False) -> dict:
        d = asdict(self)
        if not with_text:
            d.pop("text")
        return d

    @staticmethod
    def from_dict(d: dict) -> "Letter":
        return Letter(**{**d, "comments": [Comment(**c) for c in d.get("comments", [])]})


def classify(text: str) -> str:
    t = re.sub(r"\s+", " ", text).lower()
    if "will not review" in t or "not reviewed and will not" in t:
        return "no_review"
    if re.search(r"following comments?\b", t):
        return "substantive"
    if "completed our review" in t:
        return "closing"
    return "other"


MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
DATE = rf"{MONTH}\s+\d{{1,2}},\s*\d{{4}}"
FORM = r"(10-K(?:/A)?|10-Q(?:/A)?|20-F|40-F|8-K|S-1|S-3|S-4|F-1|F-4|DEF\s?14A|PRE\s?14A|DEFA14A|Schedule\s+14A)"
REF_RE = re.compile(rf"Form\s+{FORM}(?P<rest>.{{0,140}}?)(?=Form\s+\d|File\s+No|Dear|Response\s+dated|$)",
                    re.IGNORECASE | re.DOTALL)
PERIOD_RE = re.compile(rf"(?:Year|Period|Quarter)\w*\s+(?:Ended|Ending)\s+({DATE})", re.IGNORECASE)
FILED_RE = re.compile(rf"Filed\s+(?:on\s+)?({DATE})", re.IGNORECASE)


def _iso(s: str) -> str | None:
    from datetime import datetime

    try:
        clean = re.sub(r"\s*,\s*", ", ", re.sub(r"\s+", " ", s.strip()))
        return datetime.strptime(clean, "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


def parse_references(text: str) -> list[dict]:
    """Filings named in the letter's "Re:" block, e.g. Form 10-K for FY ended Dec 31, 2023."""
    flat = re.sub(r"\s+", " ", text)
    m = re.search(r"\bRe:\s*(.{0,700}?)(?:Dear\b|Ladies and Gentlemen)", flat, re.IGNORECASE)
    block = m.group(1) if m else flat[:700]
    out = []
    for r in REF_RE.finditer(block):
        form = re.sub(r"\s+", "", r.group(1).upper()).replace("SCHEDULE14A", "DEF14A")
        rest = r.group("rest")
        p, f = PERIOD_RE.search(rest), FILED_RE.search(rest)
        out.append({"form": form, "period": _iso(p.group(1)) if p else None,
                    "filed": _iso(f.group(1)) if f else None})
    return out


# a comment heading line: "Item 7. Management's Discussion..., page 27" / "Risk Factors, page 6"
# headings are indented in the SEC's text extracts: "       Use of Non-IFRS Measures, page 43"
HEADING_RE = re.compile(r"^[ \t]*(?!\d+\.)([A-Z][^\n]{2,140}?,?\s+pages?\s+[\dA-Z-]+"
                        r"(?:\s*(?:and|-|,)\s*[\dA-Z-]+)*)[ \t]*$", re.MULTILINE)
# continuation-page header: "<name>\n<company>\n<Month d, yyyy>\nPage 2"
PAGE_BREAK_RE = re.compile(rf"(?:^[^\n]*\n){{0,3}}^[ \t]*{DATE}[ \t]*\n[ \t]*Page \d+[ \t]*$",
                           re.MULTILINE)
NUM_RE = re.compile(r"^\s*(\d{1,2})\.\s+(?=[A-Z\"“(])", re.MULTILINE)
FOLLOW_RE = re.compile(r"\b(?:we note your response|your response to (?:prior |our prior )?comment|"
                       r"as previously requested|we re-?issue)", re.IGNORECASE)


def split_comments(text: str) -> list[Comment]:
    """Numbered comments with the section heading each one sits under."""
    text = PAGE_BREAK_RE.sub("\n", text)
    marks =[(m.start(), "num", int(m.group(1))) for m in NUM_RE.finditer(text)]
    marks += [(m.start(), "head", m.group(1).strip()) for m in HEADING_RE.finditer(text)]
    marks.sort()
    out, section, expected = [], "", 1
    for i, (pos, kind, val) in enumerate(marks):
        if kind == "head":
            section = re.sub(r"\s+", " ", val)
            continue
        if val != expected:          # page numbers, list items inside a comment, etc.
            continue
        end = next((p for p, k, v in marks[i + 1:] if k == "num" and v == expected + 1), None)
        body = text[pos:end] if end else text[pos:]
        body = re.split(r"\n\s*(?:We remind you|Please contact|Sincerely)", body)[0]
        # drop a heading that belongs to the next comment
        body = HEADING_RE.sub("", body)
        body = re.sub(r"\s+", " ", re.sub(r"^\s*\d{1,2}\.\s+", "", body)).strip()
        out.append(Comment(val, section, body, bool(FOLLOW_RE.search(body))))
        expected += 1
    return out


def months(start: date, end: date):
    d = start.replace(day=1)
    while d <= end:
        nxt = (d + timedelta(days=32)).replace(day=1)
        yield max(d, start), min(nxt - timedelta(days=1), end)
        d = nxt


def search(http, start: date, end: date) -> list[dict]:
    """All substantive-letter hits in [start, end], paged month by month."""
    hits: list[dict] = []
    for a, b in months(start, end):
        offset = 0
        while True:
            params = {"q": SUBSTANTIVE_Q, "forms": "UPLOAD", "dateRange": "custom",
                      "startdt": a.isoformat(), "enddt": b.isoformat(), "from": str(offset)}
            for attempt in range(6):          # full-text search returns transient 5xx
                r = http.get(SEARCH_URL, params=params)
                if r.status_code < 500 and r.status_code != 429:
                    break
                time.sleep(min(60, 5 * 2 ** attempt))
            r.raise_for_status()
            page = r.json().get("hits", {}).get("hits", [])
            hits += page
            if len(page) < 100 or offset >= 9900:
                break
            offset += 100
    # one hit per letter (a letter can match through several files)
    return list({h["_source"]["adsh"]: h for h in hits}.values())


PERIODIC = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F"}


def reviews_periodic(letter: "Letter") -> bool:
    """Product scope: reviews of annual and quarterly reports, not IPO drafts or tender offers."""
    return any(r["form"] in PERIODIC for r in letter.references)


def _letter_text(http, cik: int, acc: str) -> str:
    """The SEC's text extract of the letter (filename2.txt); fall back to reading the PDF."""
    base = DOC_URL.format(cik=cik, acc=acc.replace("-", ""), name="{}")
    r = http.get(base.format("filename2.txt"))
    if r.status_code == 200 and "TEXT-EXTRACT" in r.text[:200]:
        return r.text
    import io

    from pypdf import PdfReader

    pdf = http.get(base.format("filename1.pdf")).raise_for_status().content
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages)


def fetch(http, hit: dict) -> Letter:
    src = hit["_source"]
    cik = int(src["ciks"][0])
    acc = hit["_id"].split(":", 1)[0]
    text = _letter_text(http, cik, acc)
    company = re.sub(r"\s*\(CIK.*$", "", src["display_names"][0]).strip()
    return Letter(acc, cik, company, (src.get("sics") or [""])[0], src["file_date"],
                  classify(text), parse_references(text), split_comments(text), text)
