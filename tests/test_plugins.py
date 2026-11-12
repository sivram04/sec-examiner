import gzip
import json

import numpy as np
import pytest

from research_desk.examiner import improve, plugins
from research_desk.examiner.improve import Registry, code_step
from research_desk.examiner.plugins import UnsafeCode, extract, load, validate

GOOD = '''import re
import math

def features(text):
    n = max(len(text), 1)
    goodwill = len(re.findall(r"goodwill", text))
    return {"goodwill_per_10k": 1e4 * goodwill / n,
            "no_headroom": float(goodwill > 0 and "exceeded its carrying" not in text),
            "log_len": math.log1p(n)}
'''


@pytest.mark.parametrize("bad", [
    "import os\ndef features(t):\n    return {}",
    "from re import findall\ndef features(t):\n    return {}",
    "def features(t):\n    return open('x').read()",
    "def features(t):\n    return eval('1')",
    "def features(t):\n    return getattr(t, 'upper')()",
    "def features(t):\n    return t.__class__",
    "import re\ndef features(t):\n    return re.enum.sys.modules",          # public-attribute escape
    "def features(t):\n    return '{0.__class__}'.format(t)",              # format-string escape
    "class X: pass\ndef features(t):\n    return {}",
    "def features(t, u):\n    return {}",
    "def other(t):\n    return {}",
    "def features(t):\n    global G\n    return {}",
    "def features(t):\n    return __import__('os')",
    "def features(t)\n    return {}",
])
def test_validator_blocks_escapes(bad):
    with pytest.raises(UnsafeCode):
        validate(bad)


def test_good_plugin_runs_with_restricted_builtins():
    f = load(GOOD)
    out = f("we have goodwill of $5m. goodwill was tested.")
    assert out["no_headroom"] == 1.0 and out["goodwill_per_10k"] > 0
    assert "open" not in f.__globals__["__builtins__"]


def write_filings(root, n=25):
    root.mkdir()
    ids = []
    for i in range(n):
        cid = f"000-{i:02d}"
        with gzip.open(root / f"{cid}.json.gz", "wt", encoding="utf-8") as fh:
            json.dump({"7": "goodwill " * (i % 3) + "revenue text"}, fh)
        ids.append(cid)
    return ids


def test_sandbox_extracts_features_for_every_filing(tmp_path):
    ids = write_filings(tmp_path / "filings")
    pid, keys = extract(GOOD, tmp_path / "filings", ids, tmp_path / "plugins", log=lambda *_: None)
    feats = json.loads((tmp_path / "plugins" / pid / "features.json").read_text())
    assert set(feats) == set(ids) and keys == sorted(keys) and len(keys) == 3
    assert (tmp_path / "plugins" / pid / "code.py").read_text() == GOOD


def test_sandbox_rejects_nondeterministic_or_crashing_code(tmp_path):
    ids = write_filings(tmp_path / "filings")
    crash = "def features(t):\n    return {'x': 1 / 0}\n"      # every filing fails -> no features
    with pytest.raises(UnsafeCode, match="no numeric"):
        extract(crash, tmp_path / "filings", ids, tmp_path / "plugins", log=lambda *_: None)
    slow = "def features(t):\n    while True:\n        pass\n"
    monkey = plugins._sandbox
    with pytest.raises(UnsafeCode, match="timed out"):
        monkey(slow, tmp_path / "filings", ids[:1], timeout=3)


def test_code_step_blocks_unsafe_code_before_training(tmp_path, monkeypatch):
    reg = Registry(tmp_path / "models")
    (tmp_path / "models" / "v1").mkdir(parents=True)
    meta = {"recipe": {}, "selection": {"overall": {"f1": 0.3}, "topic_recall": {
        "impairment": {"n": 20, "recall": 0.1}}}}
    (tmp_path / "models" / "v1" / "meta.json").write_text(json.dumps(meta))
    reg.log({"attempt": True, "version": "v1", "decision": "promote", "reason": "ok"})
    reg.set_champion("v1")
    trained = []
    monkeypatch.setattr(improve, "train_and_grade", lambda *a, **k: trained.append(1))
    evil = "```python\nimport os\ndef features(t):\n    return {}\n```\nRATIONALE: sneaky"
    e = code_step([], tmp_path / "filings", reg, llm=lambda s, u: evil, log=lambda *_: None)
    assert e["decision"] == "reject" and "blocked before training" in e["reason"]
    assert not trained and reg.state()["champion"] == "v1"
    assert e["code_path"].endswith("code.py")


def test_model_trains_and_predicts_with_plugin_features():
    from research_desk.examiner.model import Recipe, train

    from .test_examiner_model import case, corpus, quiet
    cases, secs = corpus(80, seed=9)
    for c in cases:                                   # plugin signal mirrors the label
        secs[c.case_id]["__plugin__"] = np.array(
            [1.0 if "non_gaap" in c.gold_topics else 0.0, 0.5], np.float32)
    ex = train("t", cases, secs, lambda c: [], log=quiet, recipe=Recipe(plugin="p0123456789"))
    ex.plugin_code, ex.plugin_keys = GOOD, ["goodwill_per_10k", "log_len"]
    assert ex.plugin_scale is not None
    # at serving time there is no cached row: the stored code computes it in-process
    assert len(ex.predict(case(1, "2024-02-01", []), [], {"7": "goodwill"})) > 5
