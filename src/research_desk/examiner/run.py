"""Train a versioned Examiner and grade it with the sealed judge.

The judge decides; this module only wires the worker to it. A version's report (metrics,
gate result, baselines) is saved beside its model, giving every version an audit record.
"""
import json
from pathlib import Path

from ..judge.baselines import BASELINES
from ..judge.cases import cases_from, history_before
from ..judge.harness import evaluate, gate
from .filings import load
from .model import Examiner, filing_text, train


def texts_for(cases, filings_root: Path) -> dict[str, str]:
    return {c.case_id: filing_text(load(filings_root, c.case_id)) for c in cases}


def train_and_grade(records: list[dict], filings_root: Path, models_root: Path, version: str,
                    test_from: str = "2024-01-01", k: int = 5, log=print) -> dict:
    # training labels may only come from letters published before the test window
    train_records = [r for r in records if r["letter"]["letter_date"] < test_from]
    train_cases = [c for c in cases_from(train_records) if c.filing_date < test_from]
    all_cases = cases_from(records)
    texts = texts_for(all_cases, filings_root)
    log(f"training on {len(train_cases)} cases "
        f"({sum(bool(texts.get(c.case_id)) for c in train_cases)} with filing text)")
    ex = train(version, train_cases, texts,
               lambda c: history_before(train_records, c.filing_date), log=log)

    def predictor(case, history):
        return ex.predict(case, history, texts.get(case.case_id, ""))

    rep = evaluate(predictor, records, test_from=test_from, k=k)
    base = {n: evaluate(fn, records, test_from=test_from, k=k) for n, fn in BASELINES.items()}
    verdict = gate(rep, base)
    ex.meta.update({"test": rep, "gate": verdict,
                    "baselines": {n: b["overall"] for n, b in base.items()}})
    d = ex.save(models_root)
    log(f"saved {d}")
    return ex.meta


def latest_report(models_root: Path) -> dict | None:
    metas = sorted(models_root.glob("*/meta.json"))
    return json.loads(metas[-1].read_text(encoding="utf-8")) if metas else None


__all__ = ["Examiner", "latest_report", "train_and_grade"]
