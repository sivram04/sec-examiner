"""Temporal knowledge graph store: facts are edges with valid_from / valid_to dates.

An edge is "valid" from the filing that first states it until the first later filing of the
same kind that no longer does. Stored in SQLite locally; the same rows map 1:1 onto Neo4j
relationships with validity properties (see to_cypher).
"""
import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS edges (
  id TEXT PRIMARY KEY, subject TEXT, relation TEXT, object TEXT, object_type TEXT,
  valid_from TEXT, valid_to TEXT, source_accession TEXT, ended_by TEXT, evidence TEXT
);
CREATE INDEX IF NOT EXISTS edges_subj ON edges(subject, relation);
"""


@dataclass(frozen=True)
class Edge:
    subject: str
    relation: str
    object: str
    object_type: str
    valid_from: str
    valid_to: str | None
    source_accession: str
    ended_by: str | None
    evidence: str

    @property
    def id(self) -> str:
        return hashlib.sha1(f"{self.subject}|{self.relation}|{self.object}|{self.valid_from}"
                            .encode()).hexdigest()


class TemporalGraph:
    def __init__(self, path: Path | str = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)

    def upsert(self, edges: list[Edge]) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO edges VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(e.id, e.subject, e.relation, e.object, e.object_type, e.valid_from, e.valid_to,
              e.source_accession, e.ended_by, e.evidence) for e in edges])
        self.db.commit()

    def _rows(self, sql: str, args: tuple) -> list[Edge]:
        return [Edge(*r[1:]) for r in self.db.execute(sql, args).fetchall()]

    def as_of(self, subject: str, relation: str, day: str) -> list[Edge]:
        """Edges true on `day`: started on/before it and not ended by then."""
        return self._rows(
            "SELECT * FROM edges WHERE subject=? AND relation=? AND valid_from<=? "
            "AND (valid_to IS NULL OR valid_to>?) ORDER BY object", (subject, relation, day, day))

    def changed_between(self, subject: str, relation: str, start: str, end: str
                        ) -> tuple[list[Edge], list[Edge]]:
        """(appeared, disappeared) between two dates, e.g. 'what changed between Q2 and Q3'."""
        before = {e.object: e for e in self.as_of(subject, relation, start)}
        after = {e.object: e for e in self.as_of(subject, relation, end)}
        return ([after[o] for o in after.keys() - before.keys()],
                [before[o] for o in before.keys() - after.keys()])


def edges_from_snapshots(subject: str, relation: str, object_type: str,
                         snapshots: list[tuple[str, str, dict[str, str]]]) -> list[Edge]:
    """Turn ordered (filing_date, accession, {object: evidence}) snapshots into validity spans.

    An object present in consecutive snapshots is one edge; it ends at the first snapshot
    that omits it. Snapshots must be of comparable documents (e.g. consecutive 10-Ks).
    """
    snapshots = sorted(snapshots)
    open_: dict[str, tuple[str, str, str]] = {}  # object -> (valid_from, accession, evidence)
    out: list[Edge] = []
    for day, acc, objects in snapshots:
        for obj in list(open_):
            if obj not in objects:
                start, src, ev = open_.pop(obj)
                out.append(Edge(subject, relation, obj, object_type, start, day, src, acc, ev))
        for obj, ev in objects.items():
            open_.setdefault(obj, (day, acc, ev))
    out += [Edge(subject, relation, obj, object_type, start, None, src, None, ev)
            for obj, (start, src, ev) in open_.items()]
    return out


def to_cypher(e: Edge) -> tuple[str, dict]:
    """Neo4j MERGE for one edge, for loading the same graph into Neo4j/AuraDB."""
    q = (f"MERGE (s:Company {{ticker: $subject}}) MERGE (o:{e.object_type} {{name: $object}}) "
         f"MERGE (s)-[r:{e.relation} {{valid_from: $valid_from}}]->(o) "
         "SET r.valid_to = $valid_to, r.source = $source_accession, r.evidence = $evidence")
    return q, {"subject": e.subject, "object": e.object, "valid_from": e.valid_from,
               "valid_to": e.valid_to, "source_accession": e.source_accession,
               "evidence": e.evidence}
