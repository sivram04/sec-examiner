"""Train a versioned Examiner and grade it with the sealed judge.

Two grading windows keep self-improvement honest:
- selection (filings Jan-Feb 2024, 266 cases): the loop compares candidates here;
- holdout (filings from Mar 2024, 306 cases): never used to choose anything, only reported,
  so the final numbers are not inflated by trying many versions.
Most reviewed filings are annual reports from the Feb-Apr filing season, so the split sits
inside it. A later-year holdout (letters published in 2025) is the stronger design.
The judge decides pass/fail; this module only wires the worker to it.
"""
from pathlib import Path

from ..judge.baselines import BASELINES
from ..judge.cases import cases_from, history_before
from ..judge.harness import evaluate, gate
from .filings import load
from .model import Examiner, Recipe, train

SELECT = ("2024-01-01", "2024-03-01")
HOLDOUT = ("2024-03-01", "9999")


def sections_for(cases, filings_root: Path) -> dict[str, dict]:
    return {c.case_id: load(filings_root, c.case_id) or {} for c in cases}


def grade(ex: Examiner, records: list[dict], sections: dict[str, dict], window, k: int = 5):
    def predictor(case, history):
        return ex.predict(case, history, sections.get(case.case_id))

    rep = evaluate(predictor, records, test_from=window[0], test_to=window[1], k=k)
    base = {n: evaluate(fn, records, test_from=window[0], test_to=window[1], k=k)
            for n, fn in BASELINES.items()}
    return rep, base, gate(rep, base)


def train_and_grade(records: list[dict], filings_root: Path, models_root: Path, version: str,
                    recipe: Recipe | None = None, select=SELECT, holdout=HOLDOUT,
                    log=print) -> dict:
    test_from = select[0]
    # training labels may only come from letters published before any graded window
    train_records = [r for r in records if r["letter"]["letter_date"] < test_from]
    train_cases = [c for c in cases_from(train_records) if c.filing_date < test_from]
    sections = sections_for(cases_from(records), filings_root)
    log(f"{version}: training on {len(train_cases)} cases")
    ex = train(version, train_cases, sections,
               lambda c: history_before(train_records, c.filing_date), recipe=recipe, log=log)
    sel, sel_base, sel_gate = grade(ex, records, sections, select)
    hold, hold_base, _ = grade(ex, records, sections, holdout)
    ex.meta.update({
        "selection": sel, "selection_gate": sel_gate,
        "selection_baselines": {n: b["overall"] for n, b in sel_base.items()},
        "holdout": hold, "holdout_baselines": {n: b["overall"] for n, b in hold_base.items()},
    })
    ex.save(models_root)
    o = sel["overall"]
    log(f"{version}: selection f1={o['f1']:.3f} (n={o['n']}) "
        f"holdout f1={hold['overall']['f1']:.3f} gate={'PASS' if sel_gate['passed'] else 'FAIL'}")
    return ex.meta
