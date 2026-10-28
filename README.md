# AI Research Desk

A team of AI agents that researches public companies the way an analyst desk does. It reads SEC filings and XBRL financials, tracks how risk disclosures change over time, debates bull and bear cases, and writes a cited note in which every number is computed in code and every claim is checked against its source.

Full spec and phases: [PLAN.md](PLAN.md). Free resources only. Research output, not investment advice.

## How it works

```
EDGAR submissions / current-filings feed
      │  desk watch (poll)  ·  desk backfill
      ▼
raw-docs topic (Redpanda, or in-memory) ──► desk parse: section-aware parser + tables
      │                                       └─► data/chunks/<accession>.jsonl (corpus of record)
      ▼
parsed topic ──► hybrid index: BM25 (Lucene IDF) + Qdrant dense (bge-small) ──► RRF ──► bge-reranker
                 every query carries as_of: nothing filed later is ever returned
XBRL company facts ──► fact store (point-in-time series)
10-K Item 1A ──► risk factors ──► diff ──► temporal graph (valid_from / valid_to)
      ▼
LangGraph desk: planner → [human approves plan] → fundamentals · risk · transcript
               → quant sandbox → bull · bear → critic → [human reviews flags] → writer
      ▼
FastAPI + web UI  ·  MCP tool server  ·  eval gate in CI
```

Design rules that keep reports honest:
- **No LLM arithmetic.** Growth and margins come from fixed code run in the sandbox on XBRL inputs. The critic rejects any claim containing a number that isn't in a cited passage or a cited quant result.
- **Citations are rendered by code**, not written by the model, so a reference can't be invented.
- **Point in time.** Retrieval, XBRL series and the risk graph all take an `as_of` date. The backtest's leakage tests check that tampering with data before the filing date changes nothing.

## Status

| Phase | State |
|---|---|
| 0 Setup | Done: Docker stack, config, CI (lint, tests, eval gate) |
| 1 Ingestion | Done: EDGAR client (with paging for busy filers), section parser, table extraction, chunker, Redpanda pipeline, new-filing watcher, XBRL fact store |
| 2 Retrieval | Done: BM25 + dense + RRF + cross-encoder rerank with `as_of`/ticker/section filters; golden set and method comparison |
| 3 Temporal graph | Partial: risk-factor splitting, deterministic diff, validity spans, what-changed queries, Cypher export. LLM entity/relation extraction (executives, segments, suppliers) and GraphRAG not built yet |
| 4 Agent desk | Done in code and tests with a scripted LLM; not yet run against a real model (needs `LLM_API_KEY`) |
| 5 Evaluation | Partial: offline CI gate (retrieval fixture, critic regression set) proven to fail on a deliberate regression; LLM citation-precision runner written, not yet run |
| 6 Backtest | Code and leakage tests done; see results below |
| 7 Web app | Partial: FastAPI backend and a single-page UI served by it. The plan's Next.js/Vercel front end and public deploy are not done |

### Known gaps
- **Cross-reference filers** (JPM and most big banks) don't use Item headings in their 10-K. Their content is kept, but most of it lands under Item 15 or "other" rather than MD&A / Risk Factors.
- **XOM**: SEC's ticker map now resolves to a new entity (CIK 2115436) whose filings start in July 2026, so older Exxon history needs a CIK override.
- **Risk diff is headline-level.** When a filer folds several factors into one umbrella factor (MSFT, FY2025), the old headlines show as removed even though their content moved.
- **Transcripts** are not ingested yet; the transcript analyst says so in its trace rather than guessing.
- Facts, graph and memory use SQLite locally; the schemas are Postgres/Neo4j-ready (`to_cypher`), but those loaders aren't written.
- The golden retrieval set has 26 questions, against a plan target of ~200.

## Quickstart

