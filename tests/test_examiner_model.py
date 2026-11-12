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
    assert ex.meta["with_text"] == 0 and list(ex.meta["recipe"]["sections"]) == ["1A", "8"]
    assert ex.weight_text == 0.0                      # priors only, no crash
    assert len(ex.predict(case(1, "2024-02-01", []), [], {"7": NG_TEXT})) == len(LABELS)


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


def test_embedding_signal_is_learned_when_text_is_uninformative():
    rng = np.random.default_rng(0)
    cases, secs = corpus(160, seed=3)
    for c in cases:                       # same words for everyone; meaning lives in embeddings
        ng = "non_gaap" in c.gold_topics
        e = rng.normal(size=16).astype(np.float32)
        e[0] += 3.0 if ng else -3.0
        secs[c.case_id] = {"7": "about the business " * 20, "__emb__": e}
    ex = train("t", cases, secs, lambda c: [], log=quiet,
               recipe=Recipe(embed_grid=(0.0, 0.5, 1.0), min_df=1))
    assert ex.embed_share > 0
    probe = np.zeros(16, np.float32)
    probe[0] = 3.0
    assert ex.predict(case(999, "2024-02-01", []), [], {"7": "x", "__emb__": probe})[0] == \
        "non_gaap"


def test_embeddings_off_by_default():
    cases, secs = corpus(80, seed=4)
    for c in cases:
        secs[c.case_id]["__emb__"] = np.ones(8, np.float32)
    ex = train("t", cases, secs, lambda c: [], log=quiet)
    assert ex.embed_share == 0.0 and ex.emb_scale is None


def test_embed_chunks_pick_topic_passages():
    from research_desk.examiner.embed import MAX_CHUNKS, chunks
    body = ("filler text " * 70) * 30 + "goodwill impairment of the reporting unit " * 20
    picked = chunks({"7": body, "__emb__": "ignored"})
    assert len(picked) <= MAX_CHUNKS and any("goodwill" in p for p in picked)


def test_gap_features_flag_missing_disclosures():
    from research_desk.examiner.gaps import TOPICS as GT
    from research_desk.examiner.gaps import gap_features, gaps_report
    thin = {"7": "we have goodwill on the balance sheet. " * 5}
    full = {"7": "goodwill is tested for each reporting unit; the fair value of each reporting "
                 "unit exceeded its carrying value by 20%. discount rates were 9%. we performed "
                 "a quantitative impairment test."}
    i = GT.index("impairment")
    assert gap_features(thin)[4 * i + 3] == 1.0 and gap_features(full)[4 * i + 3] == 0.0
    assert "impairment" in gaps_report(thin) and gap_features({})[4 * i] == 0.0


def test_gaps_recipe_trains_and_predicts():
    cases, secs = corpus(100, seed=5)
    for c in cases:                       # gap signal: non-GAAP filings lack a reconciliation
        if "non_gaap" in c.gold_topics:
            secs[c.case_id]["7"] += " adjusted ebitda adjusted ebitda"
    ex = train("t", cases, secs, lambda c: [], log=quiet, recipe=Recipe(gaps=True))
    assert len(ex.predict(case(1, "2024-02-01", []), [], {"7": NG_TEXT})) == len(LABELS)
    assert ex.recipe.gaps and validate({"gaps": True}) == {"gaps": True}
    with pytest.raises(ValueError):
        validate({"gaps": "yes"})
