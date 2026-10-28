"""The research desk: a LangGraph team of specialist agents.

planner -> [human approves plan] -> fundamentals, risk, transcript -> quant
        -> bull, bear -> critic -> [human reviews flags] -> writer

Division of labour that keeps reports honest:
  - evidence comes only from tools (retrieval, XBRL facts, risk graph), each item with an id;
  - every number is computed by the quant sandbox from XBRL inputs, never by the LLM;
  - the critic deterministically rejects uncited claims and numbers not found in sources;
  - the writer renders citations in code, so the LLM cannot invent a reference.
"""
import itertools
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from . import sandbox
from .critic import Claim, verify

LLM = Callable[[str, str], str]  # (system, user) -> text

DEFAULT_METRICS = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                   "NetIncomeLoss", "OperatingIncomeLoss", "GrossProfit"]

# fixed, reviewed computation used when the plan asks for growth / margins; the LLM never
# writes arithmetic into the report, it only cites these results
GROWTH_CODE = """
out = {}
for name, pts in inputs["series"].items():
    pts = sorted(pts, key=lambda p: p["end"])
    if len(pts) >= 2 and pts[-2]["value"]:
        a, b = pts[-2], pts[-1]
        out[name] = {"latest": b["value"], "latest_end": b["end"], "prior": a["value"],
                     "prior_end": a["end"], "growth_pct": round((b["value"] / a["value"] - 1) * 100, 1)}
rev = next((out[k] for k in inputs["revenue_keys"] if k in out), None)
for k in ("NetIncomeLoss", "OperatingIncomeLoss", "GrossProfit"):
    if rev and k in out and out[k]["latest_end"] == rev["latest_end"]:
        out[k]["margin_pct"] = round(out[k]["latest"] / rev["latest"] * 100, 1)
result = out
"""


class DeskState(TypedDict, total=False):
    question: str
    ticker: str
    as_of: str
    user: str
    plan: dict
    evidence: dict[str, dict]        # id -> {"text", "source", "label"}
    quant: dict[str, dict]
    claims: list[dict]
    verdicts: list[dict]
    report: str
    trace: list[dict]


@dataclass
class Tools:
    search: Callable[..., list]                 # HybridIndex.search-like
    facts: Any = None                           # FactStore
    graph: Any = None                           # TemporalGraph
    memory: Any = None                          # Memory
    releases: Callable[[str, str], list[dict]] | None = None  # (ticker, as_of) -> releases
    sandbox_mode: str = "subprocess"
    judge: Callable[[str, str], bool] | None = None
    human_in_loop: bool = True
    log: list = field(default_factory=list)


def parse_json(text: str) -> Any:
    """Pull the first JSON object/array out of an LLM reply (tolerates code fences)."""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    text = m.group(1) if m else text
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError(f"no JSON in reply: {text[:200]}")
    return json.JSONDecoder().raw_decode(text[start:])[0]


def _trace(state: DeskState, agent: str, t0: float, **info) -> list[dict]:
    return [*state.get("trace", []), {"agent": agent, "secs": round(time.time() - t0, 2),
                                      **info}]


def _evidence_block(ev: dict[str, dict], limit: int = 40, chars: int = 900) -> str:
    return "\n\n".join(f"[{eid}] ({e['label']})\n{e['text'][:chars]}"
                       for eid, e in list(ev.items())[:limit])


CLAIMS_SPEC = (
    'Reply with JSON only: {"claims": [{"text": "...", "citations": ["<evidence id>", ...]}]}. '
    "Every claim must cite evidence ids from the list given. Each claim states only what its "
    "cited evidence says: no adjectives, predictions or judgements the source doesn't make. "
    "If the source gives several causes, keep all of them. Take dates and periods only from "
    "the evidence label or text; if the period isn't stated, don't name one. "
    "Make only claims that bear directly on the question; skip general financial facts that "
    "don't. Use numbers only as they appear in the cited evidence or in quant results (cite "
    "those as quant:<metric>); never compute, round or convert numbers yourself. 3 to 6 claims.")


