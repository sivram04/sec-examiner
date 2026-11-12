"""Disclosure-gap features: a topic is discussed, but what the SEC staff expects with it is absent.

SEC comments are often about omissions ("you disclose goodwill but not how close each reporting
unit is to failing its impairment test"). Word counts and topic similarity measure what a filing
says; these rules measure what it leaves out. Each rule has a trigger (the topic is present) and
the disclosures staff usually expect alongside it. Features per rule, over the whole filing:
- trigger present (0/1) and how heavily it is discussed (log of mentions per 100k characters);
- share of expected disclosures found;
- gap flag: triggered, but fewer than half the expected disclosures present.
Fast (regex), deterministic and worker-owned; the judge's labels never depend on them.
"""
import math
import re

import numpy as np

# topic -> (trigger, [expected disclosures])
RULES: dict[str, tuple[str, list[str]]] = {
    "impairment": (r"goodwill", [
        r"reporting units?", r"fair value of (?:the |each |our )?reporting units? exceed",
        r"exceed(?:ed|s)? (?:its |their )?carrying (?:value|amount)s? by", r"discount rates?",
        r"quantitative (?:goodwill )?(?:impairment )?test|qualitative assessment"]),
    "income_taxes": (r"deferred tax assets?", [
        r"valuation allowance", r"effective (?:income )?tax rate", r"unrecognized tax benefits?",
        r"statutory (?:federal )?(?:income )?tax rate"]),
    "non_gaap": (r"non-gaap|adjusted ebitda|non-ifrs", [
        r"most directly comparable", r"reconciliation",
        r"(?:in isolation|as a substitute|alternative to) (?:for )?(?:net income|gaap|ifrs)?"]),
    "revenue_recognition": (r"performance obligations?", [
        r"disaggregat", r"remaining performance obligations?",
        r"principal (?:versus|vs\.?|or) (?:an )?agent|gross (?:versus|vs\.?) net",
        r"contract (?:assets|liabilities)"]),
    "segments": (r"reportable segments?|operating segments?", [
        r"chief operating decision maker|\bcodm\b", r"segment (?:profit|income|operating income)",
        r"reconciliation of (?:total )?(?:reportable )?segment", r"significant segment expenses"]),
    "cybersecurity": (r"cybersecurity", [
        r"item 1c", r"chief information security officer|\bciso\b",
        r"third[- ]part(?:y|ies) (?:assessors|consultants|auditors|service providers)",
        r"audit committee|board of directors oversee"]),
    "financial_instruments": (r"derivative|level 3", [
        r"valuation techniques?", r"unobservable inputs?", r"hedg", r"counterpart(?:y|ies)"]),
    "legal_contingencies": (r"litigation|legal proceedings", [
        r"reasonably possible",
        (r"range of (?:reasonably )?possible loss|estimate of (?:the )?"
         r"(?:possible |reasonably possible )?loss"),
        r"asc 450|accru"]),
    "liquidity": (r"liquidity", [
        r"material cash requirements", r"covenants?", r"next (?:twelve|12) months",
        r"credit (?:facility|agreement)", r"cash flows? (?:from|used in) operating"]),
    "critical_estimates": (r"critical accounting (?:estimates?|policies)", [
        r"sensitivity", r"hypothetical", r"would (?:have )?(?:increase|decrease)d?",
        r"reasonably likely"]),
    "mdna_drivers": (r"results of operations", [
        r"primarily (?:due|attributable) to", r"partially offset", r"\bprice", r"\bvolume"]),
    "controls": (r"internal control over financial reporting", [
        r"material weakness", r"remediat", r"(?:not )?effective as of"]),
    "kpis": (r"key (?:performance|operating) (?:indicators?|metrics?|measures?)|operating metrics?",
             [r"we define|is defined as", r"calculat", r"compar(?:ed|able) (?:to|with) (?:the )?prior"]),
    "climate": (r"climate", [r"physical risks?", r"transition risks?",
                             r"greenhouse gas|emissions", r"regulat"]),
    "crypto": (r"crypto|digital assets?|bitcoin", [r"custod", r"safeguard", r"fair value"]),
    "known_trends": (r"inflation|interest rates?|tariff", [
        r"known trends?|known (?:events|uncertaint)", r"we expect|expected to",
        r"reasonably likely"]),
    "geopolitical": (r"\bchina\b|\bprc\b|hong kong|russia|ukraine", [
        r"holding foreign companies", r"variable interest entit|\bvies?\b",
        r"sanctions?", r"cash transfers?|transfer of cash"]),
}

