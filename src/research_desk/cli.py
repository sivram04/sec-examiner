import argparse
import json
from datetime import date

from .edgar.chunker import chunk_filing
from .edgar.client import EdgarClient
from .edgar.parser import parse_sections


def main() -> None:
    p = argparse.ArgumentParser(prog="desk")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("filings", help="list SEC filings for a ticker")
    f.add_argument("ticker")
    f.add_argument("--forms", default="10-K,10-Q,8-K")
    f.add_argument("--as-of", type=date.fromisoformat)
    f.add_argument("-n", type=int, default=10)
    s = sub.add_parser("sections", help="parse the latest 10-K/10-Q into sections and chunks")
    s.add_argument("ticker")
    s.add_argument("--form", default="10-K")
    s.add_argument("--as-of", type=date.fromisoformat)
    s.add_argument("--out", help="write chunks as JSONL to this path")
    a = p.parse_args()

    if a.cmd == "filings":
        for fl in EdgarClient().filings(a.ticker, set(a.forms.split(",")), a.as_of)[: a.n]:
            print(f"{fl.filing_date}  {fl.form:6} {fl.accession}  {fl.url}")
    elif a.cmd == "sections":
        ec = EdgarClient()
        fl = ec.filings(a.ticker, {a.form}, a.as_of)[0]
        secs = parse_sections(ec.document(fl), fl.form)
        chunks = chunk_filing(fl, a.ticker, secs)
        print(f"{fl.form} filed {fl.filing_date}  {fl.url}")
        for sec in secs:
            n = sum(c.section == sec.item for c in chunks)
            print(f"  Item {sec.item:6} {sec.title:42} {len(sec.text):>8,} chars "
                  f"{len(sec.tables):>3} tables {n:>4} chunks")
        print(f"total chunks: {len(chunks)}")
        if a.out:
            with open(a.out, "w", encoding="utf-8") as fh:
                fh.writelines(json.dumps(c.to_dict()) + "\n" for c in chunks)


if __name__ == "__main__":
    main()
