"""Build the letter corpus: substantive letters reviewing periodic reports, linked to their filing.

Output is append-only JSONL ({"letter": ..., "targets": [...]}) so an interrupted build resumes
where it stopped.
"""
import json
import time
from datetime import date
from pathlib import Path

import httpx

from ..edgar.client import EdgarClient
from .letters import fetch, reviews_periodic, search
from .link import link


def build(edgar: EdgarClient, start: date, end: date, out: Path, limit: int | None = None,
          log=print) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        done = {json.loads(line)["letter"]["accession"]
                for line in out.read_text(encoding="utf-8").splitlines() if line.strip()}
    seen_path = out.with_suffix(".skipped")
    skipped = set(seen_path.read_text().split()) if seen_path.exists() else set()
    stats = {"hits": 0, "kept": 0, "linked": 0, "skipped": 0, "errors": 0}
    hits = search(edgar.http, start, end)
    stats["hits"] = len(hits)
    log(f"{len(hits)} letters found {start}..{end}")
    with out.open("a", encoding="utf-8") as fh, seen_path.open("a") as sk:
        for i, h in enumerate(hits):
            acc = h["_source"]["adsh"]
            if acc in done or acc in skipped:
                continue
            if limit and stats["kept"] >= limit:
                break
            try:
                L = fetch(edgar.http, h)
                time.sleep(0.12)
                if L.kind != "substantive" or not reviews_periodic(L):
                    stats["skipped"] += 1
                    sk.write(acc + "\n")
                    continue
                targets = link(edgar, L)
                time.sleep(0.12)
            except (httpx.HTTPError, KeyError, ValueError) as e:
                stats["errors"] += 1
                log(f"error {acc}: {e!r}"[:200])
                continue
            fh.write(json.dumps({"letter": L.to_dict(), "targets": [t.__dict__ for t in targets]})
                     + "\n")
            fh.flush()
            stats["kept"] += 1
            stats["linked"] += bool(targets)
            if stats["kept"] % 25 == 0:
                log(f"  {i + 1}/{len(hits)} scanned, {stats['kept']} kept, {stats['linked']} linked")
    return stats
