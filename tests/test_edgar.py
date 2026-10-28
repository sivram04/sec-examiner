from datetime import date

from research_desk.edgar.client import parse_filings

SUBS = {"filings": {"recent": {
    "form": ["10-Q", "8-K", "10-K"],
    "accessionNumber": ["0000320193-24-000081", "0000320193-24-000070", "0000320193-23-000106"],
    "filingDate": ["2024-08-02", "2024-05-02", "2023-11-03"],
    "reportDate": ["2024-06-29", "", "2023-09-30"],
    "primaryDocument": ["aapl-20240629.htm", "x8k.htm", "aapl-20230930.htm"],
}}}


def test_form_filter():
    out = parse_filings(320193, SUBS, forms={"10-K"})
    assert [f.form for f in out] == ["10-K"]
    assert out[0].url.endswith("/320193/000032019323000106/aapl-20230930.htm")


def test_as_of_excludes_future_filings():
    out = parse_filings(320193, SUBS, as_of=date(2024, 6, 1))
    assert all(f.filing_date <= date(2024, 6, 1) for f in out)
    assert len(out) == 2


def test_decode_handles_cp1252_and_utf8():
    from research_desk.edgar.client import decode

    assert decode("Apple’s".encode()) == "Apple’s"
    assert decode("Apple’s".encode("cp1252")) == "Apple’s"


def test_empty_report_date():
    out = parse_filings(320193, SUBS, forms={"8-K"})
    assert out[0].report_date is None
