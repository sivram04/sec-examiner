"""Retrieval evaluation: recall@k, MRR and nDCG@k per method on a golden set.

Golden set (JSONL), one question per line:
  {"id": "q1", "question": "...", "ticker": "AAPL", "as_of": "2025-12-31",
   "relevant": ["<phrase that appears in the passage that answers it>", ...]}
A retrieved chunk counts as relevant when it contains any of the phrases (case-insensitive)
and belongs to the question's ticker. Phrases are used instead of chunk ids so the golden set
survives re-chunking. Because the full set of relevant chunks isn't enumerated, "recall@k" is
the hit rate: the share of questions with at least one relevant chunk in the top k.
"""
import json
import math
from datetime import date
from pathlib import Path

from .index import Filters, HybridIndex

METHODS = ("bm25", "dense", "hybrid", "hybrid_rerank")


def load_golden(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def is_relevant(chunk: dict, q: dict) -> bool:
    text = chunk["text"].lower()
    return chunk["ticker"] == q["ticker"] and any(p.lower() in text for p in q["relevant"])


def score_ranking(rels: list[bool], k: int) -> dict[str, float]:
    rels = rels[:k]
    first = next((i for i, r in enumerate(rels) if r), None)
    dcg = sum(1 / math.log2(i + 2) for i, r in enumerate(rels) if r)
    # binary relevance; ideal = all relevant hits ranked first
    idcg = sum(1 / math.log2(i + 2) for i in range(max(1, sum(rels))))
    return {"recall": float(first is not None), "mrr": 1 / (first + 1) if first is not None
            else 0.0, "ndcg": dcg / idcg}


def evaluate(index: HybridIndex, golden: list[dict], k: int = 10,
             methods: tuple[str, ...] = METHODS) -> dict[str, dict[str, float]]:
    results: dict[str, dict[str, float]] = {}
    for m in methods:
        tot = {"recall": 0.0, "mrr": 0.0, "ndcg": 0.0}
        for q in golden:
            f = Filters(as_of=date.fromisoformat(q["as_of"]) if q.get("as_of") else None,
                        tickers=(q["ticker"],))
            hits = index.search(q["question"], f, k=k, method=m)
            for key, v in score_ranking([is_relevant(h.chunk, q) for h in hits], k).items():
                tot[key] += v
        results[m] = {key: round(v / len(golden), 3) for key, v in tot.items()}
    return results


def to_markdown(results: dict[str, dict[str, float]], k: int, n: int) -> str:
    lines = [f"| Method | Recall@{k} (hit rate) | MRR | nDCG@{k} |", "|---|---|---|---|"]
    lines += [f"| {m} | {r['recall']:.3f} | {r['mrr']:.3f} | {r['ndcg']:.3f} |"
              for m, r in results.items()]
    return "\n".join(lines) + f"\n\n{n} questions."
