"""Earnings releases (8-K Item 2.02, Exhibit 99.1) and a deterministic tone score.

Earnings-call transcripts are not freely licensed; the press release a company files with
the SEC is, and carries management's framing of the quarter. Tone is measured with a fixed
lexicon in code, so the transcript analyst reports counts it can cite, not an LLM's mood.
"""
import re
from dataclasses import dataclass

INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json"
DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{name}"

# small, hand-picked lexicons in the spirit of finance tone dictionaries
UNCERTAIN = {"uncertain", "uncertainty", "uncertainties", "may", "might", "could", "possible",
             "possibly", "risk", "risks", "volatile", "volatility", "unpredictable", "depend",
             "depends", "approximately", "believe", "believes", "anticipate", "anticipates"}
NEGATIVE = {"decline", "declined", "decrease", "decreased", "loss", "losses", "weak",
            "weakness", "headwind", "headwinds", "impairment", "charge", "charges", "adverse",
            "lower", "challenging", "pressure", "pressures", "restructuring", "down"}
POSITIVE = {"record", "growth", "grew", "increase", "increased", "strong", "strength",
            "momentum", "exceeded", "improved", "improvement", "expanded", "accelerated",
            "higher", "robust", "tailwind", "tailwinds", "up"}
GUIDANCE_RE = re.compile(r"\b(outlook|guidance|expects?|expected|forecast|anticipates?)\b",
                         re.IGNORECASE)
WORD_RE = re.compile(r"[a-z]+")


@dataclass(frozen=True)
class Tone:
    words: int
    uncertain_per_1k: float
    negative_per_1k: float
    positive_per_1k: float
    net_tone: float          # (positive - negative) / (positive + negative), -1..1
    guidance_sentences: int

    def as_text(self) -> str:
        return (f"{self.words} words; uncertainty {self.uncertain_per_1k} per 1k words; "
                f"negative {self.negative_per_1k} per 1k; positive {self.positive_per_1k} per "
                f"1k; net tone {self.net_tone}; {self.guidance_sentences} guidance sentences")


def tone(text: str) -> Tone:
    words = WORD_RE.findall(text.lower())
    n = max(1, len(words))
    unc = sum(w in UNCERTAIN for w in words)
    neg = sum(w in NEGATIVE for w in words)
    pos = sum(w in POSITIVE for w in words)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return Tone(len(words), round(unc / n * 1000, 1), round(neg / n * 1000, 1),
                round(pos / n * 1000, 1), round((pos - neg) / max(1, pos + neg), 3),
                sum(bool(GUIDANCE_RE.search(s)) for s in sentences))


def earnings_filings(edgar, ticker: str, as_of: str, n: int = 2) -> list[tuple[str, int, str]]:
    """(filing_date, cik, accession) of the latest n earnings 8-Ks (Item 2.02) filed <= as_of."""
    from ..edgar.client import PREDECESSORS, SUBMISSIONS_URL

    out = []
    for cik in (edgar.cik(ticker), *PREDECESSORS.get(ticker.upper(), ())):
        r = edgar.http.get(SUBMISSIONS_URL.format(cik=cik)).raise_for_status().json()
        r = r["filings"]["recent"]
        for form, filed, acc, items in zip(r["form"], r["filingDate"], r["accessionNumber"],
                                          r.get("items", [""] * len(r["form"])), strict=False):
            if form == "8-K" and "2.02" in (items or "") and filed <= as_of:
                out.append((filed, cik, acc))
    out = list({acc: (d, c, acc) for d, c, acc in sorted(out)}.values())
    return sorted(out, reverse=True)[:n]


def releases(edgar, ticker: str, as_of: str, cache, n: int = 2) -> list[dict]:
    """Latest n earnings releases on or before as_of, with tone; cached as text files."""
    cache.mkdir(parents=True, exist_ok=True)
    out = []
    for filed, cik, acc in earnings_filings(edgar, ticker, as_of, n):
        path = cache / f"{acc}.txt"
        if not path.exists():
            text = exhibit_99(edgar, cik, acc) or ""
            path.write_text(text, encoding="utf-8")
        text = path.read_text(encoding="utf-8")
        if text:
            out.append({"filed": filed, "accession": acc, "text": text, "tone": tone(text)})
    return out


def exhibit_99(edgar, cik: int, accession: str) -> str | None:
    """Text of the filing's Exhibit 99.1 (the press release), if it has one."""
    from ..edgar.parser import whole_document

    acc = accession.replace("-", "")
    idx = edgar.http.get(INDEX_URL.format(cik=cik, acc=acc)).raise_for_status().json()
    items = idx.get("directory", {}).get("item", [])
    docs = [i for i in items if i["name"].lower().endswith((".htm", ".html"))
            and "index" not in i["name"].lower()]
    ex = next((i["name"] for i in docs
               if re.search(r"(ex|exhibit)[-_]?99", i["name"], re.IGNORECASE)), None)
    if not ex and len(docs) > 1:
        # some filers name it e.g. "q2fy27pr.htm": the release is the largest document,
        # far bigger than the one-page 8-K cover
        ex = max(docs, key=lambda i: int(i.get("size") or 0))["name"]
    if not ex:
        return None
    raw = edgar.http.get(DOC_URL.format(cik=cik, acc=acc, name=ex)).raise_for_status().content
    from ..edgar.client import decode

    return whole_document(decode(raw), "EX-99.1").text
