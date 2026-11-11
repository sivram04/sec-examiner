"""Grade any predictor against real SEC letters, point-in-time, and decide if it passes the gate.

A predictor is `fn(case, history) -> list[str]` (ranked topics), or `-> (list[str], cost_usd)`.
`history` holds only letters published before the case's filing date: the harness, not the
predictor, enforces that, so no version can peek at the letter it is being graded on.
"""
import hashlib
import json
import time
from pathlib import Path
from statistics import mean

from .cases import Case, cases_from, history_before
from .scoring import aggregate

JUDGE_DIR = Path(__file__).resolve().parent
MANIFEST = JUDGE_DIR / "MANIFEST.json"
GATES = JUDGE_DIR / "gates.json"
SEALED = ["__init__.py", "topics.py", "cases.py", "scoring.py", "baselines.py", "harness.py",
          "gates.json"]


class IntegrityError(RuntimeError):
    pass


def _digest() -> dict[str, str]:
    return {name: hashlib.sha256((JUDGE_DIR / name).read_bytes()).hexdigest() for name in SEALED}


def seal() -> dict[str, str]:
    """Record the judge's hashes. Run by a person when the judge itself is deliberately changed."""
    d = _digest()
    MANIFEST.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
    return d


def verify() -> None:
    if not MANIFEST.exists():
        raise IntegrityError("judge is not sealed: run `desk judge seal`")
    want = json.loads(MANIFEST.read_text(encoding="utf-8"))
    changed = [n for n, h in _digest().items() if want.get(n) != h]
    if changed:
        raise IntegrityError(f"judge files changed since sealing: {', '.join(changed)}")


def load_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def evaluate(predictor, records: list[dict], test_from: str, k: int = 5,
             test_to: str = "9999") -> dict:
    """Score `predictor` on cases filed in [test_from, test_to)."""
    verify()
    cases = [c for c in cases_from(records) if test_from <= c.filing_date < test_to]
    rows, secs, cost = [], [], 0.0
    for case in cases:
        hist = history_before(records, case.filing_date)
        t0 = time.perf_counter()
        out = predictor(case, hist)
        secs.append(time.perf_counter() - t0)
        if isinstance(out, tuple):
            out, c = out
            cost += c
        rows.append({"case": case, "pred": list(out)})
    rep = aggregate(rows, k)
    rep["cost_usd"] = round(cost, 4)
    rep["mean_secs"] = round(mean(secs), 4) if secs else 0.0
    rep["window"] = [test_from, test_to]
    return rep


def gate(candidate: dict, baselines: dict[str, dict]) -> dict:
    """Pass only if the candidate beats every baseline and stays within cost and latency limits."""
    g = json.loads(GATES.read_text(encoding="utf-8"))
    best = max(baselines.items(), key=lambda kv: kv[1]["overall"].get("f1", 0.0))
    f1 = candidate["overall"].get("f1", 0.0)
    checks = {
        "min_cases": candidate["overall"].get("n", 0) >= g["min_cases"],
        "beats_best_baseline": f1 >= best[1]["overall"]["f1"] + g["min_f1_margin"],
        "max_mean_secs": candidate["mean_secs"] <= g["max_mean_secs"],
        "max_cost_per_case": (candidate["cost_usd"] / max(1, candidate["overall"]["n"]))
        <= g["max_cost_usd_per_case"],
    }
    return {"passed": all(checks.values()), "checks": checks, "best_baseline": best[0],
            "best_baseline_f1": best[1]["overall"]["f1"], "candidate_f1": f1}


__all__ = ["Case", "IntegrityError", "evaluate", "gate", "load_records", "seal", "verify"]