```bash
python -m venv .venv && . .venv/Scripts/activate
pip install -e ".[dev]"
cp .env.example .env            # set SEC_USER_AGENT to "<name> <your email>"
pytest -q && python evals/gate.py

desk ingest --tickers AAPL,MSFT,NVDA --since 2024-01-01     # in-memory bus
desk facts --tickers AAPL,MSFT,NVDA
desk risk-graph --tickers AAPL,MSFT,NVDA --since 2022-01-01
desk search "export restrictions to China" --ticker NVDA --as-of 2025-06-30
desk risks NVDA
desk what-changed MSFT 2024-12-31 2025-12-31
desk backtest --tickers sp100 --since 2018-01-01
uvicorn research_desk.api:app --port 8000                    # web UI at http://localhost:8000
python -m research_desk.agents.mcp_server                    # MCP tools over stdio
```

With Redpanda: `docker compose up -d redpanda`, then `desk backfill --bus kafka` and `desk parse --bus kafka`.
To run the agents, set `LLM_API_KEY` (any OpenAI-compatible free tier, or the Project 1 gateway via `LLM_BASE_URL`): `desk research AAPL "Is gross margin at risk from tariffs?"`.

## Metrics

Only numbers produced by scripts in this repo appear here. Each one names the command that produced it.

**Corpus** (`desk stats`): 45 documents (11 10-K, 34 10-Q), 13,246 chunks, 5 tickers, filed 2024-01 to 2026-08. XBRL fact store: 139,335 facts for AAPL, MSFT, NVDA, JPM (`desk facts`).

**Eval gate** (`python evals/gate.py`, offline fixture of 1,876 chunks; easier than the full corpus because 376 of them are relevant):

| Check | Score | Floor |
|---|---|---|
| BM25 recall@10 / MRR | 0.962 / 0.814 | 0.94 / 0.79 |
| Hybrid (BM25 + hash vectors) recall@10 / MRR / nDCG@10 | 0.962 / 0.846 / 0.851 | 0.94 / 0.82 / 0.83 |
| Critic: true claims accepted | 1.000 (30 real sentences) | 0.95 |
| Critic: false claims rejected | 1.000 (30 perturbed numbers + 3 citation failures) | 1.00 |

With number-checking disabled, the false-claim rejection rate fell to 0.061 and the gate exited 1.

**Retrieval method comparison on the full corpus** (`desk eval-retrieval`, 13,246 chunks, 26 golden questions, bge-small embeddings, bge-reranker-base; [evals/results/retrieval.md](evals/results/retrieval.md)):

| Method | Recall@10 (hit rate) | MRR | nDCG@10 |
|---|---|---|---|
| BM25 | 0.962 | 0.634 | 0.714 |
| Dense | 0.808 | 0.573 | 0.628 |
| Hybrid (RRF) | 0.885 | 0.658 | 0.711 |
| Hybrid + rerank | 0.885 | 0.756 | 0.785 |

The reranker gives the best ordering (MRR +0.12 over BM25), but BM25 finds the most answers. Caveat: relevance is judged by exact answer phrases, which favours lexical search, and 26 questions is a small sample. Hybrid fusion also loses recall here, because dense results push lexical hits out of the top 10. Worth trying next: a larger fusion pool, or weighting BM25 more for numeric and entity questions. Building the embedded index took 46 minutes on CPU.

**Backtest** (`desk backtest --tickers sp100 --since 2018-01-01`; [evals/results/backtest.json](evals/results/backtest.json)). Signal: risk-factor deterioration between consecutive 10-Ks. Return: excess over SPY from the first close after the filing date.

| Window | Filing pairs | Tickers | Spearman(signal, excess) | Noise band (±2/√n) | High − low tercile |
|---|---|---|---|---|---|
| 63 trading days | 512 | 78 | 0.033 | 0.088 | +1.2 pp |
| 252 trading days | 441 | 77 | 0.018 | 0.095 | +3.9 pp |

**Result: no usable signal.** Both correlations sit well inside the noise band. The tercile spread even points the "wrong" way: more new risk language goes with slightly *higher* later returns. This is reported as a negative result, not tuned until something looked significant.

Coverage gaps in this run: 24 tickers produced no filing pairs because their Item 1A couldn't be split into individual factors: AMGN, AMT, AMZN, BMY, C, CSCO, DUK, EMR, GE, INTC, INTU, LLY, MCD, MET, MMM, MS, NOW, PFE, UNP, USB, VZ, WFC, WMT and XOM. BK is missing from SEC's ticker map. Fixing the risk-factor splitter for those filers would widen the sample.
