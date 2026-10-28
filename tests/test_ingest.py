from datetime import date

from research_desk.edgar.client import Filing
from research_desk.ingest.bus import PARSED, RAW_DOCS, MemoryBus
from research_desk.ingest.facts import FactStore, flatten
from research_desk.ingest.pipeline import index_stage, load_corpus, parse_stage
from research_desk.ingest.watcher import Watcher, filing_message, parse_feed

FEED = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>10-Q - APPLE INC (0000320193) (Filer)</title>
<category scheme="https://www.sec.gov/" label="form type" term="10-Q"/>
<id>urn:tag:sec.gov,2008:accession-number=0000320193-26-000020</id></entry>
<entry><title>10-Q - SOME SMALLCAP (0000999999) (Filer)</title>
<category term="10-Q"/>
<id>urn:tag:sec.gov,2008:accession-number=0000999999-26-000001</id></entry>
</feed>"""

HTML = """<html><body><p>PART I</p><p>Item 2. MD&amp;A</p><p>Sales rose.</p>
<p>PART II</p><p>Item 1A. Risk Factors</p><p>Tariffs may raise costs.</p></body></html>"""

F = Filing(320193, "10-Q", "0000320193-26-000020", date(2026, 7, 31), date(2026, 6, 27),
           "aapl-20260627.htm")


class FakeEdgar:
    class http:
        @staticmethod
        def get(url):
            class R:
                text = FEED
                def raise_for_status(self):
                    return self
            return R()

    def cik(self, t):
        return {"AAPL": 320193}[t]

    def filings(self, t, forms=None, as_of=None):
        return [F]

    def document(self, f):
        return HTML


def test_parse_feed():
    assert parse_feed(FEED) == [(320193, "10-Q", "0000320193-26-000020"),
                                (999999, "10-Q", "0000999999-26-000001")]


def test_watcher_queues_only_covered_unseen(tmp_path):
    bus = MemoryBus()
    w = Watcher(FakeEdgar(), bus, ["AAPL", "NOPE"], {"10-Q"}, tmp_path / "seen.json")
    assert w.poll_once() == ["0000320193-26-000020"]
    assert len(bus.topics[RAW_DOCS]) == 1
    # state survives restart: the same filing is not queued twice
    w2 = Watcher(FakeEdgar(), bus, ["AAPL"], {"10-Q"}, tmp_path / "seen.json")
    assert w2.poll_once() == []


def test_parse_and_index_stages(tmp_path):
    bus = MemoryBus()
    bus.publish(RAW_DOCS, F.accession, filing_message(F, "AAPL"))
    assert parse_stage(FakeEdgar(), bus, tmp_path) == 1
    corpus = load_corpus(tmp_path)
    assert {c["section"] for c in corpus} == {"II-1A", "I-2"}
    assert all(c["ticker"] == "AAPL" and c["filing_date"] == "2026-07-31" for c in corpus)
    got: list[dict] = []
    assert index_stage(bus, got.extend) == len(corpus) == len(got)
    assert not bus.topics[PARSED]


def test_unsectioned_filing_kept_whole(tmp_path):
    class NoItems(FakeEdgar):
        def document(self, f):
            return "<html><body><p>See cross-reference index on page 300.</p></body></html>"

    bus = MemoryBus()
    bus.publish(RAW_DOCS, F.accession, filing_message(F, "AAPL"))
    parse_stage(NoItems(), bus, tmp_path)
    assert [c["section"] for c in load_corpus(tmp_path)] == ["body"]


def test_facts_point_in_time(tmp_path):
    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        {"end": "2024-09-28", "val": 391035e6, "fy": 2024, "fp": "FY", "form": "10-K",
         "filed": "2024-11-01", "accn": "a1"},
        {"end": "2025-09-27", "val": 416161e6, "fy": 2025, "fp": "FY", "form": "10-K",
         "filed": "2025-10-31", "accn": "a2"}]}}}}}
    store = FactStore(tmp_path / "f.db")
    store.upsert(flatten("aapl", facts))
    assert len(store.series("AAPL", "Revenues")) == 2
    pit = store.series("AAPL", "Revenues", as_of="2025-01-01")
    assert [r["value"] for r in pit] == [391035e6]
