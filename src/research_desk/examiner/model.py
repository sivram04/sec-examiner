"""The Examiner: reads a filing and predicts which topics the SEC staff will raise.

score(topic) = w * P(topic | filing text) + (1 - w) * prior(topic | company, industry, recent)

Every design choice lives in a Recipe. The self-improvement loop changes the Recipe (within
RECIPE_SPACE), retrains, and lets the sealed judge decide whether the result is better.
"""
import json
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from ..judge.topics import TOPICS, is_follow_up, primary_topic
from .gaps import N_FEATURES as N_GAP
from .gaps import gap_features

LABELS = [t for t in TOPICS if t != "other"]


@dataclass(frozen=True)
class Recipe:
    sections: tuple[str, ...] = ("1", "1A", "1C", "5", "7", "7A", "8", "9A", "15", "I-1", "I-2",
                                 "II-1A", "other", "body")
    max_chars: int = 250_000         # per filing, after section selection
    ngram_max: int = 2
    min_df: int = 3
    max_features: int = 60_000
    class_weight: str = "balanced"   # or "none"
    c_grid: tuple[float, ...] = (0.3, 1.0, 3.0)
    weight_grid: tuple[float, ...] = (0.0, 0.25, 0.4, 0.5, 0.6, 0.75, 1.0)
    prior_company: float = 0.4
    prior_industry: float = 0.35
    prior_recent: float = 0.25
    recent_days: int = 365
    val_fraction: float = 0.2
    # share of the text signal taken from passage embeddings (0 = word counts only); tuned
    embed_grid: tuple[float, ...] = (0.0,)
    gaps: bool = False               # add disclosure-gap features (examiner/gaps.py)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Recipe":
        tup = {"sections", "c_grid", "weight_grid", "embed_grid"}
        return Recipe(**{k: tuple(v) if k in tup else v for k, v in d.items()})


# what the loop may change, and to what. Anything outside this is rejected before training.
RECIPE_SPACE: dict[str, object] = {
    "sections": "subset of the default sections, at least 2",
    "max_chars": (50_000, 400_000),
    "ngram_max": (1, 3),
    "min_df": (2, 20),
    "max_features": (5_000, 150_000),
    "class_weight": ("balanced", "none"),
    "c_grid": "1-5 values in [0.01, 30]",
    "weight_grid": "1-11 values in [0, 1]",
    "prior_company": (0.0, 1.0),
    "prior_industry": (0.0, 1.0),
    "prior_recent": (0.0, 1.0),
    "recent_days": (60, 1095),
    "val_fraction": (0.1, 0.4),
    "embed_grid": "1-6 values in [0, 1]",
    "gaps": (False, True),
}


def validate(changes: dict) -> dict:
    """Return the changes if all lie inside RECIPE_SPACE; raise ValueError otherwise."""
    default = Recipe()
    for k, v in changes.items():
        if k not in RECIPE_SPACE:
            raise ValueError(f"unknown recipe field {k!r}")
        space = RECIPE_SPACE[k]
        if k == "sections":
            if not (isinstance(v, (list, tuple)) and len(v) >= 2 and set(v) <= set(default.sections)):
                raise ValueError(f"sections must be a subset of {default.sections}")
        elif k == "c_grid":
            if not (isinstance(v, (list, tuple)) and 1 <= len(v) <= 5
                    and all(0.01 <= float(x) <= 30 for x in v)):
                raise ValueError("c_grid: 1-5 values in [0.01, 30]")
        elif k == "embed_grid":
            if not (isinstance(v, (list, tuple)) and 1 <= len(v) <= 6
                    and all(0 <= float(x) <= 1 for x in v)):
                raise ValueError("embed_grid: 1-6 values in [0, 1]")
        elif k == "weight_grid":
            if not (isinstance(v, (list, tuple)) and 1 <= len(v) <= 11
                    and all(0 <= float(x) <= 1 for x in v)):
                raise ValueError("weight_grid: 1-11 values in [0, 1]")
        elif k == "gaps":
            if not isinstance(v, bool):
                raise ValueError("gaps must be true or false")
        elif isinstance(space, tuple) and isinstance(space[0], str):
            if v not in space:
                raise ValueError(f"{k} must be one of {space}")
        else:
            lo, hi = space
            if not (isinstance(v, (int, float)) and lo <= v <= hi):
                raise ValueError(f"{k} must be in [{lo}, {hi}]")
    return changes


