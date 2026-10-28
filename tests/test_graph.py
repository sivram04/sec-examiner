from research_desk.graph.risks import diff_risks, split_risk_factors
from research_desk.graph.temporal import TemporalGraph, edges_from_snapshots, to_cypher

LONG = " Explanation of the risk in some detail, with consequences for results." * 3

Y1 = "\n\n".join([
    "Risks Related to Our Supply Chain",
    "We depend on a single foundry partner to manufacture our products.", "Body A." + LONG,
    "Natural disasters in Asia could disrupt our operations.", "Body B." + LONG,
    "Risks Related to Regulation",
    "Export controls could restrict sales of our products to China.", "Body C." + LONG,
])
Y2 = "\n\n".join([
    "Risks Related to Our Supply Chain",
    "We depend on a single foundry partner to manufacture our products.", "Body A." + LONG,
    "Risks Related to Regulation",
    "Export controls could restrict sales of our products to China and other regions.",
    "Body C, now covering new license requirements and inventory charges." + LONG,
    "New tariffs on imported components could increase our costs.", "Body D." + LONG,
])


def test_split_risk_factors():
    rf = split_risk_factors(Y1)
    assert [r.headline[:20] for r in rf] == ["We depend on a singl", "Natural disasters in",
                                             "Export controls coul"]
    assert rf[2].category == "Risks Related to Regulation"
    assert rf[0].body.startswith("Body A.")


def test_bold_headlines_win_and_bullets_ignored():
    from research_desk.edgar.parser import parse_sections

    html = "<html><body><p>Item 1A. Risk Factors</p>" + "".join(
        f"<p><b>Headline number {i} explains a material risk to our business.</b></p>"
        f"<p>In 2025, a long body paragraph with detail.{LONG}</p>"
        f"<p>• Bullet summary line {i} that is not a headline.</p>" for i in range(6)
    ) + "<p>Item 2. Properties</p><p>HQ.</p></body></html>"
    sec = next(s for s in parse_sections(html) if s.item == "1A")
    rf = split_risk_factors(sec.text, sec.headings)
    assert [r.headline[:17] for r in rf] == [f"Headline number {i}" for i in range(6)]
    assert "Bullet summary" in rf[0].body


def test_run_in_bold_headlines():
    from research_desk.edgar.parser import parse_sections

    html = "<html><body><p>Item 1A. Risk Factors</p>" + "".join(
        f'<p><span style="font-weight:bold">Run-in headline {i} about a risk to results.</span>'
        f"<span> Body text follows in the same paragraph.{LONG}</span></p>" for i in range(6)
    ) + "<p>Item 2. Properties</p><p>HQ.</p></body></html>"
    sec = next(s for s in parse_sections(html) if s.item == "1A")
    rf = split_risk_factors(sec.text, sec.headings)
    assert len(rf) == 6 and rf[0].headline == "Run-in headline 0 about a risk to results."
    assert rf[0].body.startswith("Body text follows")


def test_diff_risks_classifies_changes():
    ch = {c.kind: c for c in diff_risks(split_risk_factors(Y1), split_risk_factors(Y2))}
    assert ch["added"].new.headline.startswith("New tariffs")
    assert ch["removed"].old.headline.startswith("Natural disasters")
    assert ch["changed"].new.headline.startswith("Export controls")
    assert ch["unchanged"].new.headline.startswith("We depend")


def test_stable_identity_survives_rewording():
    from research_desk.graph.risks import RiskFactor, stable_snapshots

    a = RiskFactor("", "We face intense competition which may adversely affect results.", "x")
    b = RiskFactor("", "We face intense competition which could adversely affect results.", "x")
    snaps = stable_snapshots([("2024-07-01", "a1", [a]), ("2025-07-01", "a2", [b])])
    assert list(snaps[0][2]) == list(snaps[1][2]) == [a.headline]
    assert snaps[1][2][a.headline].startswith(b.headline)  # evidence shows the new wording
    edges = edges_from_snapshots("MSFT", "HAS_RISK", "Risk", snaps)
    assert len(edges) == 1 and edges[0].valid_to is None


def test_temporal_validity_and_what_changed():
    snaps = [("2023-02-01", "a1", {"foundry": "e1", "disasters": "e2"}),
             ("2024-02-01", "a2", {"foundry": "e1", "tariffs": "e3"}),
             ("2025-02-01", "a3", {"foundry": "e1", "tariffs": "e3"})]
    edges = edges_from_snapshots("NVDA", "HAS_RISK", "Risk", snaps)
    g = TemporalGraph()
    g.upsert(edges)
    assert [e.object for e in g.as_of("NVDA", "HAS_RISK", "2023-06-01")] == ["disasters",
                                                                            "foundry"]
    assert [e.object for e in g.as_of("NVDA", "HAS_RISK", "2025-06-01")] == ["foundry",
                                                                            "tariffs"]
    added, removed = g.changed_between("NVDA", "HAS_RISK", "2023-06-01", "2024-06-01")
    assert [e.object for e in added] == ["tariffs"]
    assert [e.object for e in removed] == ["disasters"]
    assert removed[0].ended_by == "a2"
    # before anything was filed, nothing is known (point-in-time)
    assert g.as_of("NVDA", "HAS_RISK", "2022-01-01") == []


def test_cypher_params():
    e = edges_from_snapshots("NVDA", "HAS_RISK", "Risk", [("2024-01-01", "a", {"x": "ev"})])[0]
    q, params = to_cypher(e)
    assert "HAS_RISK" in q and params["valid_to"] is None and params["evidence"] == "ev"
