"""Meaning-based filing features from a local embedding model (Ollama nomic-embed-text).

Word counts miss paraphrase: "write-down of the reporting unit" and "goodwill impairment" are the
same risk. Embedding a whole 10-K is too slow on a laptop, so each filing keeps the passages that
touch SEC topics (up to PER_TOPIC per topic, MAX_CHUNKS in all), embeds them once, and caches
the vectors. Features per filing:
- for each topic, the best similarity between any passage and that topic's description;
- the mean passage vector (overall meaning of the disclosure).
Runs locally and free; the filing text never leaves the machine.
"""
from pathlib import Path

import httpx
import numpy as np

from ..judge.topics import _COMPILED

MODEL = "nomic-embed-text"
URL = "http://localhost:11434/api/embed"
CHUNK = 800
MAX_CHUNKS = 24
PER_TOPIC = 2
DIM = 768

# what each topic looks like in a filing (worker-owned wording; the judge's gold labels come
# from letters, never from these)
DESCRIPTIONS = {
    "non_gaap": "non-GAAP financial measures such as adjusted EBITDA and their reconciliation",
    "revenue_recognition": "revenue recognition, performance obligations, principal versus agent",
    "segments": "reportable segments and the chief operating decision maker",
    "mdna_drivers": "results of operations and the drivers of changes in revenue and costs",
    "known_trends": "known trends, events and uncertainties likely to affect future results",
    "liquidity": "liquidity, capital resources, debt covenants and cash flows",
    "critical_estimates": "critical accounting estimates, assumptions and their sensitivity",
    "income_taxes": "income taxes, deferred tax assets and valuation allowances",
    "impairment": "goodwill and long-lived asset impairment testing of reporting units",
    "climate": "climate change risks, greenhouse gas emissions and regulation",
    "cybersecurity": "cybersecurity risk management, governance and incidents",
    "legal_contingencies": "litigation, legal proceedings and loss contingencies",
    "controls": "internal control over financial reporting and material weaknesses",
    "kpis": "key performance indicators and operating metrics",
    "geopolitical": "operations in China, Russia or Ukraine, sanctions and variable interest entities",
    "crypto": "crypto assets, digital asset holdings and blockchain activities",
    "presentation": "financial statement presentation and classification of line items",
    "audit_exhibits": "auditor report, exhibits and required filings",
    "governance_proxy": "board leadership, executive compensation and proxy disclosures",
    "business_disclosure": "description of the business, customers, licenses and material contracts",
    "financial_instruments": "derivatives, fair value measurements and investments in securities",
    "mining_reserves": "mineral resources, reserves and technical report summaries",
    "risk_factors": "risk factors describing material risks to the business",
}


def chunks(sections: dict[str, str]) -> list[str]:
    """Passages that mention SEC topics, a few per topic, then the start of MD&A as filler."""
    text = "\n".join(v for k, v in sections.items() if not k.startswith("__"))
    parts = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)]
    picked, used = [], set()
    for _, rx in _COMPILED:
        n = 0
        for i, p in enumerate(parts):
            if n >= PER_TOPIC or len(picked) >= MAX_CHUNKS:
                break
            if i not in used and rx.search(p.lower()):
                picked.append(p)
                used.add(i)
                n += 1
    for i, p in enumerate(parts):
        if len(picked) >= MAX_CHUNKS:
            break
        if i not in used:
            picked.append(p)
            used.add(i)
    return picked


def embed(texts: list[str], prefix: str, http: httpx.Client | None = None) -> np.ndarray:
    if not texts:
        return np.zeros((0, DIM), dtype=np.float32)
    client = http or httpx.Client(timeout=600)
    r = client.post(URL, json={"model": MODEL, "input": [prefix + t for t in texts]})
    r.raise_for_status()
    v = np.array(r.json()["embeddings"], dtype=np.float32)
    return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)


def topic_matrix(labels: list[str], http=None) -> np.ndarray:
    return embed([DESCRIPTIONS.get(t, t.replace("_", " ")) for t in labels], "search_query: ",
                 http)


def features(vectors: np.ndarray, topics: np.ndarray) -> np.ndarray:
    """[best similarity per topic] + [mean passage vector]; zeros when nothing was embedded."""
    if len(vectors) == 0:
        return np.zeros(topics.shape[0] + DIM, dtype=np.float32)
    sims = vectors @ topics.T
    return np.concatenate([sims.max(axis=0), vectors.mean(axis=0)]).astype(np.float32)


def cached(root: Path, case_id: str) -> np.ndarray | None:
    p = root / f"{case_id}.npy"
    return np.load(p).astype(np.float32) if p.exists() else None


def embed_all(cases, load_sections, root: Path, log=print) -> dict:
    """Embed every filing's topic passages once; resumable (skips cached files)."""
    root.mkdir(parents=True, exist_ok=True)
    stats = {"cached": 0, "embedded": 0, "empty": 0, "errors": 0}
    with httpx.Client(timeout=600) as http:
        for i, c in enumerate(cases):
            p = root / f"{c.case_id}.npy"
            if p.exists():
                stats["cached"] += 1
                continue
            secs = load_sections(c.case_id) or {}
            try:
                v = embed(chunks(secs), "search_document: ", http)
            except Exception as e:  # noqa: BLE001 - one bad filing must not stop the batch
                stats["errors"] += 1
                log(f"error {c.case_id}: {e!r}")
                continue
            np.save(p, v.astype(np.float16))
            stats["empty" if len(v) == 0 else "embedded"] += 1
            if (i + 1) % 50 == 0:
                log(f"{i + 1}/{len(cases)} {stats}")
    return stats
