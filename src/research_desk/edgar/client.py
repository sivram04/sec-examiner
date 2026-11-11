"""SEC EDGAR client: ticker -> CIK, filing listings with point-in-time (as_of) filtering."""
from dataclasses import dataclass
from datetime import date

import httpx

from ..config import settings

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
# tickers whose SEC map now points at a new entity (e.g. a holding-company reorganization):
# history lives under the predecessor CIK, so filings from both are merged
PREDECESSORS = {"XOM": (34088,)}  # ExxonMobil Holdings Corp <- Exxon Mobil Corp
PAGE_URL ="https://data.sec.gov/submissions/{name}"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"


@dataclass(frozen=True)
class Filing:
    cik: int
    form: str
    accession: str
    filing_date: date
    report_date: date | None
    primary_doc: str

    @property
    def url(self) -> str:
        return ARCHIVE_URL.format(cik=self.cik, acc=self.accession.replace("-", ""),
                                  doc=self.primary_doc)


def parse_filings(cik: int, submissions: dict, forms: set[str] | None = None,
                  as_of: date | None = None) -> list[Filing]:
    """Turn the 'recent' block of a submissions payload into Filings.

    as_of enforces point-in-time correctness: nothing filed after it is returned.
    """
    return _parse_block(cik, submissions["filings"]["recent"], forms, as_of)


def _parse_block(cik: int, r: dict, forms: set[str] | None, as_of: date | None) -> list[Filing]:
    """Parse one columnar block (the 'recent' block or an older submissions page)."""
    out = []
    for i, form in enumerate(r["form"]):
        if forms and form not in forms:
            continue
        filed = date.fromisoformat(r["filingDate"][i])
        if as_of and filed > as_of:
            continue
        rep = r["reportDate"][i]
        out.append(Filing(cik, form, r["accessionNumber"][i], filed,
                          date.fromisoformat(rep) if rep else None, r["primaryDocument"][i]))
    return out


class EdgarClient:
    def __init__(self, client: httpx.Client | None = None):
        # SEC asks for <=10 req/s and a descriptive User-Agent
        self.http = client or httpx.Client(
            headers={"User-Agent": settings.sec_user_agent}, timeout=30, follow_redirects=True)
        self._tickers: dict[str, int] | None = None

    def cik(self, ticker: str) -> int:
        if self._tickers is None:
            data = self.http.get(TICKERS_URL).raise_for_status().json()
            self._tickers = {v["ticker"].upper(): int(v["cik_str"]) for v in data.values()}
        return self._tickers[ticker.upper()]

    def filings(self, ticker: str, forms: set[str] | None = None,
                as_of: date | None = None, since: date | None = None) -> list[Filing]:
        """Filings newest first. With since, older submission pages are fetched as needed:
        'recent' holds only the last ~1000 filings, which busy filers exhaust within months.
        """
        return self.filings_cik((self.cik(ticker), *PREDECESSORS.get(ticker.upper(), ())),
                                forms, as_of, since)

    def filings_cik(self, ciks, forms: set[str] | None = None, as_of: date | None = None,
                    since: date | None = None) -> list[Filing]:
        """Same as filings(), by company ID: SEC-reviewed filers often have no ticker."""
        out: list[Filing] = []
        for cik in ciks:
            subs = self.http.get(SUBMISSIONS_URL.format(cik=cik)).raise_for_status().json()
            out += parse_filings(cik, subs, forms, as_of)
            if since:
                for page in subs["filings"].get("files", []):
                    if date.fromisoformat(page["filingTo"]) < since:
                        continue
                    block = self.http.get(
                        PAGE_URL.format(name=page["name"])).raise_for_status().json()
                    out += _parse_block(cik, block, forms, as_of)
        if since:
            out = [f for f in out if f.filing_date >= since]
        # a joint filing appears under both entities: keep one copy per accession
        out = list({f.accession: f for f in reversed(out)}.values())
        return sorted(out, key=lambda f: f.filing_date, reverse=True)

    def company_facts(self, ticker: str) -> dict:
        return self.http.get(FACTS_URL.format(cik=self.cik(ticker))).raise_for_status().json()

    def document(self, filing: Filing) -> str:
        return decode(self.http.get(filing.url).raise_for_status().content)


def decode(raw: bytes) -> str:
    """SEC serves filings without a charset; most are UTF-8, older ones Windows-1252.

    Guessing wrong turns curly quotes into U+FFFD, which then breaks phrase matching.
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")
