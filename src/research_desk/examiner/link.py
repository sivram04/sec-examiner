"""Tie each comment letter to the exact filing it reviewed, as that filing existed before the letter.

A letter's "Re:" block names a form plus a fiscal period and/or a filing date. The match must
be a filing of that form, by that company, filed strictly before the letter (the version the
staff read). Amendments filed in response to the letter are, by construction, excluded.
"""
from dataclasses import dataclass
from datetime import date, timedelta

from ..edgar.client import EdgarClient, Filing
from .letters import PERIODIC, Letter


@dataclass(frozen=True)
class Target:
    form: str
    accession: str
    filing_date: str
    period: str | None
    url: str


def _base(form: str) -> str:
    return form.replace("/A", "")


def match(letter: Letter, filings: list[Filing]) -> list[Target]:
    """Pure matching logic, separated from network access so it can be tested."""
    cutoff = letter.letter_date
    out: dict[str, Target] = {}
    for ref in letter.references:
        if ref["form"] not in PERIODIC:
            continue
        cands = [f for f in filings if _base(f.form) == _base(ref["form"])
                 and f.filing_date.isoformat() < cutoff]
        hit = None
        if ref.get("filed"):
            hit = next((f for f in cands if f.filing_date.isoformat() == ref["filed"]), None)
        if hit is None and ref.get("period"):
            # report dates can differ from the stated period end by a few days (52/53-week years)
            p = date.fromisoformat(ref["period"])
            near = [f for f in cands if f.report_date and abs((f.report_date - p).days) <= 7]
            # the original filing, not a later amendment, is what the staff first reviewed
            near.sort(key=lambda f: (f.form.endswith("/A"), f.filing_date))
            hit = near[0] if near else None
        if hit is not None:
            out[hit.accession] = Target(hit.form, hit.accession, hit.filing_date.isoformat(),
                                        hit.report_date.isoformat() if hit.report_date else None,
                                        hit.url)
    return list(out.values())


def link(edgar: EdgarClient, letter: Letter) -> list[Target]:
    since = date.fromisoformat(letter.letter_date) - timedelta(days=3 * 365)
    filings = edgar.filings_cik((letter.cik,), PERIODIC, since=since)
    return match(letter, filings)
