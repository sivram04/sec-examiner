# Project 2: AI Research Desk (Autonomous Equity Research)

> Build order: **second** (flagship). Uses the Project 1 gateway for all LLM calls.
> Constraint: **free resources only**. Owner: Sivaram Vangavolu (GitHub `sivram04`).

## 1. One-line pitch
A team of AI agents that researches public companies the way an analyst desk does. It reads SEC filings, earnings calls and macro data, tracks how facts change over time, debates bull and bear cases, and writes a cited research note in which every number is computed in code.

## 2. Why it matters (résumé link)
Mirrors the Morgan Stanley work at full depth: RAG over 500K+ documents, hybrid search with reranking, LangGraph agents with memory and human-in-the-loop, document intelligence, and LLM evals gating releases. It also mirrors Lakshyaa.ai's supervisor and specialist agents, and its hybrid LLM-plus-deterministic numbers.

## 3. Requirements

### Functional
- **F1. Ingestion.** Pull SEC EDGAR filings (10-K, 10-Q, 8-K, DEF 14A), XBRL financial facts, earnings call transcripts (from public sources), news RSS, and FRED macro series. Start with **~100 companies** (e.g. S&P 100), designed to scale.
- **F2. Streaming updates.** New filings are detected (EDGAR RSS polling) and pushed through a queue. They are parsed, chunked, embedded and indexed within minutes.
- **F3. Document processing.** Section-aware parsing (Item 1A Risk Factors, Item 7 MD&A), table extraction, and metadata on every chunk (ticker, form, period, filing date, section).
- **F4. Hybrid retrieval.** BM25 plus dense vectors, reciprocal rank fusion, then cross-encoder reranking. Metadata filters by ticker, period and section.
- **F5. Temporal knowledge graph.** Entities (companies, executives, segments, products, risks, guidance) and relationships, with **valid-from / valid-to** dates, so the system can answer "what changed between Q2 and Q3". GraphRAG over it.
- **F6. Point-in-time correctness.** Every query takes an `as_of` date, and retrieval never returns anything published after it. This is required for backtests.
- **F7. Agent team (LangGraph).**

  | Agent | Job |
  |---|---|
  | Planner / supervisor | Breaks the question into tasks and assigns them |
  | Fundamentals analyst | Financial statements and ratios via XBRL |
  | Transcript analyst | Tone, hedging and guidance language in calls |
  | Risk analyst | New, removed or changed risk factors (diff across filings) |
  | Quant agent | Runs Python in a sandbox, so no LLM arithmetic |
  | Bull agent / Bear agent | Argue opposite cases from the evidence |
  | Critic / verifier | Checks every claim against its cited source and rejects unsupported ones |
  | Report writer | Writes the final cited note |
- **F8. Memory.** Per-user and per-company long-term memory (prior notes and watched theses), plus short-term graph state with checkpoints.
- **F9. Human-in-the-loop.** The user can approve or redirect the plan before the expensive steps, and accept or reject the critic's flags.
- **F10. Tools via MCP.** EDGAR search, XBRL lookup, FRED, sandboxed Python, and graph query, each exposed as an MCP server.
- **F11. Outputs.** A research note in Markdown and PDF with inline citations (click through to the filing passage), a "what changed" diff view, and a bull vs bear summary table.
- **F12. Backtest mode.** For past dates, generate signals (e.g. risk-language deterioration) using point-in-time data only, and compare them against later stock returns versus a simple baseline. Clearly labeled as research, not investment advice.
- **F13. Web app.** Chat-style research UI, company pages, live agent trace view, and report library.

### Non-functional
- **N1. Citation precision ≥ 95%** on the golden set: every cited passage must support its claim.
- **N2. Zero computed numbers from the LLM.** All arithmetic goes through the quant tool, enforced by the critic and tests.
- **N3.** A full report in under 3 minutes, with cost per report logged.
- **N4.** Evals run in CI, and a drop in faithfulness or citation precision fails the build.
- **N5.** Works within free-tier rate limits, using the gateway's caching and routing.

### Out of scope (v1)
Real-time market data, trading, personalized advice.

## 4. Architecture

```
EDGAR RSS / FRED / transcripts / news
        │  (scheduler: APScheduler or GitHub Actions cron)
        ▼
Redpanda (Kafka API) topics: raw-docs → parsed → embedded
        │
Workers (Python): parse (section + tables) → chunk → embed → index
        │                     │                       │
     Qdrant (vectors)   OpenSearch/Tantivy (BM25)   Neo4j (temporal KG)
        │                     │                       │
        └──────── Retrieval service (hybrid + rerank + as_of filter) ───┐
                                                                         ▼
LangGraph agent team ──(MCP tools)──► sandboxed Python, XBRL, FRED, graph
        │  all LLM calls ──► Project 1 gateway
        ▼
FastAPI backend ─► Postgres (users, memory, reports) ─► Next.js web app
Langfuse traces · Ragas/DeepEval eval suite in CI
```

## 5. Tools (all free)

