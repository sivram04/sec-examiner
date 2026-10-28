"""LLM entity extraction from 10-K text, grounded so the graph never holds invented facts.

The model proposes (type, name, quote) triples; a triple is kept only if its quote appears
verbatim in the source text and the name appears in that quote. Kept entities from
consecutive 10-Ks become temporal edges (see temporal.edges_from_snapshots), which is what
answers "which suppliers did X name in 2023 but not in 2025?".
"""
import json
import re
from collections.abc import Callable
from dataclasses import dataclass

RELATIONS = {
    "Segment": "HAS_SEGMENT",
    "Executive": "HAS_EXECUTIVE",
    "Product": "SELLS_PRODUCT",
    "Supplier": "NAMES_SUPPLIER",
    "Customer": "NAMES_CUSTOMER",
    "Competitor": "NAMES_COMPETITOR",
}

PROMPT = (
    "Extract entities a financial analyst tracks from this 10-K excerpt. Types: "
    + ", ".join(RELATIONS) + ". Only named, specific entities (companies, people, named "
    "segments or products), never generic phrases. For each, copy a short exact quote "
    "(5 to 30 words) from the text that mentions it. Reply with JSON only: "
    '{"entities": [{"type": "...", "name": "...", "quote": "..."}]}')


@dataclass(frozen=True)
class Entity:
    type: str
    name: str
    quote: str


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("’", "'").replace("“", '"')
                  .replace("”", '"')).strip().lower()


def ground(raw: list[dict], text: str) -> list[Entity]:
    """Keep only entities whose quote is verbatim in text and whose name is in the quote."""
    body = _norm(text)
    out: dict[tuple[str, str], Entity] = {}
    for e in raw:
        if not isinstance(e, dict):
            continue
        t, name, quote = (str(e.get(k, "")).strip() for k in ("type", "name", "quote"))
        if t not in RELATIONS or len(name) < 2 or len(quote) < 10:
            continue
        q = _norm(quote)
        if q not in body or _norm(name) not in q:
            continue
        out.setdefault((t, _norm(name)), Entity(t, name, quote))
    return list(out.values())


def extract(text: str, llm: Callable[[str, str], str], window: int = 12000) -> list[Entity]:
    """Run extraction over the text in windows (free-tier context limits), then ground."""
    from ..agents.desk import parse_json

    found: list[dict] = []
    for i in range(0, min(len(text), window * 3), window):
        try:
            found += parse_json(llm(PROMPT, text[i:i + window])).get("entities", [])
        except (ValueError, AttributeError, json.JSONDecodeError):
            continue
    return ground(found, text)
