"""Evaluation cases: one per reviewed filing, labeled with what the SEC actually asked first.

Only first-round comments count. Follow-ups ("we note your response…") continue an earlier
exchange and can't be predicted from the filing alone.
"""
from dataclasses import asdict, dataclass

from .topics import is_follow_up, primary_topic


@dataclass(frozen=True)
class Case:
    case_id: str            # accession of the reviewed filing
    cik: int
    company: str
    sic: str
    form: str
    filing_date: str        # the prediction moment: only data public before this may be used
    period: str | None
    filing_url: str
    letter_accession: str
    letter_date: str
    gold_topics: tuple[str, ...]
    gold_sections: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Case":
        return Case(**{**d, "gold_topics": tuple(d["gold_topics"]),
                       "gold_sections": tuple(d["gold_sections"])})


def cases_from(records: list[dict]) -> list[Case]:
    """records: corpus rows {letter: {...}, targets: [{...}]} -> one Case per first review.

    A filing reviewed by several letters keeps only the earliest letter, which is the one that
    reacted to the filing itself rather than to the company's replies.
    """
    by_filing: dict[str, Case] = {}
    for rec in sorted(records, key=lambda r: r["letter"]["letter_date"]):
        L = rec["letter"]
        first = [c for c in L["comments"] if not is_follow_up(c["text"], c["follow_up"])]
        if not first or len(rec["targets"]) != 1:
            continue   # ambiguous (several filings in one letter) or nothing new to predict
        t = rec["targets"][0]
        if t["accession"] in by_filing:
            continue
        # "other" is not a finding a company can act on, and flagging it would earn free credit
        topics = tuple(t for t in dict.fromkeys(primary_topic(c["section"], c["text"])
                                                for c in first) if t != "other")
        if not topics:
            continue
        sections = tuple(dict.fromkeys(c["section"] for c in first if c["section"]))
        by_filing[t["accession"]] = Case(
            t["accession"], L["cik"], L["company"], L["sic"], t["form"], t["filing_date"],
            t["period"], t["url"], L["accession"], L["letter_date"], topics, sections)
    return sorted(by_filing.values(), key=lambda c: c.filing_date)


def history_before(records: list[dict], moment: str) -> list[dict]:
    """Letters that were public before `moment`. The only history a predictor may see."""
    return [r for r in records if r["letter"]["letter_date"] < moment]
