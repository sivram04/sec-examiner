from fastapi.testclient import TestClient

from research_desk.api import Backend, create_app
from research_desk.graph.temporal import TemporalGraph, edges_from_snapshots
from research_desk.retrieval.index import HybridIndex
from research_desk.retrieval.models import HashEmbedder

from .test_agents import CHUNK, ScriptedLLM


def make_client(tmp_path):
    idx = HybridIndex(HashEmbedder())
    idx.add([CHUNK])
    be = Backend(data=tmp_path, index=idx, llm=ScriptedLLM([]), fetch_releases=False)
    g = TemporalGraph(tmp_path / "graph.db")
    g.upsert(edges_from_snapshots("AAPL", "HAS_RISK", "Risk", [
        ("2024-11-01", "a1", {"old risk": "e"}), ("2025-10-31", "a2", {"tariff risk": "e2"})]))
    return TestClient(create_app(be))


def test_search_and_as_of(tmp_path):
    c = make_client(tmp_path)
    r = c.get("/api/search", params={"q": "tariffs", "ticker": "aapl", "method": "hybrid"})
    assert r.status_code == 200 and r.json()["hits"][0]["url"] == CHUNK["source_url"]
    r = c.get("/api/search", params={"q": "tariffs", "as_of": "2025-01-01", "method": "hybrid"})
    assert r.json()["hits"] == []
    assert c.get("/api/search", params={"q": "x", "method": "nope"}).status_code == 400


def test_what_changed(tmp_path):
    r = make_client(tmp_path).get("/api/risks/AAPL",
                                  params={"start": "2025-01-01", "end": "2025-12-31"})
    body = r.json()
    assert [x["risk"] for x in body["added"]] == ["tariff risk"]
    assert [x["risk"] for x in body["removed"]] == ["old risk"]


def test_research_hitl_roundtrip_and_report_library(tmp_path):
    c = make_client(tmp_path)
    r = c.post("/api/research", json={"ticker": "AAPL", "question": "Margins?",
                                      "as_of": "2025-12-31"}).json()
    assert r["status"] == "needs_input" and r["interrupt"]["type"] == "approve_plan"
    done = r
    for _ in range(3):  # plan approval, then at most the flag review
        if done["status"] != "needs_input":
            break
        done = c.post(f"/api/research/{r['thread']}/resume", json={"approve": True}).json()
    assert done["status"] == "done" and done["report"].startswith("# AAPL")
    lib = c.get("/api/reports").json()
    assert lib[0]["question"] == "Margins?"
    assert c.get(f"/api/reports/{lib[0]['id']}").json()["report"] == done["report"]


def test_index_page(tmp_path):
    r = make_client(tmp_path).get("/")
    assert r.status_code == 200 and "AI Research Desk" in r.text
