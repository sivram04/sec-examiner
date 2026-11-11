import shutil
from datetime import date

import pytest

from research_desk.edgar.client import Filing
from research_desk.examiner.letters import Comment, Letter
from research_desk.examiner.link import match
from research_desk.judge import harness
from research_desk.judge.baselines import BASELINES, company_history, recent_base_rate
from research_desk.judge.cases import cases_from, history_before
from research_desk.judge.scoring import score_case
from research_desk.judge.topics import primary_topic, topics_of


def rec(acc, cik, day, comments, target, sic="7372"):
    letter = Letter(acc, cik, f"Co{cik}", sic, day, "substantive",
                    [{"form": "10-K", "period": None, "filed": None}],
                    [Comment(i + 1, s, t, fu) for i, (s, t, fu) in enumerate(comments)])
    return {"letter": letter.to_dict(), "targets": [
        {"form": "10-K", "accession": target, "filing_date": day[:4] + "-02-01",
         "period": None, "url": "u"}] if target else []}


NG = ("Non-GAAP Measures, page 40", "Present the GAAP measure with equal or greater prominence.",
      False)
REV = ("Note 2, page 60", "Explain your performance obligations under ASC 606.", False)
TAX = ("Income Taxes, page 70", "Explain the valuation allowance on deferred tax assets.", False)
FU = ("", "We note your response to comment 1. Please revise.", True)


def test_topics():
    assert primary_topic(*NG[:2]) == "non_gaap"
    assert primary_topic(*REV[:2]) == "revenue_recognition"
    assert "climate" in topics_of("", "Disclose climate-related risks and greenhouse emissions.")
    assert topics_of("", "Please file the missing schedule.") == ["other"]


def test_cases_first_round_only_and_earliest_letter():
    records = [rec("L1", 1, "2023-05-01", [NG, FU], "F1"),
               rec("L2", 1, "2023-07-01", [TAX], "F1"),       # later letter, same filing
               rec("L3", 2, "2023-06-01", [FU], "F2"),        # follow-ups only
               rec("L4", 3, "2023-06-01", [REV], None)]       # not linked
    cases = cases_from(records)
    assert [c.case_id for c in cases] == ["F1"]
    assert cases[0].gold_topics == ("non_gaap",) and cases[0].letter_accession == "L1"


def test_history_is_strictly_before():
    records = [rec("L1", 1, "2023-01-10", [NG], "F1"), rec("L2", 2, "2023-03-01", [TAX], "F2")]
    assert [r["letter"]["accession"] for r in history_before(records, "2023-03-01")] == ["L1"]


def test_score_case():
    s = score_case(["non_gaap", "income_taxes", "segments"], ("non_gaap", "kpis"), k=3)
    assert s == {"precision": pytest.approx(1 / 3), "recall": 0.5, "hit": 1.0}


def test_other_earns_no_credit_and_is_not_gold():
    # predicting "other" first must not use up a slot or score
    assert score_case(["other", "non_gaap"], ("non_gaap",), k=1)["hit"] == 1.0
    vague = ("", "Please file the missing schedule.", False)
    assert cases_from([rec("L1", 1, "2023-05-01", [vague], "F1")]) == []


def test_follow_up_phrasings_detected_by_judge():
    from research_desk.judge.topics import is_follow_up

    for t in ("We have reviewed your responses to comments 5 and 6.",
              "Please refer to comment 1. We note the closing date…",
              "Given your response dated June 17, 2022 with respect to prior comments 1, 2"):
        assert is_follow_up(t)
    assert not is_follow_up("Please quantify the drivers of revenue growth.")


def test_baselines_use_only_given_history():
    old = [rec("L1", 7, "2022-03-01", [TAX], "F0"), rec("L2", 8, "2022-04-01", [NG], "F9")]
    case = cases_from([rec("L3", 7, "2023-05-01", [REV], "F1")])[0]
    assert company_history(case, old)[0] == "income_taxes"          # own past letter first
    assert "revenue_recognition" not in recent_base_rate(case, old)  # the case's own label
    for fn in BASELINES.values():
        assert isinstance(fn(case, old), list)


def test_link_matches_period_before_letter():
    letter = Letter("L", 1, "Co", "", "2024-04-18", "substantive",
                    [{"form": "10-K", "period": "2023-12-31", "filed": None}])
    fs = [Filing(1, "10-K", "A1", date(2024, 2, 20), date(2023, 12, 31), "a.htm"),
          Filing(1, "10-K/A", "A2", date(2024, 5, 1), date(2023, 12, 31), "b.htm"),  # after
          Filing(1, "10-K", "A0", date(2023, 2, 20), date(2022, 12, 31), "c.htm")]
    assert [t.accession for t in match(letter, fs)] == ["A1"]


@pytest.fixture
def sandbox_judge(tmp_path, monkeypatch):
    d = tmp_path / "judge"
    shutil.copytree(harness.JUDGE_DIR, d, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(harness, "JUDGE_DIR", d)
    monkeypatch.setattr(harness, "MANIFEST", d / "MANIFEST.json")
    monkeypatch.setattr(harness, "GATES", d / "gates.json")
    return d


def test_tampering_with_the_judge_is_detected(sandbox_judge):
    harness.seal()
    harness.verify()
    gates = sandbox_judge / "gates.json"
    gates.write_text(gates.read_text().replace('"min_f1_margin": 0.02', '"min_f1_margin": -1'))
    with pytest.raises(harness.IntegrityError, match=r"gates\.json"):
        harness.verify()


def test_evaluate_and_gate(sandbox_judge):
    harness.seal()
    records = [rec(f"L{i}", i % 5, f"20{22 + i // 40}-0{1 + i % 9}-1{i % 9}",
                   [NG if i % 2 else TAX], f"F{i}") for i in range(80)]
    base = {n: harness.evaluate(fn, records, test_from="2023-01-01") for n, fn in BASELINES.items()}

    def oracle(case, history):                  # a "perfect" candidate, for the gate check
        return list(case.gold_topics)

    rep = harness.evaluate(oracle, records, test_from="2023-01-01")
    assert rep["overall"]["recall"] == 1.0
    g = harness.gate(rep, base)
    assert g["checks"]["beats_best_baseline"] and not g["checks"]["min_cases"]
    assert not g["passed"]                      # too few cases to trust
