import random

import numpy as np
import pytest

from research_desk.examiner.model import LABELS, Examiner, Recipe, priors, train, validate
from research_desk.judge.cases import Case, history_before

from .test_judge import NG, REV, TAX, rec


def case(i, day, gold, cik=1, sic="7372"):
    return Case(f"F{i}", cik, "Co", sic, "10-K", day, None, "u", f"L{i}", day,
                tuple(gold), ())


# filings that discuss adjusted EBITDA draw non-GAAP comments; ASC 606 ones draw revenue ones
NG_TEXT = "adjusted ebitda reconciliation adjusted ebitda margin non gaap measure presented"
REV_TEXT = "performance obligations transaction price variable consideration contract assets"


def corpus(n=120, seed=0):
    rng = random.Random(seed)
    cases, sections = [], {}
    for i in range(n):
        ng = rng.random() < 0.5
        c = case(i, f"2023-{1 + i % 12:02d}-{1 + i % 27:02d}",
                 ["non_gaap"] if ng else ["revenue_recognition"])
        cases.append(c)
        sections[c.case_id] = {"7": (NG_TEXT if ng else REV_TEXT) + " about the business " * 5}
    return cases, sections


def quiet(*_):
    pass


def test_learns_from_filing_text():
    cases, secs = corpus()
    ex = train("t", cases, secs, lambda c: [], log=quiet)
    assert ex.weight_text > 0                       # tuning found the text useful
    assert ex.predict(case(999, "2024-02-01", []), [], {"7": NG_TEXT * 3})[0] == "non_gaap"
    assert ex.predict(case(998, "2024-02-01", []), [], {"7": REV_TEXT * 3})[0] == \
        "revenue_recognition"


def test_recipe_section_choice_is_respected():
    cases, secs = corpus()
    # train only on Item 1A, where the synthetic filings have no text: nothing to learn from
    ex = train("t", cases, secs, lambda c: [], recipe=Recipe(sections=("1A", "8")), log=quiet)
    assert ex.meta["with_text"] == 0 and ex.meta["recipe"]["sections"] == ["1A", "8"]


def test_priors_ignore_letters_after_the_filing():
    c = case(1, "2023-06-01", [], cik=7)
    past = [rec("A", 7, "2023-01-05", [TAX], "X")]
    future = [rec("B", 7, "2023-09-01", [REV], "Y")]
    p = priors(c, history_before(past + future, c.filing_date))
    assert p[LABELS.index("income_taxes")] > 0
    assert p[LABELS.index("revenue_recognition")] == 0


def test_priors_weight_company_over_market():
    c = case(1, "2023-06-01", [], cik=7, sic="1311")
    hist = [rec("A", 7, "2023-01-05", [TAX], "X", sic="1311")] + \
           [rec(f"M{i}", 100 + i, "2023-02-01", [NG], f"Z{i}", sic="7372") for i in range(5)]
    p = priors(c, hist)
    assert p[LABELS.index("income_taxes")] > p[LABELS.index("non_gaap")]


def test_save_and_load_roundtrip(tmp_path):
    cases, secs = corpus(60, seed=1)
    ex = train("v-test", cases, secs, lambda c: [], log=quiet)
    ex.save(tmp_path)
    back = Examiner.load(tmp_path, "v-test")
    probe = [NG_TEXT, REV_TEXT]
    assert np.allclose(ex.text_probs(probe), back.text_probs(probe))
    assert back.recipe == ex.recipe and (tmp_path / "v-test" / "meta.json").exists()


def test_rare_labels_fall_back_to_priors():
    cases, secs = corpus(60, seed=2)
    ex = train("t", cases, secs, lambda c: [], log=quiet)
    assert ex.models["climate"] is None              # never seen: no text model
    assert ex.text_probs(["anything"]).shape == (1, len(LABELS))


@pytest.mark.parametrize("bad", [
    {"max_features": 10**7}, {"ngram_max": 9}, {"class_weight": "auto"},
    {"sections": ["1"]}, {"sections": ["1", "99"]}, {"c_grid": []}, {"weight_grid": [2]},
    {"learning_rate": 0.1}])
def test_recipe_space_rejects_out_of_range(bad):
    with pytest.raises(ValueError):
        validate(bad)


def test_recipe_roundtrip():
    r = Recipe(c_grid=(1.0,), sections=("7", "8"))
    assert Recipe.from_dict(r.to_dict()) == r
