"""Long-term memory: prior notes and watched theses per user and company (SQLite locally)."""
import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, user TEXT, ticker TEXT,
  created REAL, question TEXT, as_of TEXT, report TEXT, claims TEXT);
CREATE TABLE IF NOT EXISTS theses (user TEXT, ticker TEXT, thesis TEXT, created REAL,
  PRIMARY KEY (user, ticker, thesis));
"""


class Memory:
    def __init__(self, path: Path | str = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)

    def save_note(self, user: str, ticker: str, question: str, as_of: str, report: str,
                  claims: list[dict]) -> int:
        cur = self.db.execute(
            "INSERT INTO notes (user, ticker, created, question, as_of, report, claims) "
            "VALUES (?,?,?,?,?,?,?)",
            (user, ticker, time.time(), question, as_of, report, json.dumps(claims)))
        self.db.commit()
        return cur.lastrowid

    def notes(self, user: str, ticker: str, limit: int = 3) -> list[dict]:
        rows = self.db.execute(
            "SELECT question, as_of, report FROM notes WHERE user=? AND ticker=? "
            "ORDER BY created DESC LIMIT ?", (user, ticker, limit)).fetchall()
        return [{"question": q, "as_of": a, "report": r} for q, a, r in rows]

    def watch(self, user: str, ticker: str, thesis: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO theses VALUES (?,?,?,?)",
                        (user, ticker, thesis, time.time()))
        self.db.commit()

    def theses(self, user: str, ticker: str) -> list[str]:
        return [r[0] for r in self.db.execute(
            "SELECT thesis FROM theses WHERE user=? AND ticker=? ORDER BY created",
            (user, ticker)).fetchall()]
