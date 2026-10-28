"""FastAPI backend: search, company pages, what-changed, report library, and the agent desk.

    uvicorn research_desk.api:app --port 8000

The research endpoint is two-step for human-in-the-loop: POST /api/research returns either a
finished report or an interrupt (plan to approve, flags to review) with a thread id; POST
/api/research/{thread}/resume continues it.
"""
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import settings

DATA = Path("data")
WEB = Path(__file__).resolve().parent / "web"


@dataclass
class Backend:
    """Lazily built resources; tests pass ready-made ones instead."""
    data: Path = DATA
    index: Any = None
    llm: Any = None

    @cached_property
    def idx(self):
        if self.index is None:
            from .cli import _load_index

            self.index = _load_index()
        return self.index

    @cached_property
    def facts(self):
        from .ingest.facts import FactStore

        return FactStore(self.data / "facts.db")

    @cached_property
    def graph(self):
        from .graph.temporal import TemporalGraph

        return TemporalGraph(self.data / "graph.db")

    @cached_property
    def memory(self):
        from .agents.memory import Memory

        return Memory(self.data / "memory.db")

    @cached_property
    def desk(self):
        from .agents.desk import Tools, build_desk
        from .retrieval.index import Filters

        llm = self.llm
        if llm is None:
            if not settings.llm_api_key:
                raise HTTPException(503, "LLM_API_KEY is not configured on the server")
            from .llm import chat

            def llm(system: str, user: str) -> str:
                return chat([{"role": "system", "content": system},
                             {"role": "user", "content": user}])
        tools = Tools(search=lambda q, as_of, ticker, k: self.idx.search(
            q, Filters(date.fromisoformat(as_of), (ticker,)), k=k),
            facts=self.facts, graph=self.graph, memory=self.memory)
        return build_desk(llm, tools)


class ResearchRequest(BaseModel):
    ticker: str
    question: str
    as_of: str | None = None
    user: str = "default"


def _hit(h) -> dict:
    c = h.chunk
    return {"id": c["id"], "ticker": c["ticker"], "form": c["form"], "filed": c["filing_date"],
            "section": c["section"], "section_title": c["section_title"], "text": c["text"],
            "url": c["source_url"], "score": round(float(h.score), 4), "ranks": h.ranks}


def _desk_response(thread: str, out: dict) -> dict:
    if "__interrupt__" in out:
        return {"thread": thread, "status": "needs_input",
                "interrupt": out["__interrupt__"][0].value, "trace": out.get("trace", [])}
    return {"thread": thread, "status": "done", "report": out["report"],
            "trace": out["trace"], "verdicts": out["verdicts"]}


def create_app(backend: Backend | None = None) -> FastAPI:
    be = backend or Backend()
    app = FastAPI(title="AI Research Desk")
    # the Next.js front end (frontend/) runs on its own origin, locally and on Vercel
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","),
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    @app.get("/api/companies")
    def companies():
        from .ingest.pipeline import load_corpus

        corpus = load_corpus(be.data / "chunks")
        docs = {c["accession"]: c for c in corpus}
        per = Counter(c["ticker"] for c in docs.values())
        latest = {}
        for c in docs.values():
            latest[c["ticker"]] = max(latest.get(c["ticker"], ""), c["filing_date"])
        return [{"ticker": t, "documents": n, "latest_filing": latest[t]}
                for t, n in sorted(per.items())]

    @app.get("/api/search")
    def search(q: str, ticker: str | None = None, as_of: str | None = None,
               section: str | None = None, method: str = "hybrid_rerank", k: int = 8):
        from .retrieval.index import Filters

        if method not in ("bm25", "dense", "hybrid", "hybrid_rerank"):
            raise HTTPException(400, "unknown method")
        f = Filters(date.fromisoformat(as_of) if as_of else None,
                    (ticker.upper(),) if ticker else (), (section,) if section else ())
        t0 = time.time()
        hits = be.idx.search(q, f, k=min(k, 25), method=method)
        return {"ms": round((time.time() - t0) * 1000), "hits": [_hit(h) for h in hits]}

    @app.get("/api/risks/{ticker}")
    def what_changed(ticker: str, start: str, end: str):
        added, removed = be.graph.changed_between(ticker.upper(), "HAS_RISK", start, end)
        return {"added": [{"risk": e.object, "evidence": e.evidence,
                           "filing": e.source_accession, "since": e.valid_from} for e in added],
                "removed": [{"risk": e.object, "filing": e.ended_by, "until": e.valid_to}
                            for e in removed]}

    @app.get("/api/facts/{ticker}/{concept}")
    def facts(ticker: str, concept: str, as_of: str | None = None, form: str = "10-K"):
        rows = be.facts.series(ticker, concept, as_of=as_of, form=form)
        by_end = {r["end"]: r for r in rows if r["fp"] == "FY"}
        return [{"end": e, "value": r["value"], "filed": r["filed"], "accession": r["accession"]}
                for e, r in sorted(by_end.items())]

    @app.get("/api/reports")
    def reports(user: str = "default"):
        rows = be.memory.db.execute(
            "SELECT id, ticker, question, as_of, created FROM notes WHERE user=? "
            "ORDER BY created DESC LIMIT 100", (user,)).fetchall()
        return [{"id": i, "ticker": t, "question": q, "as_of": a, "created": c}
                for i, t, q, a, c in rows]

    @app.get("/api/reports/{note_id}")
    def report(note_id: int):
        row = be.memory.db.execute("SELECT ticker, question, as_of, report FROM notes WHERE id=?",
                                   (note_id,)).fetchone()
        if not row:
            raise HTTPException(404, "no such report")
        return dict(zip(("ticker", "question", "as_of", "report"), row, strict=True))

    @app.post("/api/research")
    def research(req: ResearchRequest):
        thread = f"{req.ticker.upper()}-{time.time_ns()}"
        out = be.desk.invoke({"question": req.question, "ticker": req.ticker.upper(),
                              "as_of": req.as_of or date.today().isoformat(), "user": req.user},
                             {"configurable": {"thread_id": thread}})
        return _desk_response(thread, out)

    @app.post("/api/research/{thread}/resume")
    def resume(thread: str, answer: dict):
        from langgraph.types import Command

        # an empty resume value would re-raise the interrupt, so treat {} as plain approval
        out = be.desk.invoke(Command(resume=answer or {"approve": True}),
                             {"configurable": {"thread_id": thread}})
        return _desk_response(thread, out)

    return app


app = create_app()