def filing_text(sections: dict[str, str] | None, recipe: Recipe | None = None) -> str:
    if not sections:
        return ""
    r = recipe or Recipe()
    keep = [(k, v) for k, v in sections.items() if k in r.sections]
    # tag each section so "segment" in MD&A and in the notes are different signals
    return "\n".join(f"[item {k}] {v}" for k, v in keep)[: r.max_chars]


_TOPIC_CACHE: dict[str, frozenset[str]] = {}


def _letter_topics(L: dict) -> frozenset[str]:
    """Topics of a letter's first-round comments. Letters are immutable, so cache by accession."""
    key = L.get("accession")
    if key and key in _TOPIC_CACHE:
        return _TOPIC_CACHE[key]
    ts = frozenset({primary_topic(c["section"], c["text"]) for c in L["comments"]
                    if not is_follow_up(c["text"], c["follow_up"])} - {"other"})
    if key:
        _TOPIC_CACHE[key] = ts
    return ts


def priors(case, history: list[dict], recipe: Recipe | None = None) -> np.ndarray:
    """Per-label prior from letters before the filing: company, industry, recent market."""
    r = recipe or Recipe()
    sic2 = (case.sic or "")[:2]
    start = (date.fromisoformat(case.filing_date) - timedelta(days=r.recent_days)).isoformat()
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
    weights = {"company": r.prior_company, "industry": r.prior_industry,
               "recent": r.prior_recent}
    out = np.zeros(len(LABELS))
    for g, w in weights.items():
        if sizes[g]:
            out += w * np.array([groups[g][t] / sizes[g] for t in LABELS])
    return out


