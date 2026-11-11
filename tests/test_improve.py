import json

import pytest

from research_desk.examiner import improve
from research_desk.examiner.improve import Registry, diagnose, rule_propose, step


def fake_meta(version, recipe, sel_f1, passed=True, hold_f1=0.3, weight=1.0, val_f1=0.5):
    topic_recall = {"non_gaap": {"n": 50, "recall": 0.9},
                    "impairment": {"n": 20, "recall": 0.1}}
    return {"version": version, "recipe": recipe, "val_f1": val_f1, "weight_text": weight,
            "train_secs": 100,
            "selection": {"overall": {"f1": sel_f1, "n": 266}, "topic_recall": topic_recall,
                          "mean_secs": 1.0},
            "selection_gate": {"passed": passed, "checks": {}},
            "holdout": {"overall": {"f1": hold_f1, "n": 306}}}


@pytest.fixture
def reg(tmp_path, monkeypatch):
    """A registry whose trainer is scripted: candidate F1 comes from `scores` in order."""
    r = Registry(tmp_path)
    scores = []

    def fake_train(records, filings_root, root, version, recipe, log=print):
        f1, passed = scores.pop(0)
        if f1 == "crash":
            raise RuntimeError("boom")
        meta = fake_meta(version, recipe.to_dict(), f1, passed)
        (root / version).mkdir(parents=True, exist_ok=True)
        (root / version / "meta.json").write_text(json.dumps(meta))
        return meta

    monkeypatch.setattr(improve, "train_and_grade", fake_train)
    r.scores = scores
    return r


def quiet(*_):
    pass


def test_diagnose_finds_problems():
    kinds = {f["kind"] for f in diagnose(fake_meta("v1", {}, 0.30, passed=False))}
    assert {"weak_topic", "validation_overstates", "signal_unused", "gate_fail"} <= kinds


def test_bootstrap_then_promote_then_reject(reg):
    reg.scores += [(0.34, True), (0.36, True), (0.361, True)]
    e = step([], None, reg, log=quiet)
    assert e["decision"] == "promote" and reg.state()["champion"] == "v1"
    e = step([], None, reg, log=quiet)                   # +0.02: promote
    assert e["decision"] == "promote" and reg.state()["champion"] == "v2"
    assert e["parent"] == "v1" and e["changes"]
    e = step([], None, reg, log=quiet)                   # +0.001: below MIN_GAIN
    assert e["decision"] == "reject" and "no gain" in e["reason"]
    assert reg.state()["champion"] == "v2"


def test_judge_gate_beats_raw_score(reg):
    reg.scores += [(0.34, True), (0.50, False)]          # higher F1, but the judge says no
    step([], None, reg, log=quiet)
    e = step([], None, reg, log=quiet)
    assert e["decision"] == "reject" and e["reason"] == "fails the judge gate"


def test_crashing_candidate_is_rejected_not_fatal(reg):
    reg.scores += [(0.34, True), ("crash", True)]
    step([], None, reg, log=quiet)
    e = step([], None, reg, log=quiet)
    assert e["decision"] == "reject" and "crashed" in e["reason"]
    assert reg.state()["champion"] == "v1"


def test_never_repeats_a_change(reg):
    reg.scores += [(0.34, True)] + [(0.30, True)] * 4
    step([], None, reg, log=quiet)
    tried = [json.dumps(step([], None, reg, log=quiet)["changes"], sort_keys=True)
             for _ in range(4)]
    assert len(set(tried)) == 4


def test_llm_proposal_used_when_valid_and_ignored_when_not(reg):
    reg.scores += [(0.34, True), (0.35, True), (0.36, True)]
    step([], None, reg, log=quiet)
    good = step([], None, reg, log=quiet,
                llm=lambda s, u: '{"changes": {"min_df": 5}, "rationale": "denoise"}')
    assert good["changes"] == {"min_df": 5} and good["rationale"].startswith("llm:")
    bad = step([], None, reg, log=quiet,                 # out of range: rules take over
               llm=lambda s, u: '{"changes": {"max_features": 99999999}}')
    assert bad["rationale"].startswith("rule:")


def test_rollback(reg):
    reg.scores += [(0.34, True), (0.36, True)]
    step([], None, reg, log=quiet)
    step([], None, reg, log=quiet)
    assert reg.rollback() == "v1" and reg.state()["champion"] == "v1"
    assert reg.rollback() is None                        # nothing older to revert to


def test_rule_proposer_exhausts():
    attempts = [{"parent": "v1", "changes": c} for _, c in improve.FALLBACK]
    assert rule_propose([{"kind": "weak_topic"}], attempts, "v1")[0] == {}


def test_bootstrap_from_seed_recipe(reg):
    from research_desk.examiner.model import Recipe
    reg.scores += [(0.34, True)]
    e = step([], None, reg, log=quiet, seed=(Recipe(min_df=5), "carried over"))
    assert e["rationale"] == "bootstrap: carried over"
    assert reg.meta("v1")["recipe"]["min_df"] == 5
