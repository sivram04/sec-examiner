"""Ingestion stages: backfill -> raw-docs -> parse+chunk -> parsed -> index.

Chunks are also written to data/chunks/<accession>.jsonl, the corpus of record that indexes
can always be rebuilt from.
"""
import json
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx

from ..edgar.chunker import chunk_filing
from ..edgar.client import EdgarClient, Filing
from ..edgar.parser import parse_sections, whole_document
from .bus import PARSED, RAW_DOCS, Bus
from .watcher import filing_message

SECTIONED_FORMS = {"10-K", "10-Q"}


def backfill(edgar: EdgarClient, bus: Bus, tickers: list[str], forms: set[str],
             since: date, as_of: date | None = None) -> int:
    n = 0
    for t in tickers:
        try:
            filings = edgar.filings(t, forms, as_of, since=since)
        except KeyError:
            print(f"skip {t}: not in SEC ticker map")
            continue
        for f in filings:
            bus.publish(RAW_DOCS, f.accession, filing_message(f, t))
            n += 1
    bus.flush()
    return n


def _filing(msg: dict) -> Filing:
    return Filing(msg["cik"], msg["form"], msg["accession"],
                  date.fromisoformat(msg["filing_date"]),
                  date.fromisoformat(msg["report_date"]) if msg["report_date"] else None,
                  msg["primary_doc"])


def parse_stage(edgar: EdgarClient, bus: Bus, chunk_dir: Path, idle_timeout: float = 5.0,
                limit: int | None = None) -> int:
    chunk_dir.mkdir(parents=True, exist_ok=True)
    done = 0
    for msg in bus.consume(RAW_DOCS, "parser", idle_timeout):
        out = chunk_dir / f"{msg['accession']}.jsonl"
        if out.exists():
            done += 1
            continue
        f = _filing(msg)
        try:
            html = edgar.document(f)
        except httpx.HTTPError as e:  # one bad document must not stop the stream
            print(f"fetch failed {f.accession}: {e}")
            continue
        sections = parse_sections(html, f.form) if f.form in SECTIONED_FORMS else []
        if not sections:
            # 8-Ks, and filings whose Item headings can't be found: keep the whole body
            sections = [whole_document(html, f.form)]
        chunks = [c.to_dict() for c in chunk_filing(f, msg["ticker"], sections)]
        tmp = out.with_suffix(".tmp")
        tmp.write_text("\n".join(json.dumps(c) for c in chunks), encoding="utf-8")
        tmp.replace(out)
        for c in chunks:
            bus.publish(PARSED, c["id"], c)
        bus.flush()
        done += 1
        print(f"parsed {msg['ticker']:6} {f.form:5} {f.filing_date} {len(chunks):5} chunks")
        time.sleep(0.12)  # stay under SEC's 10 req/s
        if limit and done >= limit:
            break
    return done


def index_stage(bus: Bus, add: Callable[[list[dict]], None], batch: int = 256,
                idle_timeout: float = 5.0) -> int:
    buf: list[dict] = []
    n = 0
    for c in bus.consume(PARSED, "indexer", idle_timeout):
        buf.append(c)
        if len(buf) >= batch:
            add(buf)
            n += len(buf)
            buf = []
    if buf:
        add(buf)
        n += len(buf)
    return n


def corpus_documents(chunk_dir: Path) -> list[dict]:
    """One metadata row per filing, from each file's first chunk (cheap: no full read)."""
    out = []
    for p in sorted(chunk_dir.glob("*.jsonl")):
        with p.open(encoding="utf-8") as fh:
            first = fh.readline()
        if first.strip():
            c = json.loads(first)
            out.append({k: c[k] for k in ("ticker", "form", "accession", "filing_date")})
    return out


def load_corpus(chunk_dir: Path) -> list[dict]:
    chunks: list[dict] = []
    for p in sorted(chunk_dir.glob("*.jsonl")):
        chunks += [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line]
    return chunks
