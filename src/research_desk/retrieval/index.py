"""Hybrid index: BM25 (keyword) + Qdrant (dense) over the same chunks, with metadata filters.

Every search takes as_of and never returns a chunk filed after it (point-in-time correctness).
"""
import math
import re
import warnings
from dataclasses import dataclass
from datetime import date

import numpy as np
from qdrant_client import QdrantClient, models
from rank_bm25 import BM25Okapi

from .models import Embedder, Reranker

COLLECTION = "chunks"
TOKEN_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
STOP = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "in", "is", "it", "its", "of", "on", "or", "that", "the", "this", "to", "was", "were", "will", "with", "we", "our"])


class LuceneBM25(BM25Okapi):
    """BM25 with Lucene's IDF, log(1 + (N - n + 0.5) / (n + 0.5)).

    Okapi's IDF hits zero for terms in half the documents, which zeroes out common
    finance terms ("tariffs", "revenue") inside a single company's filings.
    """

    def _calc_idf(self, nd):
        for word, freq in nd.items():
            self.idf[word] = math.log(1 + (self.corpus_size - freq + 0.5) / (freq + 0.5))


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOP]


@dataclass(frozen=True)
class Filters:
    as_of: date | None = None
    tickers: tuple[str, ...] = ()
    sections: tuple[str, ...] = ()
    forms: tuple[str, ...] = ()

    def ok(self, c: dict) -> bool:
        return ((self.as_of is None or c["filing_date"] <= self.as_of.isoformat())
                and (not self.tickers or c["ticker"] in self.tickers)
                and (not self.sections or c["section"] in self.sections)
                and (not self.forms or c["form"] in self.forms))

    def qdrant(self) -> models.Filter | None:
        must: list = []
        if self.as_of:
            must.append(models.FieldCondition(key="filing_day", range=models.Range(
                lte=self.as_of.toordinal())))
        for key, vals in (("ticker", self.tickers), ("section", self.sections),
                          ("form", self.forms)):
            if vals:
                must.append(models.FieldCondition(key=key, match=models.MatchAny(any=list(vals))))
        return models.Filter(must=must) if must else None


@dataclass
class Hit:
    chunk: dict
    score: float
    ranks: dict[str, int]


def rrf(rankings: dict[str, list[str]], k: int = 60) -> list[tuple[str, float, dict]]:
    """Reciprocal rank fusion: sum of 1/(k + rank) across methods."""
    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}
    for method, ids in rankings.items():
        for r, cid in enumerate(ids, 1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + r)
            ranks.setdefault(cid, {})[method] = r
    return [(cid, s, ranks[cid]) for cid, s in sorted(scores.items(), key=lambda x: -x[1])]


class HybridIndex:
    def __init__(self, embedder: Embedder, reranker: Reranker | None = None,
                 qdrant: QdrantClient | None = None):
        self.embedder, self.reranker = embedder, reranker
        self.qdrant = qdrant or QdrantClient(":memory:")
        self.chunks: dict[str, dict] = {}
        self._ids: list[str] = []
        self._bm25: BM25Okapi | None = None
        if not self.qdrant.collection_exists(COLLECTION):
            self.qdrant.create_collection(COLLECTION, vectors_config=models.VectorParams(
                size=embedder.dim, distance=models.Distance.COSINE))
            with warnings.catch_warnings():
                # embedded Qdrant ignores payload indexes (and says so); the server uses them
                warnings.simplefilter("ignore", UserWarning)
                for key in ("ticker", "section", "form"):
                    self.qdrant.create_payload_index(COLLECTION, key, "keyword")
                self.qdrant.create_payload_index(COLLECTION, "filing_day", "integer")

    @staticmethod
    def _point_id(cid: str) -> str:
        # Qdrant ids must be UUIDs or ints; the sha1 chunk id maps to a stable UUID
        return f"{cid[:8]}-{cid[8:12]}-{cid[12:16]}-{cid[16:20]}-{cid[20:32]}"

    def add(self, chunks: list[dict]) -> None:
        new = [c for c in chunks if c["id"] not in self.chunks]
        if not new:
            return
        # a persistent Qdrant may already hold vectors from an earlier run: don't re-embed them
        stored = {str(p.id) for p in self.qdrant.retrieve(
            COLLECTION, ids=[self._point_id(c["id"]) for c in new], with_payload=False)}
        for c in new:
            self.chunks[c["id"]] = c
        self._bm25 = None  # rebuilt lazily on next keyword search
        new = [c for c in new if self._point_id(c["id"]) not in stored]
        if not new:
            return
        vecs = self.embedder.embed_docs([self._doc_text(c) for c in new])
        self.qdrant.upsert(COLLECTION, points=[
            models.PointStruct(id=self._point_id(c["id"]), vector=v.tolist(), payload={
                "chunk_id": c["id"], "ticker": c["ticker"], "section": c["section"],
                "form": c["form"],
                "filing_day": date.fromisoformat(c["filing_date"]).toordinal()})
            for c, v in zip(new, vecs, strict=True)])

    @staticmethod
    def _doc_text(c: dict) -> str:
        # a little context helps both BM25 and embeddings place the passage
        return f"{c['ticker']} {c['form']} {c['section_title']}\n{c['text']}"

    def _keyword(self, query: str, f: Filters, k: int) -> list[str]:
        if self._bm25 is None:
            self._ids = list(self.chunks)
            self._bm25 = LuceneBM25([tokenize(self._doc_text(self.chunks[i])) for i in self._ids])
        scores = self._bm25.get_scores(tokenize(query))
        out = []
        for i in np.argsort(-scores):
            if scores[i] <= 0 or len(out) >= k:
                break
            if f.ok(self.chunks[self._ids[i]]):
                out.append(self._ids[i])
        return out

    def _dense(self, query: str, f: Filters, k: int) -> list[str]:
        res = self.qdrant.query_points(COLLECTION, query=self.embedder.embed_query(query).tolist(),
                                       query_filter=f.qdrant(), limit=k, with_payload=True)
        return [p.payload["chunk_id"] for p in res.points]

    def search(self, query: str, filters: Filters | None = None, k: int = 10,
               method: str = "hybrid_rerank", pool: int = 50, rerank_top: int = 30) -> list[Hit]:
        """method: bm25 | dense | hybrid | hybrid_rerank."""
        filters = filters or Filters()
        rankings: dict[str, list[str]] = {}
        if method in ("bm25", "hybrid", "hybrid_rerank"):
            rankings["bm25"] = self._keyword(query, filters, pool)
        if method in ("dense", "hybrid", "hybrid_rerank"):
            rankings["dense"] = self._dense(query, filters, pool)
        fused = rrf(rankings)
        hits = [Hit(self.chunks[cid], s, r) for cid, s, r in fused]
        if method == "hybrid_rerank" and self.reranker and hits:
            top = hits[:rerank_top]
            scores = self.reranker.score(query, [h.chunk["text"] for h in top])
            hits = [Hit(h.chunk, s, {**h.ranks, "rerank": 0}) for h, s in zip(top, scores,
                                                                              strict=True)]
            hits.sort(key=lambda h: -h.score)
        hits = hits[:k]
        # belt and braces: the as_of guarantee is checked on the final list too
        assert all(filters.ok(h.chunk) for h in hits), "filter leak"
        return hits
