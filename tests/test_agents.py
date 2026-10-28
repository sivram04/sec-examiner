import json

import pytest
from langgraph.types import Command

from research_desk.agents import sandbox
from research_desk.agents.critic import Claim, numbers, verify
from research_desk.agents.desk import Tools, build_desk, parse_json
from research_desk.agents.memory import Memory
from research_desk.ingest.facts import FactStore, flatten
from research_desk.retrieval.index import Filters, HybridIndex
from research_desk.retrieval.models import HashEmbedder

CHUNK = {"id": "c" * 40, "ticker": "AAPL", "cik": 1, "form": "10-K", "accession": "a2",
         "filing_date": "2025-10-31", "period": None, "section": "1A",
         "section_title": "Risk Factors", "kind": "text", "ordinal": 0,
         "text": "New tariffs on imported components could raise costs and reduce gross margin.",
         "source_url": "https://www.sec.gov/x.htm"}
FACTS = {"facts": {"us-gaap": {
    "Revenues": {"units": {"USD": [
        {"start": "2023-10-01", "end": "2024-09-28", "val": 391035e6, "fy": 2024, "fp": "FY",
         "form": "10-K", "filed": "2024-11-01", "accn": "a1"},
        {"start": "2024-09-29", "end": "2025-09-27", "val": 416161e6, "fy": 2025, "fp": "FY",
         "form": "10-K", "filed": "2025-10-31", "accn": "a2"}]}},
    "NetIncomeLoss": {"units": {"USD": [
        {"start": "2024-09-29", "end": "2025-09-27", "val": 112010e6, "fy": 2025, "fp": "FY",
         "form": "10-K", "filed": "2025-10-31", "accn": "a2"},
        {"start": "2023-10-01", "end": "2024-09-28", "val": 93736e6, "fy": 2024, "fp": "FY",
         "form": "10-K", "filed": "2024-11-01", "accn": "a1"}]}}}}}


def test_sandbox_computes_and_isolates():
    r = sandbox.run("result = {'g': round((inputs['b'] / inputs['a'] - 1) * 100, 1)}",
                    {"a": 391035, "b": 416161})
    assert r.ok and r.result == {"g": 6.4}
    assert not sandbox.run("raise ValueError('boom')").ok
    assert "timeout" in sandbox.run("while True: pass", timeout=1).error


def test_numbers_ignores_years_and_normalizes():
    assert numbers("Revenue rose 6.4% to $416,161 million in 2025, up 1.50 points") == {
        "6.4", "416161", "1.5"}


def test_critic_matches_scaled_amounts_both_ways():
    ev = {"c1": "The Commission imposed a fine of €500 million.", "c2": "Fine: 500,000,000 EUR."}
    v = verify([Claim("Apple was fined 500,000,000 EUR.", ["c1"]),
                Claim("Apple was fined EUR 500 million.", ["c2"]),
                Claim("Apple was fined EUR 600 million.", ["c1"])], ev, {})
    assert [x.ok for x in v] == [True, True, False]


def test_critic_rejects_uncited_and_invented_numbers():
    ev = {"c1": "Net sales were $416,161 million."}
    quant = {"Revenues": {"growth_pct": 6.4}}
    v = verify([Claim("Net sales were $416,161 million.", ["c1"]),
                Claim("Revenue grew 6.4%.", ["quant:Revenues"]),
                Claim("Revenue grew 9.9%.", ["quant:Revenues"]),          # seeded false number
                Claim("Margins will expand.", []),                         # no citation
                Claim("Sales hit $416,161 million.", ["c404"])], ev, quant)  # unknown source
    assert [x.ok for x in v] == [True, True, False, False, False]
    assert "9.9" in v[2].reasons[0]


