# AI Research Desk

A team of AI agents that researches public companies the way an analyst desk does. It reads SEC filings, earnings calls and macro data, tracks how facts change over time, debates bull and bear cases, and writes a cited note in which every number is computed in code.

Full spec and phases: [PLAN.md](PLAN.md). Free resources only.

## Status
- [x] Phase 0: repo skeleton, Docker stack, config, LLM client, CI
- [ ] Phase 1: EDGAR client (ticker→CIK, filings with `as_of`, XBRL facts), section-aware 10-K/10-Q parser with table extraction, chunker with metadata. Next: Redpanda flow, new-filing watcher
  - Known gap: filers that use a cross-reference index instead of Item headings (e.g. JPM, most large banks) get mis-sectioned. Needs a heading-based fallback.

```bash
desk sections MSFT --form 10-Q --out data/msft-10q.jsonl   # per-item stats + JSONL chunks
```
- [ ] Phases 2–7

## Quickstart
```bash
python -m venv .venv && . .venv/Scripts/activate
pip install -e ".[dev]"
cp .env.example .env          # set SEC_USER_AGENT with your email
docker compose up -d          # redpanda, qdrant, neo4j, postgres, redis
pytest -q
desk filings AAPL --forms 10-K --as-of 2024-01-01
```

All LLM calls go through `research_desk.llm.chat`, an OpenAI-compatible client. Point `LLM_BASE_URL` at the Project 1 gateway once it exists.

## Metrics
None yet. Only numbers produced by scripts in this repo will be published here.
