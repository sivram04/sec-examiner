"""Baselines any real system must beat. Each sees only letters public before the filing date.

Because the SEC repeats themes, cheap rules can score respectably; if the examiner can't beat
them, it adds nothing.
"""
from collections import Counter

from .cases import Case
from .topics import primary_topic


def _topic_counts(history: list[dict], where=lambda letter: True) -> Counter:
    c: Counter = Counter()
    for rec in history:
        L = rec["letter"]
        if not where(L):
            continue
        c.update({primary_topic(x["section"], x["text"])
                  for x in L["comments"] if not x["follow_up"]})
    return c


def base_rate(case: Case, history: list[dict]) -> list[str]:
    """Most common topics across all prior letters."""
    return [t for t, _ in _topic_counts(history).most_common()]


def recent_base_rate(case: Case, history: list[dict], days: int = 365) -> list[str]:
    """Most common topics over the past year: captures SEC sweeps (climate 2021-22, etc.)."""
    from datetime import date, timedelta

    start = (date.fromisoformat(case.filing_date) - timedelta(days=days)).isoformat()
    recent = [r for r in history if r["letter"]["letter_date"] >= start]
    return [t for t, _ in _topic_counts(recent).most_common()] or base_rate(case, history)


def industry_rate(case: Case, history: list[dict]) -> list[str]:
    """Most common topics among prior letters to the same industry (2-digit SIC)."""
    sic2 = (case.sic or "")[:2]
    same = _topic_counts(history, lambda L: (L["sic"] or "")[:2] == sic2 and bool(sic2))
    ranked = [t for t, _ in same.most_common()]
    return ranked + [t for t in base_rate(case, history) if t not in ranked]


def company_history(case: Case, history: list[dict]) -> list[str]:
    """Whatever the SEC asked this company before, then the industry's usual topics."""
    own = _topic_counts(history, lambda L: L["cik"] == case.cik)
    ranked = [t for t, _ in own.most_common()]
    return ranked + [t for t in industry_rate(case, history) if t not in ranked]


BASELINES = {"base_rate": base_rate, "recent_base_rate": recent_base_rate,
             "industry_rate": industry_rate, "company_history": company_history}
