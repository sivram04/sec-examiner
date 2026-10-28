"""End-to-end LLM evals: run the desk on golden questions and measure what the plan requires.

  - citation precision: share of accepted claims an LLM judge says their citations support (N1)
  - verifier rejection rate: share of generated claims the deterministic critic rejected
  - seconds per report (N3)

Needs LLM_API_KEY and the local corpus (data/). Results go to evals/results/llm_evals.json.

    python evals/llm_evals.py [--limit 10] [--gate]
"""
import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import httpx

from research_desk.config import settings

JUDGE = ("You check citations. Answer only YES or NO: does the SOURCE text directly support "
         "every factual statement in the CLAIM?")
MIN_CITATION_PRECISION = 0.95


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--gate", action="store_true")
    a = p.parse_args()
    if not settings.llm_api_key:
        print("LLM_API_KEY not set; skipping LLM evals")
        return 0

    from research_desk.agents.desk import Tools, build_desk
    from research_desk.cli import DATA, _load_index
    from research_desk.ingest.facts import FactStore
    from research_desk.llm import USAGE, chat
    from research_desk.retrieval.evaluate import load_golden
    from research_desk.retrieval.index import Filters

    def llm(system: str, user: str) -> str:
        return chat([{"role": "system", "content": system}, {"role": "user", "content": user}])

    def judge(claim: str, source: str) -> bool:
        return llm(JUDGE, f"CLAIM: {claim}\n\nSOURCE:\n{source[:6000]}").strip().upper() \
            .startswith("YES")

    idx = _load_index()
    tools = Tools(search=lambda q, as_of, ticker, k: idx.search(
        q, Filters(date.fromisoformat(as_of), (ticker,)), k=k),
        facts=FactStore(DATA / "facts.db"), human_in_loop=False)
    desk = build_desk(llm, tools)
    rows, errors = [], []
    for q in load_golden(ROOT / "evals" / "retrieval_golden.jsonl")[: a.limit]:
        t0 = time.time()
        try:
            out = desk.invoke({"question": q["question"], "ticker": q["ticker"],
                               "as_of": q["as_of"]}, {"configurable": {"thread_id": q["id"]}})
            secs = time.time() - t0  # report time only; judge calls below are eval overhead
            # the label carries form, period and filing date, which claims may cite
            ev = {k: f"({v['label']})\n{v['text']}" for k, v in out["evidence"].items()}
            accepted = [v["claim"] for v in out["verdicts"] if v["ok"]]
            supported = [judge(c["text"], "\n---\n".join(
                ev.get(cid, json.dumps(out["quant"].get(cid[6:], {}))) for cid in c["citations"]))
                for c in accepted]
        except httpx.HTTPError as e:  # rate limit outlasting retries: record it, keep going
            errors.append({"id": q["id"], "error": str(e)[:200]})
            print(errors[-1])
            continue
        rows.append({"id": q["id"], "secs": round(secs, 1), "claims": len(out["verdicts"]),
                     "accepted": len(accepted), "supported": sum(supported)})
        print(rows[-1])

    acc = sum(r["accepted"] for r in rows)
    summary = {
        "questions": len(rows),
        "citation_precision": round(sum(r["supported"] for r in rows) / acc, 3) if acc else None,
        "verifier_rejection_rate": round(1 - acc / max(1, sum(r["claims"] for r in rows)), 3),
        "mean_secs_per_report": round(sum(r["secs"] for r in rows) / max(1, len(rows)), 1),
        # tokens include the judge's calls; on the free tier the dollar cost is 0
        "llm_calls": len(USAGE),
        "prompt_tokens": sum(u["prompt_tokens"] or 0 for u in USAGE),
        "completion_tokens": sum(u["completion_tokens"] or 0 for u in USAGE),
        "model": settings.llm_model, "errors": errors, "rows": rows}
    out_path = ROOT / "evals" / "results" / "llm_evals.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2) + "\n")
    print({k: v for k, v in summary.items() if k != "rows"})
    cp = summary["citation_precision"]
    return 1 if a.gate and (cp is None or cp < MIN_CITATION_PRECISION) else 0


if __name__ == "__main__":
    sys.exit(main())
