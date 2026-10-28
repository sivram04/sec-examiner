"""XBRL company facts -> a flat table (ticker, concept, unit, period, value, filed, accession).

Stored in a local SQLite file for now so the pipeline runs with no services; the schema is
Postgres-compatible for the move to Postgres in deployment.
"""
import sqlite3
from pathlib import Path

COLUMNS = ("ticker", "taxonomy", "concept", "unit", "start", "end", "value",
           "fy", "fp", "form", "filed", "accession", "frame")

SCHEMA = """
CREATE TABLE IF NOT EXISTS xbrl_facts (
  ticker TEXT, taxonomy TEXT, concept TEXT, unit TEXT, start TEXT, "end" TEXT,
  value DOUBLE PRECISION, fy INTEGER, fp TEXT, form TEXT, filed TEXT, accession TEXT, frame TEXT,
  PRIMARY KEY (ticker, taxonomy, concept, unit, "end", accession, fp, start)
)
"""


def flatten(ticker: str, facts: dict) -> list[tuple]:
    rows = []
    for taxonomy, concepts in facts.get("facts", {}).items():
        for concept, body in concepts.items():
            for unit, points in body.get("units", {}).items():
                for p in points:
                    rows.append((ticker.upper(), taxonomy, concept, unit, p.get("start") or "",
                                 p["end"], p["val"], p.get("fy"), p.get("fp") or "",
                                 p.get("form"), p.get("filed"), p.get("accn"), p.get("frame")))
    return rows


class FactStore:
    def __init__(self, sqlite_path: Path):
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(sqlite_path, check_same_thread=False)
        self.db.execute(SCHEMA)

    def upsert(self, rows: list[tuple]) -> int:
        cols = ", ".join(f'"{c}"' for c in COLUMNS)
        self.db.executemany(
            f"INSERT OR REPLACE INTO xbrl_facts ({cols}) VALUES ({', '.join('?' * len(COLUMNS))})",
            rows)
        self.db.commit()
        return len(rows)

    def series(self, ticker: str, concept: str, as_of: str | None = None,
               form: str | None = None) -> list[dict]:
        """Point-in-time series: only facts filed on or before as_of."""
        q = ('SELECT * FROM xbrl_facts WHERE ticker=? AND concept=?'
             + (" AND filed<=?" if as_of else "") + (" AND form=?" if form else "")
             + ' ORDER BY "end", filed')
        args = [ticker.upper(), concept] + ([as_of] if as_of else []) + ([form] if form else [])
        cur = self.db.execute(q, args)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]
