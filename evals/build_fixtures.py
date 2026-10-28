"""Build the small, committed eval fixtures that CI runs on (no network, no models).

1. evals/fixtures/corpus.jsonl.gz: every chunk relevant to a golden question plus a fixed
   random sample of distractors from the full corpus.
2. evals/critic_golden.jsonl: real numeric sentences from filings as true claims, the same
   sentences with one number perturbed as false claims, plus citation-failure cases.

    python evals/build_fixtures.py      (needs data/chunks from `desk ingest`)
"""
import gzip
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from research_desk.agents.critic import numbers
from research_desk.ingest.pipeline import load_corpus
from research_desk.retrieval.evaluate import is_relevant, load_golden

DISTRACTORS = 1500
CRITIC_CASES = 60
SEED = 7


def main() -> None:
    rng = random.Random(SEED)
    corpus = load_corpus(ROOT / "data" / "chunks")
    golden = load_golden(ROOT / "evals" / "retrieval_golden.jsonl")

    relevant = {c["id"] for c in corpus for q in golden if is_relevant(c, q)}
    others = sorted(c["id"] for c in corpus if c["id"] not in relevant)
    keep = relevant | set(rng.sample(others, min(DISTRACTORS, len(others))))
    fx = ROOT / "evals" / "fixtures"
    fx.mkdir(parents=True, exist_ok=True)
    with gzip.open(fx / "corpus.jsonl.gz", "wt", encoding="utf-8") as fh:
        for c in corpus:
            if c["id"] in keep:
                fh.write(json.dumps(c) + "\n")
    print(f"fixture corpus: {len(keep)} chunks ({len(relevant)} relevant)")

    sentences = []
    for c in corpus:
        if c["kind"] != "text":
            continue
        for s in re.split(r"(?<=[.])\s+", c["text"]):
            if 60 < len(s) < 300 and len(numbers(s)) >= 1 and "|" not in s:
                sentences.append((c, s))
    rng.shuffle(sentences)
    cases = []
    for c, s in sentences[:CRITIC_CASES // 2]:
        ev = {"e1": c["text"]}
        cases.append({"claim": s, "citations": ["e1"], "evidence": ev, "expect": True,
                      "kind": "true_sentence"})
        n = sorted(numbers(s))[0]
        m = re.search(rf"(?<![\d.,]){re.escape(n)}(?![\d])", s.replace(",", ""))
        bad = str(round(float(n) * 1.37 + 3, 1))
        wrong = (s.replace(",", "")[:m.start()] + bad + s.replace(",", "")[m.end():]) if m else None
        if wrong and bad not in numbers(c["text"]):
            cases.append({"claim": wrong, "citations": ["e1"], "evidence": ev, "expect": False,
                          "kind": "perturbed_number"})
    c, s = sentences[0]
    cases += [
        {"claim": s, "citations": [], "evidence": {"e1": c["text"]}, "expect": False,
         "kind": "no_citation"},
        {"claim": s, "citations": ["e9"], "evidence": {"e1": c["text"]}, "expect": False,
         "kind": "unknown_citation"},
        {"claim": s, "citations": ["e2"], "evidence": {"e1": c["text"], "e2": "Unrelated text."},
         "expect": False, "kind": "wrong_citation"},
    ]
    with (ROOT / "evals" / "critic_golden.jsonl").open("w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(x) + "\n" for x in cases)
    print(f"critic cases: {len(cases)}")


if __name__ == "__main__":
    main()
