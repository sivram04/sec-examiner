"""MCP server exposing the desk's tools: filing search, XBRL lookup, risk changes, quant sandbox.

Run over stdio for any MCP client:  python -m research_desk.agents.mcp_server
"""
from datetime import date
from functools import cache
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import sandbox

DATA = Path("data")
mcp = MCPServer("research-desk")


@cache
def _index():
    from ..cli import _load_index

    return _load_index(rerank=True)


@mcp.tool()
def search_filings(query: str, ticker: str, as_of: str, section: str = "", k: int = 5) -> list:
    """Hybrid search over SEC filings filed on or before as_of (YYYY-MM-DD)."""
    from ..retrieval.index import Filters

    f = Filters(date.fromisoformat(as_of), (ticker.upper(),), (section,) if section else ())
    return [{"id": h.chunk["id"], "form": h.chunk["form"], "filed": h.chunk["filing_date"],
             "section": h.chunk["section"], "text": h.chunk["text"], "url": h.chunk["source_url"]}
            for h in _index().search(query, f, k=k)]


@mcp.tool()
def xbrl_series(ticker: str, concept: str, as_of: str, form: str = "10-K") -> list:
    """Reported XBRL values for a us-gaap concept, as known on as_of (point in time)."""
    from ..ingest.facts import FactStore

    return FactStore(DATA / "facts.db").series(ticker, concept, as_of=as_of, form=form)


@mcp.tool()
def risk_changes(ticker: str, start: str, end: str) -> dict:
    """Risk factors that appeared or disappeared in 10-Ks between two dates."""
    from ..graph.temporal import TemporalGraph

    added, removed = TemporalGraph(DATA / "graph.db").changed_between(
        ticker.upper(), "HAS_RISK", start, end)
    return {"added": [{"risk": e.object, "filing": e.source_accession} for e in added],
            "removed": [{"risk": e.object, "filing": e.ended_by} for e in removed]}


@mcp.tool()
def run_python(code: str, inputs: dict | None = None) -> dict:
    """Run Python in the sandbox. Read `inputs`, assign a dict to `result`."""
    r = sandbox.run(code, inputs)
    return {"ok": r.ok, "result": r.result, "error": r.error}


if __name__ == "__main__":
    mcp.run()