class ScriptedLLM:
    """Returns canned JSON per role so the whole graph runs without a model."""
    def __init__(self, bear_claims):
        self.bear_claims, self.calls = bear_claims, []

    def __call__(self, system, user):
        self.calls.append(system[:30])
        if "plan" in system:
            return json.dumps({"queries": ["tariffs gross margin"],
                               "metrics": ["us-gaap:Revenues", "NetIncomeLoss"],
                               "focus": "margins"})
        if "bull" in system:
            return "```json\n" + json.dumps({"claims": [
                {"text": "Revenue grew 6.4% year over year.", "citations": ["quant:Revenues"]},
                {"text": "Net margin was 26.9%.", "citations": ["quant:NetIncomeLoss"]}]}) + "\n```"
        return json.dumps({"claims": self.bear_claims})


@pytest.fixture
def tools(tmp_path):
    idx = HybridIndex(HashEmbedder())
    idx.add([CHUNK])
    facts = FactStore(tmp_path / "f.db")
    facts.upsert(flatten("AAPL", FACTS))
    return Tools(search=lambda q, as_of, ticker, k: idx.search(
        q, Filters(as_of=__import__("datetime").date.fromisoformat(as_of), tickers=(ticker,)),
        k=k, method="hybrid"), facts=facts, memory=Memory(), human_in_loop=False)


def test_desk_end_to_end_rejects_seeded_false_claim(tools):
    bear = [{"text": "Tariffs could raise costs and reduce gross margin.",
             "citations": ["c" * 12]},
            {"text": "Gross margin fell 12.5 points.", "citations": ["c" * 12]}]  # invented
    desk = build_desk(ScriptedLLM(bear), tools)
    out = desk.invoke({"question": "Is margin at risk?", "ticker": "AAPL",
                       "as_of": "2025-12-31", "user": "u"},
                      {"configurable": {"thread_id": "t1"}})
    assert out["quant"]["Revenues"]["growth_pct"] == 6.4                     # sandbox, not LLM
    assert out["quant"]["NetIncomeLoss"]["margin_pct"] == 26.9
    ok = {v["claim"]["text"]: v["ok"] for v in out["verdicts"]}
    assert ok == {"Revenue grew 6.4% year over year.": True, "Net margin was 26.9%.": True,
                  "Tariffs could raise costs and reduce gross margin.": True,
                  "Gross margin fell 12.5 points.": False}
    assert "12.5" not in out["report"] and "6.4%" in out["report"]
    assert "[^1]" in out["report"] and "https://www.sec.gov/x.htm" in out["report"]
    assert "1 claim(s) were rejected" in out["report"]
    assert next(t["agent"] for t in out["trace"]) == "planner"
    assert tools.memory.notes("u", "AAPL")[0]["question"] == "Is margin at risk?"


def test_point_in_time_facts_in_desk(tools):
    desk = build_desk(ScriptedLLM([]), tools)
    out = desk.invoke({"question": "q", "ticker": "AAPL", "as_of": "2025-01-01"},
                      {"configurable": {"thread_id": "t2"}})
    # only FY2024 is known on 2025-01-01: one point, so no growth can be computed
    assert "Revenues" not in out["quant"]
    assert "2025-09-27" not in json.dumps(out["evidence"])


def test_human_in_the_loop_plan_approval(tools):
    tools.human_in_loop = True
    desk = build_desk(ScriptedLLM([]), tools)
    cfg = {"configurable": {"thread_id": "t3"}}
    first = desk.invoke({"question": "q", "ticker": "AAPL", "as_of": "2025-12-31"}, cfg)
    assert first["__interrupt__"][0].value["type"] == "approve_plan"
    edited = {"queries": ["tariffs"], "metrics": ["Revenues"], "focus": "edited"}
    out = desk.invoke(Command(resume={"plan": edited}), cfg)
    assert out["plan"]["focus"] == "edited" and "NetIncomeLoss" not in out["quant"]


def test_parse_json_tolerates_prose():
    assert parse_json('Sure! {"a": 1} hope that helps') == {"a": 1}
