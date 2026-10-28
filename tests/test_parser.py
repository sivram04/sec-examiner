from datetime import date

from research_desk.edgar.chunker import chunk_filing, split_text
from research_desk.edgar.client import Filing
from research_desk.edgar.parser import parse_sections

TOC = """
<table><tr><td>Item 1.</td><td>Business</td><td>3</td></tr>
<tr><td>Item 1A.</td><td>Risk Factors</td><td>9</td></tr></table>
<p>Item 1. Business</p><p>Item 1A. Risk Factors</p><p>Item 7. MD&amp;A</p>
"""

TENK = f"""<html><body>{TOC}
<div><span>Item 1.</span> <span>Business</span></div>
<p>The Company designs smartphones.</p>
<div>Item 1A. Risk Factors</div>
<p>Supply chain disruption could hurt results.</p>
<p>Competition is intense.</p>
<div>Item 7. Management's Discussion and Analysis</div>
<p>Net sales increased.</p>
<table><tr><td>Net sales</td><td>$</td><td>391,035</td></tr>
<tr><td>Cost of sales</td><td>$</td><td>210,352</td></tr></table>
</body></html>"""

TENQ = """<html><body>
<p>PART I — FINANCIAL INFORMATION</p>
<p>Item 2. Management's Discussion and Analysis</p><p>Revenue grew.</p>
<p>PART II — OTHER INFORMATION</p>
<p>Item 1A. Risk Factors</p><p>No material changes.</p>
</body></html>"""


def test_10k_sections_skip_table_of_contents():
    secs = {s.item: s for s in parse_sections(TENK)}
    assert list(secs) == ["1", "1A", "7"]
    assert "smartphones" in secs["1"].text
    assert "Competition is intense." in secs["1A"].text
    assert "Supply chain" in secs["1A"].text


def test_tables_attached_to_section_and_clean():
    secs = {s.item: s for s in parse_sections(TENK)}
    assert secs["7"].tables == ["Net sales | 391,035\nCost of sales | 210,352"]


def test_10q_items_keyed_by_part():
    secs = {s.item: s for s in parse_sections(TENQ, form="10-Q")}
    assert set(secs) == {"I-2", "II-1A"}
    assert secs["II-1A"].text == "No material changes."


RUNNING = """<html><body>
<p>PART I</p><p>Item 1</p><p>ITEM 1. FINANCIAL STATEMENTS</p><p>Page one.</p>
<p>PART I</p><p>Item 1</p><p>Page two.</p>
<p>PART I</p><p>Item 2</p><p>ITEM 2. MD&amp;A</p><p>Growth.</p>
</body></html>"""


def test_running_page_headers_dont_split_sections():
    secs = {s.item: s for s in parse_sections(RUNNING, form="10-Q")}
    assert secs["I-1"].text == "ITEM 1. FINANCIAL STATEMENTS\n\nPage one.\n\nPage two."
    assert secs["I-2"].text == "ITEM 2. MD&A\n\nGrowth."


def test_text_before_first_item_kept_as_other():
    html = ("<html><body>" + "<p>Consolidated balance sheet discussion. </p>" * 200
            + "<p>PART II</p><p>Item 1A. Risk Factors</p><p>None.</p></body></html>")
    secs = {s.item: s for s in parse_sections(html, form="10-Q")}
    assert set(secs) == {"II-1A", "other"}
    assert "balance sheet" in secs["other"].text


def test_split_text_respects_max_and_overlaps():
    text = "\n\n".join(f"Paragraph {i} " + "word " * 80 for i in range(10))
    chunks = split_text(text, max_chars=1000, overlap=100)
    assert len(chunks) > 1
    assert all(len(c) <= 1100 for c in chunks)
    assert chunks[1].split("\n\n")[0] in chunks[0]


def test_split_long_paragraph():
    chunks = split_text("This is a sentence. " * 300, max_chars=500, overlap=0)
    assert all(len(c) <= 500 for c in chunks)


def test_chunk_metadata():
    f = Filing(320193, "10-K", "0000320193-24-000123", date(2024, 11, 1),
               date(2024, 9, 28), "aapl-20240928.htm")
    chunks = chunk_filing(f, "aapl", parse_sections(TENK))
    c = next(c for c in chunks if c.section == "7" and c.kind == "table")
    assert c.ticker == "AAPL" and c.period == date(2024, 9, 28)
    assert c.source_url == f.url
    assert len({c.id for c in chunks}) == len(chunks)
