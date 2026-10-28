import hashlib
from datetime import date

import pytest

from research_desk.retrieval.evaluate import evaluate, score_ranking
from research_desk.retrieval.index import Filters, HybridIndex, rrf
from research_desk.retrieval.models import HashEmbedder


def chunk(ticker, filed, section, text):
    cid = hashlib.sha1(f"{ticker}{filed}{text}".encode()).hexdigest()
    return {"id": cid, "ticker": ticker, "cik": 1, "form": "10-K", "accession": "x",
            "filing_date": filed, "period": None, "section": section,
            "section_title": "Risk Factors", "kind": "text", "ordinal": 0, "text": text,
            "source_url": "u"}


CORPUS = [
    chunk("AAPL", "2023-11-03", "1A", "Supply chain disruption in China could hurt margins."),
    chunk("AAPL", "2025-10-31", "1A", "New tariffs on imported components could hurt margins."),
    chunk("AAPL", "2025-10-31", "7", "Net sales of services grew on App Store strength."),
    chunk("MSFT", "2025-07-30", "1A", "Tariffs and trade restrictions may affect cloud hardware."),
]


class FakeReranker:
    """Prefers passages mentioning 'services' to prove reranking reorders results."""
    def score(self, query, texts):
        return [1.0 if "services" in t else 0.0 for t in texts]


@pytest.fixture
def idx():
    i = HybridIndex(HashEmbedder())
    i.add(CORPUS)
    return i


def test_rrf_fuses_rankings():
    out = rrf({"a": ["x", "y"], "b": ["y", "z"]})
    assert out[0][0] == "y"
    assert out[0][2] == {"a": 2, "b": 1}


@pytest.mark.parametrize("method", ["bm25", "dense", "hybrid"])
def test_as_of_never_leaks_future(idx, method):
    hits = idx.search("tariffs hurt margins", Filters(as_of=date(2024, 1, 1)), method=method)
    assert hits and all(h.chunk["filing_date"] <= "2024-01-01" for h in hits)


def test_ticker_and_section_filters(idx):
    hits = idx.search("tariffs", Filters(tickers=("MSFT",)), method="hybrid")
    assert {h.chunk["ticker"] for h in hits} == {"MSFT"}
    hits = idx.search("sales", Filters(sections=("7",)), method="hybrid")
    assert {h.chunk["section"] for h in hits} == {"7"}


def test_hybrid_finds_keyword_match(idx):
    top = idx.search("tariffs imported components", Filters(tickers=("AAPL",)), method="hybrid")
    assert "tariffs" in top[0].chunk["text"]


def test_rerank_reorders(idx):
    idx.reranker = FakeReranker()
    top = idx.search("margins sales", Filters(tickers=("AAPL",)), method="hybrid_rerank")
    assert "services" in top[0].chunk["text"]


def test_add_is_idempotent(idx):
    idx.add(CORPUS)
    assert len(idx.chunks) == len(CORPUS)
    assert idx.qdrant.count("chunks").count == len(CORPUS)


def test_metrics():
    assert score_ranking([False, True, False], 10) == {"recall": 1.0, "mrr": 0.5,
                                                       "ndcg": pytest.approx(1 / 1.585, 1e-3)}
    assert score_ranking([False] * 3, 10)["recall"] == 0.0


def test_evaluate_runs_all_methods(idx):
    golden = [{"id": "q1", "question": "tariffs components", "ticker": "AAPL",
               "as_of": "2025-12-31", "relevant": ["new tariffs"]}]
    res = evaluate(idx, golden, methods=("bm25", "dense", "hybrid"))
    assert res["bm25"]["recall"] == 1.0 and set(res) == {"bm25", "dense", "hybrid"}
