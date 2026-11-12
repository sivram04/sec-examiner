import pytest
from mcp.server.mcpserver.exceptions import ToolError

from research_desk.examiner import mcp_server


def test_topic_tools_and_errors():
    topics = mcp_server.list_topics()
    assert {"topic": "non_gaap"}.items() <= topics[0].items() and len(topics) >= 20
    with pytest.raises(ToolError, match="unknown topic"):
        mcp_server.explain_topic("nope")


def test_compact_shape():
    r = {"model": "v1", "filing": {}, "note": None, "past_letters": [], "sections_read": ["7"],
         "predictions": [{"topic": "non_gaap", "label": "Non-GAAP measures", "score": 0.8,
                          "from_filing": 0.6, "from_history": 0.2, "missing": ["x"]}]}
    out = mcp_server._compact(r)["likely_comment_topics"][0]
    assert out["likelihood"] == "high" and out["share_from_filing_text"] == 0.75
    assert out["expected_disclosures_not_found"] == ["x"]
