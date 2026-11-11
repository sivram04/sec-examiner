"""Issue-level scoring of a ranked topic prediction against the topics the SEC actually raised."""
from collections import defaultdict
from statistics import mean


def score_case(pred: list[str], gold: tuple[str, ...], k: int) -> dict[str, float]:
    top = list(dict.fromkeys(pred))[:k]
    g = set(gold)
    tp = len(set(top) & g)
    return {
        "precision": tp / len(top) if top else 0.0,
        "recall": tp / len(g) if g else 0.0,
        "hit": float(tp > 0),          # at least one real issue among the flags
    }


def aggregate(rows: list[dict], k: int) -> dict:
    """rows: {case, pred} -> overall, per-year and per-topic metrics."""
    scored = [{**r, **score_case(r["pred"], r["case"].gold_topics, k)} for r in rows]

    def summary(rs):
        if not rs:
            return {}
        p = mean(r["precision"] for r in rs)
        rc = mean(r["recall"] for r in rs)
        return {"n": len(rs), "precision": round(p, 3), "recall": round(rc, 3),
                "f1": round(2 * p * rc / (p + rc), 3) if p + rc else 0.0,
                "hit_rate": round(mean(r["hit"] for r in rs), 3)}

    by_year = defaultdict(list)
    for r in scored:
        by_year[r["case"].filing_date[:4]].append(r)
    # per-topic recall: of the cases where the SEC raised topic T, how often did we flag T
    topic_recall: dict[str, list[float]] = defaultdict(list)
    for r in scored:
        top = set(list(dict.fromkeys(r["pred"]))[:k])
        for t in r["case"].gold_topics:
            topic_recall[t].append(float(t in top))
    return {
        "k": k,
        "overall": summary(scored),
        "by_year": {y: summary(rs) for y, rs in sorted(by_year.items())},
        "topic_recall": {t: {"n": len(v), "recall": round(mean(v), 3)}
                         for t, v in sorted(topic_recall.items(), key=lambda x: -len(x[1]))},
    }
