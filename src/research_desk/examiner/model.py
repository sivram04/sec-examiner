"""Examiner v1: reads the filing and predicts which topics the SEC staff will raise.

score(topic) = w * P(topic | filing text) + (1 - w) * prior(topic | company, industry, recent)

- Text model: TF-IDF over the cached sections, one logistic regression per topic.
- Priors: shares of past letters raising each topic, computed only from letters public before
  the filing date (the same point-in-time rule the judge enforces).
- w and C are chosen on the newest slice of the training data, never on the test window.
Everything here belongs to the worker: the self-improvement loop may change any of it.
"""
import json
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from ..judge.topics import TOPICS, is_follow_up, primary_topic

LABELS = [t for t in TOPICS if t != "other"]


def filing_text(sections: dict[str, str] | None) -> str:
    if not sections:
        return ""
    # tag each section so "segment" in MD&A and in the notes are different signals
    return "\n".join(f"[item {k}] {v}" for k, v in sections.items())


def _letter_topics(L: dict) -> set[str]:
    return {primary_topic(c["section"], c["text"]) for c in L["comments"]
            if not is_follow_up(c["text"], c["follow_up"])} - {"other"}


def priors(case, history: list[dict], recent_days: int = 365) -> np.ndarray:
    """Per-label prior from letters before the filing: company, industry, recent market."""
    sic2 = (case.sic or "")[:2]
    start = (date.fromisoformat(case.filing_date) - timedelta(days=recent_days)).isoformat()
    groups = {"company": Counter(), "industry": Counter(), "recent": Counter()}
    sizes = Counter()
    for rec in history:
        L = rec["letter"]
        ts = _letter_topics(L)
        if not ts:
            continue
        if L["cik"] == case.cik:
            groups["company"].update(ts)
            sizes["company"] += 1
        if sic2 and (L["sic"] or "")[:2] == sic2:
            groups["industry"].update(ts)
            sizes["industry"] += 1
        if L["letter_date"] >= start:
            groups["recent"].update(ts)
            sizes["recent"] += 1
    weights = {"company": 0.4, "industry": 0.35, "recent": 0.25}
    out = np.zeros(len(LABELS))
    for g, w in weights.items():
        if sizes[g]:
            out += w * np.array([groups[g][t] / sizes[g] for t in LABELS])
    return out


@dataclass
class Examiner:
    version: str
    weight_text: float = 0.5
    C: float = 1.0
    vectorizer: TfidfVectorizer | None = None
    models: dict = field(default_factory=dict)       # label -> LogisticRegression (or None)
    base_rates: dict = field(default_factory=dict)   # label -> training prevalence
    meta: dict = field(default_factory=dict)

    def _fit_text(self, texts: list[str], Y: np.ndarray) -> None:
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_df=0.9,
                                          max_features=60_000, sublinear_tf=True,
                                          stop_words="english")
        X = self.vectorizer.fit_transform(texts)
        self.models, self.base_rates = {}, {}
        for j, t in enumerate(LABELS):
            y = Y[:, j]
            self.base_rates[t] = float(y.mean())
            if y.sum() < 5:      # too rare to learn from text: rely on priors
                self.models[t] = None
                continue
            m = LogisticRegression(C=self.C, class_weight="balanced", max_iter=2000)
            m.fit(X, y)
            self.models[t] = m

    def text_probs(self, texts: list[str]) -> np.ndarray:
        X = self.vectorizer.transform(texts)
        cols = []
        for t in LABELS:
            m = self.models.get(t)
            cols.append(m.predict_proba(X)[:, 1] if m is not None
                        else np.full(X.shape[0], self.base_rates.get(t, 0.0)))
        return np.column_stack(cols)

    def rank(self, text_p: np.ndarray, prior: np.ndarray) -> list[str]:
        # calibrate the two signals to comparable scales before blending
        tp = text_p / (text_p.max() or 1.0)
        pr = prior / (prior.max() or 1.0)
        score = self.weight_text * tp + (1 - self.weight_text) * pr
        return [LABELS[i] for i in np.argsort(-score)]

    def predict(self, case, history: list[dict], text: str) -> list[str]:
        return self.rank(self.text_probs([text])[0], priors(case, history))

    def save(self, root: Path) -> Path:
        d = root / self.version
        d.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, d / "model.joblib", compress=3)
        (d / "meta.json").write_text(json.dumps(self.meta, indent=2) + "\n", encoding="utf-8")
        return d

    @staticmethod
    def load(root: Path, version: str) -> "Examiner":
        return joblib.load(root / version / "model.joblib")


def _labels(cases) -> np.ndarray:
    return np.array([[t in c.gold_topics for t in LABELS] for c in cases], dtype=int)


def _tuning_score(preds: list[list[str]], cases) -> tuple[float, float]:
    """(F1@5, mean reciprocal rank of the real issues).

    F1@5 is what the judge grades, but it is coarse: settings often tie. Ranking quality breaks
    ties, so real issues are pushed toward the top rather than just inside the top five.
    """
    from ..judge.scoring import aggregate

    f1 = aggregate([{"case": c, "pred": p} for c, p in zip(cases, preds, strict=True)],
                   k=5)["overall"].get("f1", 0.0)
    rr = [np.mean([1 / (p.index(t) + 1) for t in c.gold_topics if t in p] or [0.0])
          for c, p in zip(cases, preds, strict=True)]
    return f1, float(np.mean(rr)) if rr else 0.0


def train(version: str, train_cases, texts: dict[str, str], history_of, log=print) -> Examiner:
    """Fit on cases whose letters are public before the test window; tune on the newest 20%.

    history_of(case) -> letters public before the case's filing date (point-in-time).
    """
    t0 = time.time()
    cases = sorted(train_cases, key=lambda c: c.filing_date)
    cut = int(len(cases) * 0.8)
    fit, val = cases[:cut], cases[cut:]
    val_priors = [priors(c, history_of(c)) for c in val]
    best = ((-1.0, -1.0), 0.5, 1.0)
    for C in (0.3, 1.0, 3.0):
        ex = Examiner("tune", C=C)
        ex._fit_text([texts.get(c.case_id, "") for c in fit], _labels(fit))
        tp = ex.text_probs([texts.get(c.case_id, "") for c in val])
        for w in (0.0, 0.25, 0.4, 0.5, 0.6, 0.75, 1.0):
            ex.weight_text = w
            s = _tuning_score([ex.rank(tp[i], val_priors[i]) for i in range(len(val))], val)
            if s > best[0]:
                best = (s, w, C)
    (f1, mrr), w, C = best
    log(f"tuned on {len(val)} validation cases: f1={f1:.3f} mrr={mrr:.3f} weight_text={w} C={C}")
    ex = Examiner(version, weight_text=w, C=C)
    ex._fit_text([texts.get(c.case_id, "") for c in cases], _labels(cases))
    ex.meta = {"version": version, "trained_on": len(cases),
               "train_window": [cases[0].filing_date, cases[-1].filing_date],
               "val_f1": round(f1, 3), "val_mrr": round(mrr, 3), "weight_text": w, "C": C,
               "with_text": sum(bool(texts.get(c.case_id)) for c in cases),
               "train_secs": round(time.time() - t0, 1)}
    return ex
