"""SEC Examiner as an MCP server: any MCP client (Claude, Cursor, VS Code...) can call it as tools.

Run over stdio:   sec-examiner-mcp        (or: python -m research_desk.examiner.mcp_server)

Same guarantees as the web app: stateless, drafts are read in memory only and never stored or
used for training, and the model answering is the judge-approved champion.
"""
from functools import cache
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .embed import DESCRIPTIONS
from .gaps import NAMES
from .service import LABELS, ExaminerService

# resolve data from the project, not the caller's working directory (MCP clients launch anywhere)
ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data" / "examiner"

mcp = MCPServer(
    "sec-examiner",
    instructions=(
        "Predicts which topics SEC staff are likely to raise in comment letters on a 10-K, 10-Q "
        "or 20-F, and which expected disclosures appear to be missing. Use examine_company for a "
        "public ticker, examine_draft for unfiled text. Results are statistical, graded against "
        "real SEC letters (see examiner_status for accuracy); not legal or accounting advice."),
)


@cache
def _service() -> ExaminerService:
    return ExaminerService(DATA / "models", DATA / "letters.jsonl")


def _compact(r: dict) -> dict:
    """Keep what an assistant needs to answer; drop UI-only fields."""
    return {
        "model": r["model"],
        "filing": r["filing"],
        "note": r.get("note"),
        "likely_comment_topics": [
            {"rank": i + 1, "topic": p["topic"], "label": p["label"],
             "likelihood": "high" if p["score"] >= 0.75 else "medium" if p["score"] >= 0.5
             else "lower",
             "score": p["score"], "share_from_filing_text": round(
                 p["from_filing"] / ((p["from_filing"] + p["from_history"]) or 1), 2),
             "expected_disclosures_not_found": p["missing"]}
            for i, p in enumerate(r["predictions"])],
        "past_sec_letters": r["past_letters"],
        "sections_read": r["sections_read"],
    }


@mcp.tool()
def examine_company(ticker: str) -> dict:
    """Examine a public company's latest 10-K, 10-Q or 20-F from SEC EDGAR.

    Returns the 5 topics SEC staff are most likely to comment on (with likelihood and how much
    came from the filing's text vs. past SEC letters), expected disclosures that could not be
    found, and the company's recent SEC comment letters. Example tickers: TSLA, BABA, BRK.B.
    """
    try:
        return _compact(_service().examine_ticker(ticker))
    except LookupError as e:          # ToolError reaches the client as an isError result
        raise ToolError(str(e)) from e


@mcp.tool()
def examine_draft(text: str, sic: str = "", form: str = "10-K") -> dict:
    """Examine unfiled disclosure text (MD&A, notes, or a whole draft) before it is filed.

    sic: optional 4-digit industry code (e.g. 7372 software, 6022 banks) to use industry history.
    The text is processed in memory only; it is never stored, logged or used for training.
    """
    try:
        return _compact(_service().examine_draft(text, sic=sic, form=form))
    except (ValueError, LookupError) as e:
        raise ToolError(str(e)) from e


@mcp.tool()
def explain_topic(topic: str) -> dict:
    """What an SEC comment topic covers and which disclosures staff usually expect with it.

    topic: a topic id such as non_gaap, impairment, segments, cybersecurity (see list_topics).
    """
    if topic not in LABELS:
        raise ToolError(f"unknown topic {topic!r}; valid topics: {', '.join(sorted(LABELS))}")
    recall = {t["topic"]: t for t in _service().status()["topic_recall"]}.get(topic)
    return {"topic": topic, "label": LABELS[topic], "covers": DESCRIPTIONS.get(topic, ""),
            "expected_disclosures": NAMES.get(topic, []),
            "model_recall_on_holdout": recall and {"recall": recall["recall"], "n": recall["n"]}}


@mcp.tool()
def list_topics() -> list[dict]:
    """All SEC comment topics the Examiner predicts, with plain-English names."""
    return [{"topic": t, "label": label, "covers": DESCRIPTIONS.get(t, "")}
            for t, label in LABELS.items()]


@mcp.tool()
def examiner_status() -> dict:
    """The live model's accuracy and self-improvement record.

    Champion version, F1@5 on 2024 (selection) and 2025-26 (holdout, never used to choose)
    filings vs. simple baselines, whether the judge is sealed, and recent improvement attempts.
    """
    s = _service().status()
    return {"champion": s["champion"], "judge_sealed": s["judge_sealed"],
            "selection": s["selection"], "holdout": s["holdout"],
            "trained_on_filings": s["trained_on"],
            "attempts": [{k: a[k] for k in ("version", "parent", "changes", "selection_f1",
                                            "holdout_f1", "decision", "reason")}
                         for a in s["attempts"][:10]]}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