def build_desk(llm: LLM, tools: Tools):
    def planner(s: DeskState) -> dict:
        t0 = time.time()
        prior = tools.memory.notes(s.get("user", "default"), s["ticker"]) if tools.memory else []
        reply = llm(
            "You plan equity research. Reply with JSON only: "
            '{"queries": ["search query", ...], "metrics": ["XBRL us-gaap concept", ...], '
            '"focus": "one sentence"}',
            f"Company {s['ticker']}, as of {s['as_of']}. Question: {s['question']}\n"
            f"Prior notes: {json.dumps(prior)[:1500]}")
        try:
            plan = parse_json(reply)
        except ValueError:
            plan = {}
        # models write "us-gaap:Revenues" or "Revenues"; the fact store keys on the bare
        # concept. Core metrics are always included so quant has growth/margins to compute.
        asked = [str(m).split(":")[-1].strip() for m in plan.get("metrics") or []]
        plan = {"queries": plan.get("queries") or [s["question"]],
                "metrics": list(dict.fromkeys([*DEFAULT_METRICS, *asked])),
                "focus": plan.get("focus", "")}
        return {"plan": plan, "trace": _trace(s, "planner", t0, queries=len(plan["queries"]))}

    def human_plan(s: DeskState) -> dict:
        if not tools.human_in_loop:
            return {}
        answer = interrupt({"type": "approve_plan", "plan": s["plan"]})
        if isinstance(answer, dict) and answer.get("plan"):
            return {"plan": answer["plan"]}
        return {}

    def fundamentals(s: DeskState) -> dict:
        t0 = time.time()
        ev, series = dict(s.get("evidence", {})), {}
        if tools.facts:
            for concept in s["plan"]["metrics"]:
                rows = [r for r in tools.facts.series(s["ticker"], concept, as_of=s["as_of"],
                                                      form="10-K")
                        if r["fp"] == "FY" and r["start"]]
                # one value per fiscal period end, from the latest filing that reported it
                by_end = {r["end"]: r for r in rows}
                pts = [{"end": e, "value": r["value"], "accession": r["accession"]}
                       for e, r in sorted(by_end.items())][-4:]
                if pts:
                    series[concept] = pts
                    ev[f"xbrl:{concept}"] = {
                        "label": f"XBRL {concept} (10-K, filed <= {s['as_of']})",
                        "source": pts[-1]["accession"],
                        "text": "; ".join(f"FY ending {p['end']}: {p['value']:,.0f} USD"
                                          for p in pts)}
        return {"evidence": ev, "quant": {"_series": series},
                "trace": _trace(s, "fundamentals", t0, metrics=len(series))}

    def risk(s: DeskState) -> dict:
        t0 = time.time()
        ev = dict(s.get("evidence", {}))
        for q in s["plan"]["queries"]:
            for h in tools.search(q, as_of=s["as_of"], ticker=s["ticker"], k=5):
                c = h.chunk
                # the period lives in metadata, not the passage: without it the model guesses
                # which quarter "grew 40%" refers to, and the judge can't check the date
                period = f" for the period ending {c['period']}" if c.get("period") else ""
                ev[c["id"][:12]] = {"label": f"{c['form']}{period}, filed {c['filing_date']}, "
                                             f"Item {c['section']}", "source": c["source_url"],
                                    "text": c["text"]}
        if tools.graph:
            end = date.fromisoformat(s["as_of"])
            added, removed = tools.graph.changed_between(
                s["ticker"], "HAS_RISK", (end - timedelta(days=365)).isoformat(), end.isoformat())
            for e in added:
                ev[f"risk+:{e.id[:8]}"] = {"label": "risk factor added in the last year",
                                           "source": e.source_accession, "text": e.evidence}
            for e in removed:
                ev[f"risk-:{e.id[:8]}"] = {"label": "risk factor removed in the last year",
                                           "source": e.ended_by, "text": e.object}
            # entity changes from the knowledge graph (suppliers, customers, segments, ...)
            from ..graph.extract import RELATIONS

            for rel in RELATIONS.values():
                added, removed = tools.graph.changed_between(
                    s["ticker"], rel, (end - timedelta(days=400)).isoformat(), end.isoformat())
                for e, what in [(e, "newly named") for e in added] + \
                        [(e, "no longer named") for e in removed]:
                    ev[f"kg:{e.id[:8]}"] = {
                        "label": f"10-K knowledge graph: {e.object_type} {what} "
                                 f"({rel}, {e.valid_from if what == 'newly named' else e.valid_to})",
                        "source": e.source_accession if what == "newly named" else e.ended_by,
                        "text": f"{e.object}: {e.evidence}"}
        return {"evidence": ev, "trace": _trace(s, "risk", t0, evidence=len(ev))}

    def transcript(s: DeskState) -> dict:
        # earnings releases (8-K Ex. 99.1) stand in for call transcripts, which aren't freely
        # licensed; tone is counted in code (ingest/releases.py), not judged by the LLM
        t0 = time.time()
        if not tools.releases:
            return {"trace": _trace(s, "transcript", t0, status="no release source configured")}
        ev = dict(s.get("evidence", {}))
        rel = tools.releases(s["ticker"], s["as_of"])
        for r in rel:
            ev[f"release:{r['accession'][-8:]}"] = {
                "label": f"earnings release (8-K Ex. 99.1), filed {r['filed']}",
                "source": r["accession"],
                "text": f"Tone (lexicon count): {r['tone'].as_text()}.\n\n{r['text'][:2500]}"}
        return {"evidence": ev, "trace": _trace(s, "transcript", t0, releases=len(rel))}

    def quant(s: DeskState) -> dict:
        t0 = time.time()
        series = s.get("quant", {}).get("_series", {})
        q: dict[str, dict] = {}
        if series:
            res = sandbox.run(GROWTH_CODE, {"series": series, "revenue_keys": DEFAULT_METRICS[:2]},
                              mode=tools.sandbox_mode)
            q = res.result if res.ok else {"_error": {"message": res.error}}
        return {"quant": q, "trace": _trace(s, "quant", t0, results=len(q))}

    def _argue(stance: str) -> Callable[[DeskState], dict]:
        def node(s: DeskState) -> dict:
            t0 = time.time()
            reply = llm(
                f"You are the {stance} analyst. Make the strongest evidence-based {stance} case. "
                + CLAIMS_SPEC,
                f"Question: {s['question']} ({s['ticker']}, as of {s['as_of']})\n\n"
                f"Quant results: {json.dumps(s.get('quant', {}))}\n\nEvidence:\n"
                + _evidence_block(s.get("evidence", {})))
            try:
                claims = parse_json(reply).get("claims", [])
            except (ValueError, AttributeError):
                claims = []
            claims = [{"text": c.get("text", ""), "citations": list(c.get("citations", [])),
                       "stance": stance} for c in claims if isinstance(c, dict)]
            return {"claims": [*s.get("claims", []), *claims],
                    "trace": _trace(s, stance, t0, claims=len(claims))}
        return node

    def critic(s: DeskState) -> dict:
        t0 = time.time()
        # labels carry the report period, which may back a date in a claim
        ev = {k: f"({v['label']})\n{v['text']}" for k, v in s.get("evidence", {}).items()}
        vs = verify([Claim(**c) for c in s.get("claims", [])], ev, s.get("quant", {}),
                    tools.judge)
        verdicts = [{"claim": v.claim.__dict__, "ok": v.ok, "reasons": v.reasons} for v in vs]
        return {"verdicts": verdicts,
                "trace": _trace(s, "critic", t0, accepted=sum(v.ok for v in vs),
                                rejected=sum(not v.ok for v in vs))}

    def human_flags(s: DeskState) -> dict:
        flagged = [i for i, v in enumerate(s["verdicts"]) if not v["ok"]]
        if not tools.human_in_loop or not flagged:
            return {}
        answer = interrupt({"type": "review_flags", "flagged": [s["verdicts"][i] for i in flagged]})
        # the reviewer may only drop claims or confirm rejections, never force one through:
        # an override is recorded but a claim with an unverifiable number stays out
        keep = set((answer or {}).get("override", [])) if isinstance(answer, dict) else set()
        vs = [dict(v, overridden=(i in keep)) for i, v in enumerate(s["verdicts"])]
        return {"verdicts": vs}

    def writer(s: DeskState) -> dict:
        t0 = time.time()
        ev = s.get("evidence", {})
        ok = [v["claim"] for v in s.get("verdicts", []) if v["ok"]]
        cite_ids = sorted({c for cl in ok for c in cl["citations"]})
        num = {cid: i + 1 for i, cid in enumerate(cite_ids)}

        def render(cl: dict) -> str:
            refs = "".join(f"[^{num[c]}]" for c in cl["citations"])
            return f"- {cl['text']} {refs}"

        lines = [f"# {s['ticker']}: {s['question']}", "",
                 f"*As of {s['as_of']}. Research output, not investment advice.*", ""]
        for stance, title in (("bull", "Bull case"), ("bear", "Bear case"),
                              ("neutral", "Observations")):
            group = [render(c) for c in ok if c["stance"] == stance]
            if group:
                lines += [f"## {title}", "", *group, ""]
        rows = [(c["text"], c["stance"]) for c in ok if c["stance"] in ("bull", "bear")]
        if rows:
            lines += ["## Bull vs bear", "", "| Bull | Bear |", "|---|---|"]
            bulls = [t for t, st in rows if st == "bull"]
            bears = [t for t, st in rows if st == "bear"]
            for i in range(max(len(bulls), len(bears))):
                lines.append(f"| {bulls[i] if i < len(bulls) else ''} | "
                             f"{bears[i] if i < len(bears) else ''} |")
            lines.append("")
        rejected = [v for v in s.get("verdicts", []) if not v["ok"]]
        if rejected:
            lines += [f"*{len(rejected)} claim(s) were rejected by the verifier and omitted.*", ""]
        lines += ["## Sources", ""]
        for cid in cite_ids:
            if cid.startswith("quant:"):
                lines.append(f"[^{num[cid]}]: Computed in sandbox: "
                             f"{json.dumps(s.get('quant', {}).get(cid[6:], {}))}")
            else:
                e = ev[cid]
                lines.append(f"[^{num[cid]}]: {e['label']}: {e['source']}")
        report = "\n".join(lines)
        if tools.memory:
            tools.memory.save_note(s.get("user", "default"), s["ticker"], s["question"],
                                   s["as_of"], report, ok)
        return {"report": report, "trace": _trace(s, "writer", t0, claims=len(ok))}

    g = StateGraph(DeskState)
    for name, fn in (("planner", planner), ("human_plan", human_plan),
                     ("fundamentals", fundamentals), ("risk", risk), ("transcript", transcript),
                     ("quant", quant), ("bull", _argue("bull")), ("bear", _argue("bear")),
                     ("critic", critic), ("human_flags", human_flags), ("writer", writer)):
        g.add_node(name, fn)
    # sequential edges keep state merges simple; the specialists are independent and can be
    # fanned out with reducers once real LLM latency makes it worth it
    order = ["planner", "human_plan", "fundamentals", "risk", "transcript", "quant", "bull",
             "bear", "critic", "human_flags", "writer"]
    g.add_edge(START, order[0])
    for a, b in itertools.pairwise(order):
        g.add_edge(a, b)
    g.add_edge(order[-1], END)
    return g.compile(checkpointer=InMemorySaver())