@dataclass
class Examiner:
    version: str
    recipe: Recipe = field(default_factory=Recipe)
    weight_text: float = 0.5
    C: float = 1.0
    vectorizer: TfidfVectorizer | None = None
    models: dict = field(default_factory=dict)       # label -> LogisticRegression (or None)
    base_rates: dict = field(default_factory=dict)   # label -> training prevalence
    meta: dict = field(default_factory=dict)
    embed_share: float = 0.0
    emb_models: dict = field(default_factory=dict)   # label -> LogisticRegression on embeddings
    emb_scale: tuple | None = None                   # (mean, std) of embedding features

    def _vectorizer(self) -> TfidfVectorizer:
        r = self.recipe
        return TfidfVectorizer(ngram_range=(1, r.ngram_max), min_df=r.min_df, max_df=0.9,
                               max_features=r.max_features, sublinear_tf=True,
                               stop_words="english", dtype=np.float32)

    def _fit_models(self, X, Y: np.ndarray) -> None:
        self.models, self.base_rates = {}, {}
        cw = None if self.recipe.class_weight == "none" else "balanced"
        for j, t in enumerate(LABELS):
            y = Y[:, j]
            self.base_rates[t] = float(y.mean())
            if y.sum() < 5:      # too rare to learn from text: rely on priors
                self.models[t] = None
                continue
            m = LogisticRegression(C=self.C, class_weight=cw, max_iter=2000)
            m.fit(X, y)
            self.models[t] = m

    def probs_from_matrix(self, X) -> np.ndarray:
        cols = []
        for t in LABELS:
            m = self.models.get(t)
            cols.append(m.predict_proba(X)[:, 1] if m is not None
                        else np.full(X.shape[0], self.base_rates.get(t, 0.0)))
        return np.column_stack(cols)

    def _fit_emb(self, E: np.ndarray, Y: np.ndarray) -> None:
        mu, sd = E.mean(axis=0), E.std(axis=0) + 1e-6
        self.emb_scale = (mu, sd)
        Z = (E - mu) / sd
        cw = None if self.recipe.class_weight == "none" else "balanced"
        self.emb_models = {}
        for j, t in enumerate(LABELS):
            y = Y[:, j]
            self.emb_models[t] = None if y.sum() < 5 else                 LogisticRegression(C=0.05, class_weight=cw, max_iter=2000).fit(Z, y)

    def emb_probs(self, E: np.ndarray) -> np.ndarray:
        if self.emb_scale is None:
            return np.zeros((len(E), len(LABELS)))
        Z = (E - self.emb_scale[0]) / self.emb_scale[1]
        return np.column_stack([m.predict_proba(Z)[:, 1] if (m := self.emb_models.get(t))
                                is not None else np.full(len(E), self.base_rates.get(t, 0.0))
                                for t in LABELS])

    def text_probs(self, texts: list[str], gap_rows: np.ndarray | None = None) -> np.ndarray:
        if self.vectorizer is None:      # no usable text at training time: priors only
            return np.zeros((len(texts), len(LABELS)))
        return self.probs_from_matrix(_with_gaps(self.vectorizer.transform(texts), gap_rows,
                                                 self.recipe))

    def rank(self, text_p: np.ndarray, prior: np.ndarray) -> list[str]:
        # calibrate the two signals to comparable scales before blending
        tp = text_p / (text_p.max() or 1.0)
        pr = prior / (prior.max() or 1.0)
        score = self.weight_text * tp + (1 - self.weight_text) * pr
        return [LABELS[i] for i in np.argsort(-score)]

    def signals(self, case, history: list[dict], sections: dict[str, str] | None):
        """(text signal, prior signal) per label, before blending."""
        text = filing_text(sections, self.recipe)
        g = gap_features(sections)[None, :] if self.recipe.gaps else None
        tp = self.text_probs([text], g)[0]
        if self.embed_share and sections is not None and "__emb__" in sections:
            ep = self.emb_probs(sections["__emb__"][None, :])[0]
            tp = (1 - self.embed_share) * tp + self.embed_share * ep
        return tp, priors(case, history, self.recipe)

    def predict(self, case, history: list[dict], sections: dict[str, str] | None) -> list[str]:
        return self.rank(*self.signals(case, history, sections))

    def explain(self, case, history: list[dict], sections: dict[str, str] | None) -> list[dict]:
        """Every label with its blended score and how much came from the filing vs history."""
        tp, pr = self.signals(case, history, sections)
        tpn, prn = tp / (tp.max() or 1.0), pr / (pr.max() or 1.0)
        w = self.weight_text
        rows = [{"topic": t, "score": round(float(w * tpn[i] + (1 - w) * prn[i]), 4),
                 "from_filing": round(float(w * tpn[i]), 4),
                 "from_history": round(float((1 - w) * prn[i]), 4)}
                for i, t in enumerate(LABELS)]
        return sorted(rows, key=lambda r: -r["score"])

    def save(self, root: Path) -> Path:
        d = root / self.version
        d.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, d / "model.joblib", compress=3)
        (d / "meta.json").write_text(json.dumps(self.meta, indent=2) + "\n", encoding="utf-8")
        return d

    @staticmethod
    def load(root: Path, version: str) -> "Examiner":
        return joblib.load(root / version / "model.joblib")


def _with_gaps(X, gap_rows, recipe: Recipe):
    if not recipe.gaps:
        return X
    from scipy.sparse import csr_matrix, hstack

    G = gap_rows if gap_rows is not None else np.zeros((X.shape[0], N_GAP), np.float32)
    return hstack([X, csr_matrix(G)], format="csr")


def _emb_matrix(cases, sections) -> np.ndarray:
    rows = [(sections.get(c.case_id) or {}).get("__emb__") for c in cases]
    dim = next(len(v) for v in rows if v is not None)
    return np.array([v if v is not None else np.zeros(dim, np.float32) for v in rows])


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