| Layer | Tool | Free source |
|---|---|---|
| Data | SEC EDGAR full-text and XBRL APIs, FRED API, public transcripts, RSS | Free (EDGAR needs a User-Agent header) |
| Parsing | `sec-parser` / `edgartools`, unstructured, pdfplumber, BeautifulSoup | OSS |
| Queue | Redpanda (Docker) | OSS |
| Vector DB | Qdrant (self-hosted on Oracle VM) | OSS |
| Keyword search | OpenSearch or Tantivy (via `tantivy-py`), or Qdrant sparse vectors (BM25) | OSS |
| Embeddings | bge-small/base (local) or Gemini embeddings | OSS / free tier |
| Reranker | bge-reranker-base (local CPU) | OSS |
| Graph | Neo4j AuraDB Free (or Neo4j Community in Docker), Graphiti for temporal KG | Free / OSS |
| Agents | LangGraph, LangChain core, MCP Python SDK | OSS |
| LLMs | Via Project 1 gateway: Gemini, Groq Llama/Qwen, OpenRouter free | Free tiers |
| Sandbox | Docker-isolated Python runner (or `e2b` free tier) | OSS / free |
| Backend | FastAPI, Celery or arq workers, Postgres (Neon), Redis | OSS / free |
| Frontend | Next.js + Tailwind + shadcn/ui, hosted on Vercel | Free |
| Evals | Ragas, DeepEval, LLM-as-a-judge, golden dataset in repo | OSS |
| Observability | Langfuse, OpenTelemetry | OSS / free |
| Backtest | pandas, yfinance (historical prices) or Stooq | Free |
| CI/CD | GitHub Actions | Free |
| Hosting | Oracle Cloud Always Free VM (backend + DBs), Vercel (UI) | Free |

## 6. Phases

### Phase 0: Setup (3 days)
- Repo `sivram04/ai-research-desk`. Docker Compose: Redpanda, Qdrant, Neo4j, Postgres, Redis, Langfuse.
- Connect to the Project 1 gateway. CI skeleton.
- **Done when:** all services are up locally and CI is green.

### Phase 1: Ingestion pipeline (1.5 weeks)
- EDGAR fetchers for 100 tickers, about 5 years of 10-K, 10-Q and 8-K filings. XBRL facts into Postgres.
- Section-aware parser, table extraction, chunking with rich metadata.
- Streaming flow through Redpanda. New-filing watcher.
- **Done when:** the corpus is indexed (document and chunk counts published), and a new filing goes live in under 10 minutes.

### Phase 2: Hybrid retrieval with as-of filtering (1 week)
- BM25 plus vectors, RRF fusion, cross-encoder rerank, metadata and `as_of` filters.
- Build a **retrieval golden set** (~200 questions with known source passages).
- **Done when:** recall@10, MRR and nDCG are measured for BM25-only, vector-only, hybrid, and hybrid with rerank. The comparison table goes in the README.

### Phase 3: Temporal knowledge graph (1.5 weeks)
- Entity and relation extraction from filings into Neo4j, with validity dates (Graphiti or custom).
- Risk-factor diffing across consecutive filings.
- GraphRAG queries ("which suppliers did X mention in 2023 but not 2025?").
- **Done when:** "what changed" questions are answered correctly on a 50-question temporal test set.

### Phase 4: Agent team (2 weeks)
- LangGraph supervisor and the 8 agents. MCP tool servers. Sandboxed quant agent.
- Bull/bear debate and critic verification loop. Human-in-the-loop checkpoint.
- Long-term memory in Postgres.
- **Done when:** end-to-end cited reports generate for any covered ticker, and the critic rejects seeded false claims.

### Phase 5: Evaluation system (1 week)
- Golden QA set of **500+ questions** (factual, numeric, temporal, multi-hop).
- Ragas and DeepEval: faithfulness, answer relevancy, context precision, citation precision. Numeric exact-match.
- Wired into CI as a regression gate. Langfuse dashboards.
- **Done when:** the eval report is published, and CI fails on a deliberate regression.

### Phase 6: Backtest study (1 week)
- Point-in-time signal from risk-language change and transcript tone. Compare against forward returns vs a baseline.
- Write up results honestly, including if the signal is weak.
- **Done when:** a reproducible notebook and README section exist, with a leakage test proving no future data is used.

### Phase 7: Web app and deploy (1.5 weeks)
- Next.js UI: ask, live agent trace, report with clickable citations, change diff, company pages.
- Deploy the backend on Oracle VM and the UI on Vercel. Demo video and architecture diagram.
- **Done when:** a public demo URL works, and every README number comes from a script.

## 7. Metrics to publish (measured only)
Corpus size (documents and chunks) · retrieval recall@10 and nDCG by method · faithfulness and citation precision · numeric accuracy · temporal QA accuracy · time and cost per report · backtest result vs baseline.

## 8. Portfolio entry (fill in after Phase 7)
Lanes: AI, Analytics, Cloud & DevOps, Software. Charts: retrieval method comparison, eval scores, agent-flow route diagram. Links: GitHub, live demo, sample report.

## 9. Starting prompt for a new chat
> "Start Project 2 (AI research desk) from `ai-projects/02-ai-research-desk.md`. Project 1 gateway is at <URL or 'not finished, use providers directly for now'>. Begin Phase 0. Repo `ai-research-desk` under `sivram04`. Free resources only."
