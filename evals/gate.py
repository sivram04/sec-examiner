"""CI regression gate. Fails (exit 1) when a measured score drops below evals/thresholds.json.

Runs offline on committed fixtures:
  - retrieval: BM25 and hash-vector hybrid over evals/fixtures/corpus.jsonl.gz
  - critic: acceptance of true claims, rejection of perturbed/uncited claims

    python evals/gate.py [--write-baseline]
"""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from research_desk.agents.critic import Claim, verify
from research_desk.retrieval.evaluate import evaluate, load_golden
from research_desk.retrieval.index import HybridIndex
from research_desk.retrieval.models import HashEmbedder

THRESHOLDS = ROOT / "evals" / "thresholds.json"
RESULTS = ROOT / "evals" / "results" / "gate.json"


def retrieval_scores() -> dict[str, float]:
    with gzip.open(ROOT / "evals" / "fixtures" / "corpus.jsonl.gz", "rt", encoding="utf-8") as fh:
        corpus = [json.loads(line) for line in fh]
    idx = HybridIndex(HashEmbedder())
    idx.add(corpus)
    res = evaluate(idx, load_golden(ROOT / "evals" / "retrieval_golden.jsonl"),
                   methods=("bm25", "hybrid"))
    return {f"retrieval.{m}.{k}": v for m, r in res.items() for k, v in r.items()}


def critic_scores() -> dict[str, float]:
    cases = [json.loads(line) for line in
             (ROOT / "evals" / "critic_golden.jsonl").read_text(encoding="utf-8").splitlines()]
    got = [verify([Claim(c["claim"], c["citations"])], c["evidence"], {})[0].ok for c in cases]
    true = [g for g, c in zip(got, cases, strict=True) if c["expect"]]
    false = [g for g, c in zip(got, cases, strict=True) if not c["expect"]]
    return {"critic.true_claims_accepted": round(sum(true) / len(true), 3),
            "critic.false_claims_rejected": round(sum(not g for g in false) / len(false), 3)}


def main() -> int:
    scores = {**retrieval_scores(), **critic_scores()}
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(scores, indent=2) + "\n")
    if "--write-baseline" in sys.argv:
        THRESHOLDS.write_text(json.dumps(scores, indent=2) + "\n")
        print("baseline written")
        return 0
    limits = json.loads(THRESHOLDS.read_text())
    failed = False
    for key, floor in sorted(limits.items()):
        got = scores.get(key)
        ok = got is not None and got >= floor - 1e-9
        failed |= not ok
        print(f"{'PASS' if ok else 'FAIL'}  {key:40} {got!s:>6}  (min {floor})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
