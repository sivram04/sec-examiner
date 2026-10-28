"""New-filing watcher: polls EDGAR's 'current filings' Atom feed and queues covered filings."""
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..edgar.client import EdgarClient, Filing
from .bus import RAW_DOCS, Bus

CURRENT_URL = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type={form}"
               "&company=&dateb=&owner=include&start=0&count=100&output=atom")
ATOM = "{http://www.w3.org/2005/Atom}"
ACC_RE = re.compile(r"accession-number=(\d{10}-\d{2}-\d{6})")
CIK_RE = re.compile(r"\((\d{10})\)")


def parse_feed(xml: str) -> list[tuple[int, str, str]]:
    """Return (cik, form, accession) for each feed entry."""
    out = []
    for e in ET.fromstring(xml).iter(f"{ATOM}entry"):
        title = e.findtext(f"{ATOM}title") or ""
        acc = ACC_RE.search(e.findtext(f"{ATOM}id") or "")
        cik = CIK_RE.search(title)
        form = (e.find(f"{ATOM}category").get("term") if e.find(f"{ATOM}category") is not None
                else title.split(" - ")[0])
        if acc and cik:
            out.append((int(cik.group(1)), form.strip(), acc.group(1)))
    return out


def filing_message(f: Filing, ticker: str) -> dict:
    return {"cik": f.cik, "ticker": ticker, "form": f.form, "accession": f.accession,
            "filing_date": f.filing_date.isoformat(),
            "report_date": f.report_date.isoformat() if f.report_date else None,
            "primary_doc": f.primary_doc}


class Watcher:
    def __init__(self, edgar: EdgarClient, bus: Bus, tickers: list[str], forms: set[str],
                 state_path: Path):
        self.edgar, self.bus, self.forms, self.state_path = edgar, bus, forms, state_path
        self.by_cik = {}
        for t in tickers:
            try:
                self.by_cik[edgar.cik(t)] = t
            except KeyError:
                pass  # ticker not in SEC's map (e.g. share-class suffix)
        self.seen: set[str] = (set(json.loads(state_path.read_text()))
                               if state_path.exists() else set())

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(sorted(self.seen)))

    def poll_once(self) -> list[str]:
        """Queue unseen covered filings from the live feed; returns their accessions."""
        new: list[str] = []
        for form in self.forms:
            xml = self.edgar.http.get(CURRENT_URL.format(form=form)).raise_for_status().text
            for cik, f_form, acc in parse_feed(xml):
                if cik not in self.by_cik or f_form not in self.forms or acc in self.seen:
                    continue
                # the feed lacks the primary document name; the submissions API has it
                match = [f for f in self.edgar.filings(self.by_cik[cik], {f_form})
                         if f.accession == acc]
                if match:
                    self.bus.publish(RAW_DOCS, acc, filing_message(match[0], self.by_cik[cik]))
                    new.append(acc)
                self.seen.add(acc)
        self.bus.flush()
        self._save()
        return new
