import json

from research_desk.graph.extract import extract, ground
from research_desk.graph.temporal import TemporalGraph, edges_from_snapshots
from research_desk.ingest.releases import tone

TEXT_2023 = ("We rely on Taiwan Semiconductor Manufacturing Company Limited to manufacture our "
             "wafers. Our Compute & Networking segment includes data center platforms. We compete "
             "with Advanced Micro Devices and Intel in GPUs.")
TEXT_2025 = ("We rely on Taiwan Semiconductor Manufacturing Company Limited to manufacture our "
             "wafers, and on Samsung Electronics for memory. We compete with Advanced Micro "
             "Devices in GPUs.")


def test_ground_drops_hallucinated_and_misquoted_entities():
    raw = [
        {"type": "Supplier", "name": "Taiwan Semiconductor Manufacturing Company Limited",
         "quote": "We rely on Taiwan Semiconductor Manufacturing Company Limited to manufacture"},
        {"type": "Supplier", "name": "Foxconn", "quote": "Foxconn assembles our boards"},  # invented
        {"type": "Competitor", "name": "Intel",
         "quote": "We compete with Advanced Micro Devices and Intel"},
        {"type": "Competitor", "name": "Qualcomm",                                      # not in quote
         "quote": "We compete with Advanced Micro Devices and Intel"},
        {"type": "Mascot", "name": "Intel", "quote": "Advanced Micro Devices and Intel in GPUs"},
    ]
    assert sorted(e.name for e in ground(raw, TEXT_2023)) == [
        "Intel", "Taiwan Semiconductor Manufacturing Company Limited"]


def test_extract_and_temporal_supplier_change():
    def llm(text):
        if "Samsung" in text:
            return [{"type": "Supplier", "name": "Samsung Electronics",
                     "quote": "on Samsung Electronics for memory"},
                    {"type": "Competitor", "name": "Advanced Micro Devices",
                     "quote": "We compete with Advanced Micro Devices in GPUs"}]
        return [{"type": "Competitor", "name": "Intel",
                 "quote": "We compete with Advanced Micro Devices and Intel in GPUs"},
                {"type": "Competitor", "name": "Advanced Micro Devices",
                 "quote": "We compete with Advanced Micro Devices and Intel in GPUs"}]

    snaps = {"NAMES_SUPPLIER": [], "NAMES_COMPETITOR": []}
    for day, acc, text in (("2023-02-24", "a1", TEXT_2023), ("2025-02-26", "a2", TEXT_2025)):
        ents = extract(text, lambda s, u: json.dumps({"entities": llm(u)}))
        snaps["NAMES_SUPPLIER"].append((day, acc, {e.name: e.quote for e in ents if e.type == "Supplier"}))
        snaps["NAMES_COMPETITOR"].append((day, acc, {e.name: e.quote for e in ents if e.type == "Competitor"}))
    g = TemporalGraph()
    for rel, typ in (("NAMES_SUPPLIER", "Supplier"), ("NAMES_COMPETITOR", "Competitor")):
        g.upsert(edges_from_snapshots("NVDA", rel, typ, snaps[rel]))
    added, removed = g.changed_between("NVDA", "NAMES_COMPETITOR", "2024-01-01", "2025-12-31")
    assert [e.object for e in removed] == ["Intel"] and added == []
    added, _ = g.changed_between("NVDA", "NAMES_SUPPLIER", "2024-01-01", "2025-12-31")
    assert [e.object for e in added] == ["Samsung Electronics"]


def test_tone_counts():
    t = tone("Revenue grew to a record. Margins declined on headwinds. We expect growth may slow.")
    assert t.positive_per_1k > 0 and t.negative_per_1k > 0 and t.guidance_sentences == 1
    assert -1 <= t.net_tone <= 1
