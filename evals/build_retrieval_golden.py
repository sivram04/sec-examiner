"""Build the retrieval golden set from hand-written (question, answer phrase) candidates.

Each candidate is checked against the corpus: its phrase must appear in 1..MAX_MATCHES of the
ticker's chunks filed on or before as_of, so it is present and specific. Rejected candidates
are printed, never silently kept.

    python evals/build_retrieval_golden.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from research_desk.ingest.pipeline import load_corpus

MAX_MATCHES = 40

# (ticker, as_of, question, [phrases in the answering passage])
CANDIDATES = [
    ("NVDA", "2025-12-31", "What license requirement did the US government impose on H20 exports to China?", ["H20"]),
    ("NVDA", "2025-12-31", "How much did NVIDIA write down for H20 excess inventory and purchase obligations?", ["H20 excess inventory"]),
    ("NVDA", "2026-12-31", "Which foundry manufactures NVIDIA's GPUs?", ["Taiwan Semiconductor Manufacturing"]),
    ("NVDA", "2026-12-31", "What is the Blackwell architecture?", ["Blackwell architecture"]),
    ("NVDA", "2026-12-31", "How concentrated is NVIDIA's revenue among direct customers?", ["direct customer"]),
    ("NVDA", "2026-12-31", "What are NVIDIA's reportable segments?", ["Compute & Networking"]),
    ("NVDA", "2025-06-30", "What risks come from the AI diffusion export rule?", ["AI Diffusion"]),
    ("MSFT", "2026-12-31", "What is Microsoft's investment in OpenAI and how is it accounted for?", ["OpenAI"]),
    ("MSFT", "2026-12-31", "How did Azure and other cloud services revenue grow?", ["Azure and other cloud services revenue"]),
    ("MSFT", "2025-12-31", "When did Microsoft complete the Activision Blizzard acquisition?", ["Activision Blizzard"]),
    ("MSFT", "2026-12-31", "What are Microsoft's three reportable segments?", ["More Personal Computing"]),
    ("MSFT", "2026-12-31", "What drives Microsoft's capital expenditure on datacenters?", ["datacenter"]),
    ("MSFT", "2026-12-31", "What were Microsoft's unearned revenue balances?", ["unearned revenue"]),
    ("MSFT", "2026-12-31", "What does Microsoft say about competition in AI?", ["AI"]),
    ("AAPL", "2026-12-31", "How much were Apple's Services net sales?", ["Services net sales"]),
    ("AAPL", "2026-12-31", "How did Greater China net sales change?", ["Greater China"]),
    ("AAPL", "2026-12-31", "What are Apple's risks under the EU Digital Markets Act?", ["Digital Markets Act"]),
    ("AAPL", "2026-12-31", "What is the status of the Epic Games litigation?", ["Epic"]),
    ("AAPL", "2026-12-31", "How do tariffs affect Apple's gross margin?", ["tariff"]),
    ("AAPL", "2026-12-31", "How much stock did Apple repurchase?", ["repurchased"]),
    ("AAPL", "2026-12-31", "What was the European Commission State Aid decision about?", ["State Aid"]),
    ("AAPL", "2026-12-31", "What is Apple's iPhone net sales trend?", ["iPhone net sales"]),
    ("AAPL", "2026-12-31", "Where does Apple's manufacturing take place?", ["outsourcing partners"]),
    ("JPM", "2026-12-31", "What is JPMorgan's CET1 capital ratio?", ["CET1 capital ratio"]),
    ("JPM", "2026-12-31", "How did net interest income change?", ["net interest income"]),
    ("JPM", "2025-12-31", "What did JPMorgan acquire from First Republic?", ["First Republic"]),
    ("JPM", "2026-12-31", "What does JPMorgan say about the Basel III endgame proposal?", ["Basel III"]),
    ("JPM", "2026-12-31", "What is the allowance for credit losses?", ["allowance for credit losses"]),
    ("JPM", "2026-12-31", "What were card net charge-off rates?", ["net charge-off rate"]),
    ("JPM", "2026-12-31", "What is JPMorgan's liquidity coverage ratio?", ["LCR"]),
    ("JPM", "2026-12-31", "What value-at-risk does JPMorgan report?", ["VaR"]),
    ("XOM", "2026-12-31", "What does ExxonMobil report about Guyana production?", ["Guyana"]),
    ("XOM", "2026-12-31", "What is ExxonMobil's Permian Basin activity?", ["Permian"]),
    # tighter phrasings, taken from real sentences, for topics whose broad phrase repeats
    ("NVDA", "2025-12-31", "How much H20 revenue did NVIDIA record before the new export licensing requirement?", ["Sales of our H20 products were"]),
    ("NVDA", "2026-12-31", "How much H20 revenue came from the licenses granted in August 2025?", ["in H20 revenue under those licenses"]),
    ("MSFT", "2026-12-31", "What are Microsoft's total funding commitments to OpenAI?", ["total funding commitments"]),
    ("MSFT", "2026-12-31", "How did OpenAI investment gains or losses affect other income?", ["from investments in OpenAI"]),
    ("MSFT", "2026-12-31", "How much intangible assets relate to Activision Blizzard?", ["intangible assets of $ 22.0 billion related to Activision"]),
    ("MSFT", "2026-12-31", "How much of operating expense growth came from the Activision Blizzard acquisition?", ["points of growth from the Activision Blizzard acquisition"]),
    ("MSFT", "2026-12-31", "How much unearned revenue was recognized and deferred during the period?", ["Recognition of unearned revenue"]),
    ("JPM", "2026-12-31", "What is JPMorgan's Standardized CET1 requirement including regulatory buffers?", ["CET1 capital ratio requirement, including regulatory buffers"]),
    ("JPM", "2025-12-31", "When and from whom did JPMorgan acquire First Republic Bank?", ["assumed certain liabilities of First Republic Bank"]),
    ("JPM", "2026-12-31", "Which Basel III approach is more binding for JPMorgan's risk-based ratios?", ["were more binding than the Basel III Advanced"]),
    ("AAPL", "2025-12-31", "Why did Greater China net sales decrease in fiscal 2025?", ["Greater China net sales decreased during 2025"]),
    ("AAPL", "2026-12-31", "Why did Greater China net sales increase in the first quarter of 2026?", ["Greater China net sales increased during the first quarter of 2026"]),
]


def main() -> None:
    corpus = load_corpus(ROOT / "data" / "chunks")
    kept, out = 0, ROOT / "evals" / "retrieval_golden.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for n, (ticker, as_of, q, phrases) in enumerate(CANDIDATES, 1):
            matches = sum(1 for c in corpus if c["ticker"] == ticker
                          and c["filing_date"] <= as_of
                          and any(p.lower() in c["text"].lower() for p in phrases))
            if not 1 <= matches <= MAX_MATCHES:
                print(f"reject ({matches:4} matches) {ticker}: {q}")
                continue
            fh.write(json.dumps({"id": f"r{n:03d}", "question": q, "ticker": ticker,
                                 "as_of": as_of, "relevant": phrases}) + "\n")
            kept += 1
    print(f"kept {kept}/{len(CANDIDATES)} -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
