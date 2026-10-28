"""Paragraph-aware chunking with the metadata every retrieval filter needs."""
import hashlib
from dataclasses import asdict, dataclass
from datetime import date

from .client import Filing
from .parser import Section


@dataclass(frozen=True)
class Chunk:
    id: str
    ticker: str
    cik: int
    form: str
    accession: str
    filing_date: date
    period: date | None
    section: str
    section_title: str
    kind: str        # "text" or "table"
    ordinal: int     # position within the section
    text: str
    source_url: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["filing_date"] = self.filing_date.isoformat()
        d["period"] = self.period.isoformat() if self.period else None
        return d


def split_text(text: str, max_chars: int = 2000, overlap: int = 200) -> list[str]:
    """Pack paragraphs into chunks up to max_chars; split oversized paragraphs on sentences."""
    paras: list[str] = []
    for p in text.split("\n\n"):
        p = p.strip()
        if not p:
            continue
        while len(p) > max_chars:
            cut = p.rfind(". ", 0, max_chars)
            cut = cut + 1 if cut > max_chars // 2 else max_chars
            paras.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            paras.append(p)

    chunks: list[str] = []
    cur = ""
    for p in paras:
        if cur and len(cur) + len(p) + 2 > max_chars:
            chunks.append(cur)
            tail = cur[-overlap:] if overlap else ""
            # start overlap at a word boundary
            tail = tail[tail.find(" ") + 1:] if " " in tail else tail
            cur = f"{tail}\n\n{p}" if tail else p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        chunks.append(cur)
    return chunks


def chunk_filing(filing: Filing, ticker: str, sections: list[Section],
                 max_chars: int = 2000, overlap: int = 200) -> list[Chunk]:
    out: list[Chunk] = []
    for sec in sections:
        pieces = [("text", t) for t in split_text(sec.text, max_chars, overlap)]
        pieces += [("table", t) for t in sec.tables]
        for n, (kind, txt) in enumerate(pieces):
            # text is part of the id, so a parser change re-embeds instead of reusing stale vectors
            cid = hashlib.sha1(
                f"{filing.accession}|{sec.item}|{kind}|{n}|{txt}".encode()).hexdigest()
            out.append(Chunk(cid, ticker.upper(), filing.cik, filing.form, filing.accession,
                             filing.filing_date, filing.report_date, sec.item, sec.title,
                             kind, n, txt, filing.url))
    return out
