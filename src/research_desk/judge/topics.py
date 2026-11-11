"""Deterministic topic labels for SEC comments.

Labels come from fixed keyword rules, not an LLM, so the gold standard can't drift between
runs or be influenced by the model under test. A comment may carry several topics.
"""
import re

# (topic, pattern over "section heading + comment text", lowercased). Order is priority.
TAXONOMY: list[tuple[str, str]] = [
    ("non_gaap", (r"non-gaap|non-ifrs|adjusted ebitda|item 10\(e\)|equal or greater prominence|"
                 r"most directly comparable (?:gaap|ifrs)")),
    ("revenue_recognition", (r"revenue recognition|asc 606|ifrs 15|performance obligation|"
                            r"principal (?:versus|vs\.?|or) agent|gross (?:versus|vs\.?) net")),
    ("segments", r"\bsegment|asc 280|ifrs 8\b|chief operating decision maker|\bcodm\b"),
    ("mdna_drivers", (r"quantif\w+ (?:the )?(?:impact|effect|amount|factors?|drivers?)|"
                     r"underlying (?:reasons|causes|drivers)|price (?:and|versus) volume|"
                     r"results of operations")),
    ("known_trends", r"known trends?|known (?:events|uncertaint)|item 303|reasonably likely"),
    ("liquidity", r"liquidity|capital resources|going concern|covenant|cash flows? (?:from|used)"),
    ("critical_estimates", r"critical accounting (?:estimate|polic)|sensitivity analysis"),
    ("income_taxes", r"income tax|deferred tax|valuation allowance|effective tax rate|asc 740|ias 12"),
    ("impairment", r"impairment|goodwill|reporting unit|recoverab"),
    ("climate", r"climate|greenhouse|emissions|carbon"),
    ("cybersecurity", r"cybersecurity|item 1c\b|cyber"),
    ("legal_contingencies", r"contingenc|litigation|asc 450|ias 37|legal proceedings"),
    ("controls", r"internal control|disclosure controls|\bicfr\b|material weakness"),
    ("kpis", (r"key (?:performance|operating) (?:indicator|measure|metric)|\bkpis?\b|"
             r"operating metric")),
    ("geopolitical", (r"\bchina\b|\bprc\b|hong kong|holding foreign companies|russia|ukraine|"
                     r"sanction|israel|middle east")),
    ("crypto", r"crypto|digital asset|bitcoin|blockchain"),
    ("presentation", (r"statements? of cash flows|earnings per share|\beps\b|classif\w+ (?:of|as)|"
                     r"balance sheet|comprehensive income|financial statement presentation")),
    ("audit_exhibits", r"exhibit|certification|auditor|audit report|pcaob|signature"),
    ("governance_proxy", (r"board leadership|lead (?:independent )?director|executive compensation|"
                         r"proxy|pay versus performance")),
    ("business_disclosure", (r"material (?:agreement|contract)|license agreement|customer "
                            r"concentration|major customer|backlog|item 101|description of business")),
    ("risk_factors", r"risk factor"),
]
_COMPILED = [(t, re.compile(p)) for t, p in TAXONOMY]
TOPICS = [t for t, _ in TAXONOMY]


def topics_of(section: str, text: str) -> list[str]:
    s = f"{section} {text}".lower()
    found = [t for t, rx in _COMPILED if rx.search(s)]
    return found or ["other"]


def primary_topic(section: str, text: str) -> str:
    return topics_of(section, text)[0]