# plain-English name of each expected disclosure, in RULES order (shown to users)
NAMES: dict[str, list[str]] = {
    "impairment": ["goodwill by reporting unit",
                   "reporting units whose fair value is close to carrying value", "headroom (how far fair value exceeds carrying value)",
                   "discount rate assumptions", "type of impairment test performed"],
    "income_taxes": ["valuation allowance", "effective tax rate explanation",
                     "unrecognized tax benefits", "statutory rate reconciliation"],
    "non_gaap": ["the most directly comparable GAAP measure", "reconciliation to GAAP",
                 "caution that the measure is not a substitute for GAAP"],
    "revenue_recognition": ["disaggregated revenue", "remaining performance obligations",
                            "principal versus agent judgment", "contract assets and liabilities"],
    "segments": ["chief operating decision maker", "segment profit measure",
                 "reconciliation of segment totals", "significant segment expenses"],
    "cybersecurity": ["Item 1C disclosure", "named security lead (CISO)",
                      "use of third-party assessors", "board or committee oversight"],
    "financial_instruments": ["valuation techniques", "unobservable inputs", "hedging policy",
                              "counterparty risk"],
    "legal_contingencies": ["whether a loss is reasonably possible", "estimate or range of loss",
                            "accrual policy (ASC 450)"],
    "liquidity": ["material cash requirements", "debt covenants", "12-month liquidity outlook",
                  "credit facility terms", "operating cash flow discussion"],
    "critical_estimates": ["sensitivity analysis", "hypothetical change scenarios",
                           "quantified effect of changes", "reasonably likely changes"],
    "mdna_drivers": ["reasons for changes", "offsetting factors", "price effects",
                     "volume effects"],
    "controls": ["material weakness assessment", "remediation plans",
                 "effectiveness conclusion"],
    "kpis": ["definition of each metric", "how each metric is calculated",
             "comparison with prior periods"],
    "climate": ["physical climate risks", "transition risks", "emissions",
                "climate regulation"],
    "crypto": ["custody arrangements", "safeguarding of assets", "fair value of holdings"],
    "known_trends": ["known trends and uncertainties", "expected future effects",
                     "reasonably likely impacts"],
    "geopolitical": ["HFCAA status", "VIE structure", "sanctions exposure",
                     "cash transfers within the group"],
}

_COMPILED = [(t, re.compile(trig), [re.compile(e) for e in exp]) for t, (trig, exp) in RULES.items()]
TOPICS = [t for t, _, _ in _COMPILED]
N_FEATURES = 4 * len(_COMPILED)


def gap_features(sections: dict[str, str] | None) -> np.ndarray:
    out = np.zeros(N_FEATURES, dtype=np.float32)
    if not sections:
        return out
    text = "\n".join(v for k, v in sections.items()
                     if not k.startswith("__") and isinstance(v, str)).lower()
    if not text:
        return out
    per100k = 100_000 / len(text)
    for i, (_, trig, expected) in enumerate(_COMPILED):
        hits = len(trig.findall(text))
        if not hits:
            continue
        share = sum(bool(e.search(text)) for e in expected) / len(expected)
        out[4 * i:4 * i + 4] = (1.0, math.log1p(hits * per100k) / 5, share, float(share < 0.5))
    return out


def gaps_report(sections: dict[str, str] | None) -> dict[str, list[str]]:
    """Human-readable: for each triggered topic, the expected disclosures not found."""
    text = "\n".join(v for k, v in (sections or {}).items()
                     if not k.startswith("__") and isinstance(v, str)).lower()
    out = {}
    for t, trig, expected in _COMPILED:
        if trig.search(text):
            missing = [NAMES[t][j] for j, e in enumerate(expected) if not e.search(text)]
            if missing:
                out[t] = missing
    return out
