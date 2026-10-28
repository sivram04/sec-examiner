"""Section-aware parser for 10-K / 10-Q HTML: splits by Item headings and pulls out tables."""
import re
import warnings
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

ITEMS_10K = {
    "1": "Business", "1A": "Risk Factors", "1B": "Unresolved Staff Comments",
    "1C": "Cybersecurity", "2": "Properties", "3": "Legal Proceedings",
    "4": "Mine Safety Disclosures", "5": "Market for Common Equity",
    "6": "[Reserved]", "7": "MD&A", "7A": "Market Risk Disclosures",
    "8": "Financial Statements", "9": "Changes in and Disagreements with Accountants",
    "9A": "Controls and Procedures", "9B": "Other Information",
    "9C": "Foreign Jurisdictions that Prevent Inspections",
    "10": "Directors and Officers", "11": "Executive Compensation",
    "12": "Security Ownership", "13": "Relationships and Related Transactions",
    "14": "Accountant Fees", "15": "Exhibits", "16": "Form 10-K Summary",
}
# 10-Q items repeat numbers across Part I / Part II, so keys carry the part
ITEMS_10Q = {
    "I-1": "Financial Statements", "I-2": "MD&A", "I-3": "Market Risk Disclosures",
    "I-4": "Controls and Procedures", "II-1": "Legal Proceedings", "II-1A": "Risk Factors",
    "II-2": "Unregistered Sales of Equity", "II-3": "Defaults on Senior Securities",
    "II-4": "Mine Safety Disclosures", "II-5": "Other Information", "II-6": "Exhibits",
}

ITEM_RE = re.compile(r"^\s*item\s+(\d{1,2}[a-c]?)\s*[.:\-—–]?", re.IGNORECASE)
PART_RE = re.compile(r"^\s*part\s+(i{1,2})\b", re.IGNORECASE)
# bare "PART I" / "Item 1" / "Item 3, 4" lines: page headers, not prose
RUNNING_RE = re.compile(r"^\s*(part\s+i{1,2}|items?\s+\d{1,2}[a-c]?(\s*,\s*\d{1,2}[a-c]?)*)\.?\s*$",
                        re.IGNORECASE)
BLOCK_TAGS = ["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"]


@dataclass
class Section:
    item: str       # "1A", or "II-1A" for 10-Q
    title: str
    text: str
    tables: list[str] = field(default_factory=list)


def _table_text(table) -> str:
    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c and c not in {"$", "%", ")"}]
        if cells:
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _blocks(html: str) -> list[tuple[str, str]]:
    """Flatten the document into ('text'|'table', content) blocks in reading order."""
    with warnings.catch_warnings():
        # inline XBRL filings are XHTML; the HTML parser handles them fine
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "head"]):
        t.decompose()
    # inline XBRL hidden header holds raw facts, not prose
    for t in soup.find_all(["ix:header"]):
        t.decompose()
    out: list[tuple[str, str]] = []
    body = soup.body or soup
    for el in body.find_all(["table", *BLOCK_TAGS]):
        if el.find_parent("table") is not None:
            continue
        if el.name == "table":
            txt = _table_text(el)
            if txt:
                out.append(("table", txt))
            continue
        # only leaf-ish blocks, so nested divs don't duplicate text
        if el.find(["table", *BLOCK_TAGS]):
            continue
        txt = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
        if txt:
            out.append(("text", txt))
    return out


def _is_heading(txt: str) -> bool:
    return len(txt) < 200


def parse_sections(html: str, form: str = "10-K") -> list[Section]:
    """Split a filing into Item sections.

    Item headings appear twice (table of contents, then the body). For each item we keep
    the occurrence followed by the most text, which is the body in practice.
    """
    is_q = form.upper().startswith("10-Q")
    names = ITEMS_10Q if is_q else ITEMS_10K
    blocks = _blocks(html)

    starts: list[tuple[int, str]] = []
    running: set[int] = set()
    part = "I"
    for i, (kind, txt) in enumerate(blocks):
        if kind != "text" or not _is_heading(txt):
            continue
        if RUNNING_RE.match(txt):
            running.add(i)
        if pm := PART_RE.match(txt):
            part = pm.group(1).upper()
        m = ITEM_RE.match(txt)
        if not m:
            continue
        key = m.group(1).upper()
        if is_q:
            key = f"{part}-{key}"
        # page running headers repeat the open item on every page; they don't start a section
        if key in names and (not starts or starts[-1][1] != key):
            starts.append((i, key))

    best: dict[str, Section] = {}
    for n, (i, key) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(blocks)
        body = [b for j, b in enumerate(blocks[i + 1:end], i + 1) if j not in running]
        text = "\n\n".join(t for k, t in body if k == "text")
        sec = Section(key, names[key], text, [t for k, t in body if k == "table"])
        if key not in best or len(sec.text) > len(best[key].text):
            best[key] = sec

    order = list(names)
    return sorted(best.values(), key=lambda s: order.index(s.item))
