"""Fetch each reviewed filing once and cache the sections the SEC staff reads most.

Full 10-K HTML runs to several MB; only section text is kept (gzip, capped per section), so the
whole training set fits in a few hundred MB and features can be recomputed without re-fetching.
"""
import gzip
import json
import time
from pathlib import Path

import httpx

from ..edgar.client import EdgarClient, decode
from ..edgar.parser import parse_sections, whole_document

# 10-K items (and their 20-F counterparts land in "other"/"body"): business, risks, MD&A, notes
# note: many filers put the financial statements and notes under Item 15 (the "F-pages")
KEEP = {"1", "1A", "1B", "1C", "3", "5", "7", "7A", "8", "9A", "15", "I-1", "I-2", "II-1A",
        "other", "body"}
CAP = 150_000        # characters per section
CAP_BODY = 400_000   # unsectioned filings (20-F): the operating review comes well into the body


def cache_path(root: Path, accession: str) -> Path:
    return root / f"{accession}.json.gz"


def load(root: Path, accession: str) -> dict[str, str] | None:
    p = cache_path(root, accession)
    if not p.exists():
        return None
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def extract(html: str, form: str) -> dict[str, str]:
    base = form.replace("/A", "")
    secs = parse_sections(html, base) if base in ("10-K", "10-Q") else []
    if not secs:                     # 20-F and unsectioned filings: keep the body
        secs = [whole_document(html, form)]
    out = {}
    for s in secs:
        if s.item in KEEP:
            body = s.text + ("\n\n" + "\n".join(s.tables) if s.tables else "")
            out[s.item] = body[:CAP_BODY if s.item in ("body", "other") else CAP]
    return out


def fetch_all(edgar: EdgarClient, cases, root: Path, log=print) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    stats = {"cached": 0, "fetched": 0, "errors": 0}
    for i, c in enumerate(cases):
        p = cache_path(root, c.case_id)
        if p.exists():
            stats["cached"] += 1
            continue
        try:
            html = decode(edgar.http.get(c.filing_url).raise_for_status().content)
            secs = extract(html, c.form)
        except (httpx.HTTPError, ValueError) as e:
            stats["errors"] += 1
            log(f"error {c.case_id}: {e!r}"[:160])
            continue
        tmp = p.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(secs, fh)
        tmp.replace(p)
        stats["fetched"] += 1
        if stats["fetched"] % 50 == 0:
            log(f"  {i + 1}/{len(cases)} done ({stats['fetched']} fetched, {stats['errors']} errors)")
        time.sleep(0.12)
    return stats