def train(version: str, train_cases, sections: dict[str, dict], history_of,
          recipe: Recipe | None = None, log=print) -> Examiner:
    """Fit on cases whose letters are public before the test window; tune on the newest slice.

    sections: case_id -> cached filing sections. history_of(case) -> letters public before the
    case's filing date (point-in-time).
    """
    r = recipe or Recipe()
    t0 = time.time()
    cases = sorted(train_cases, key=lambda c: c.filing_date)
    texts = {c.case_id: filing_text(sections.get(c.case_id), r) for c in cases}
    cut = int(len(cases) * (1 - r.val_fraction))
    fit, val = cases[:cut], cases[cut:]
    val_priors = [priors(c, history_of(c), r) for c in val]

    probe = Examiner("tune", recipe=r)
    Y_fit, Y_all = _labels(fit), _labels(cases)
    use_emb = max(r.embed_grid) > 0 and any("__emb__" in (sections.get(c.case_id) or {})
                                            for c in cases)
    G = (np.array([gap_features(sections.get(c.case_id)) for c in cases])
         if r.gaps else None)
    vec = probe._vectorizer()
    try:
        X_fit = _with_gaps(vec.fit_transform([texts[c.case_id] for c in fit]),
                           None if G is None else G[:cut], r)   # fitted once, reused per C
        X_val = _with_gaps(vec.transform([texts[c.case_id] for c in val]),
                           None if G is None else G[cut:], r)
    except ValueError:
        # the recipe selected no usable text (e.g. sections these filings lack)
        X_fit = X_val = None
        if not use_emb:
            log("no usable filing text for this recipe; falling back to priors only")
            ex = Examiner(version, recipe=r, weight_text=0.0)
            ex.meta = {"version": version, "recipe": r.to_dict(), "trained_on": len(cases),
                       "train_window": [cases[0].filing_date, cases[-1].filing_date],
                       "val_f1": 0.0, "val_mrr": 0.0, "weight_text": 0.0, "C": None,
                       "embed_share": 0.0, "with_text": 0,
                       "train_secs": round(time.time() - t0, 1)}
            return ex
        log("no usable word-count text; using passage embeddings as the text signal")
    grid_a = r.embed_grid if use_emb else (0.0,)
    if X_fit is None:
        grid_a = tuple(x for x in grid_a if x > 0) or (1.0,)
    if use_emb:
        E = _emb_matrix(cases, sections)
        probe._fit_emb(E[:cut], Y_fit)
        ep_val = probe.emb_probs(E[cut:])
    best = ((-1.0, -1.0), 0.5, 1.0, 0.0)
    for C in (r.c_grid if X_fit is not None else (r.c_grid[0],)):
        probe.C = C
        if X_fit is not None:
            probe._fit_models(X_fit, Y_fit)
            tp0 = probe.probs_from_matrix(X_val)
        else:
            tp0 = np.zeros((len(val), len(LABELS)))
        for a in grid_a:
            tp = (1 - a) * tp0 + a * ep_val if a else tp0
            for w in r.weight_grid:
                probe.weight_text = w
                s = _tuning_score([probe.rank(tp[i], val_priors[i]) for i in range(len(val))],
                                  val)
                if s > best[0]:
                    best = (s, w, C, a)
    (f1, mrr), w, C, a = best
    log(f"tuned on {len(val)} validation cases: f1={f1:.3f} mrr={mrr:.3f} weight_text={w} "
        f"C={C} embed_share={a}")

    ex = Examiner(version, recipe=r, weight_text=w, C=C, embed_share=a)
    if X_fit is not None:
        ex.vectorizer = ex._vectorizer()
        ex._fit_models(_with_gaps(ex.vectorizer.fit_transform([texts[c.case_id] for c in cases]),
                                  G, r), Y_all)
    else:
        ex.base_rates = {t: float(Y_all[:, j].mean()) for j, t in enumerate(LABELS)}
    if a:
        ex._fit_emb(E, Y_all)
    ex.meta = {"version": version, "recipe": r.to_dict(), "trained_on": len(cases),
               "train_window": [cases[0].filing_date, cases[-1].filing_date],
               "val_f1": round(f1, 3), "val_mrr": round(mrr, 3), "weight_text": w, "C": C,
               "embed_share": a,
               "with_text": sum(bool(texts[c.case_id]) for c in cases),
               "train_secs": round(time.time() - t0, 1)}
    return ex
