"""The Examiner as a product: examine a company's latest report, or a draft, with the champion.

Stateless by design: nothing a user submits is stored, logged or learned from. The model learns
only from official SEC letters (which cannot be poisoned by users), and the only state on disk
is the versioned model registry and the public-letter corpus.
"""
import time
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from pathlib import Path

from ..edgar.client import SUBMISSIONS_URL, EdgarClient
from ..judge.cases import Case, history_before
from .embed import DESCRIPTIONS
from .filings import extract
from .gaps import gaps_report
from .improve import Registry
from .letters import PERIODIC
from .model import Examiner, _letter_topics

TOP_K = 5
MAX_DRAFT = 2_000_000       # characters


LABELS = {"non_gaap": "Non-GAAP measures", "revenue_recognition": "Revenue recognition",
          "segments": "Segment reporting", "mdna_drivers": "MD&A: drivers of results",
          "known_trends": "Known trends and uncertainties", "liquidity": "Liquidity and capital",
          "critical_estimates": "Critical accounting estimates", "income_taxes": "Income taxes",
          "impairment": "Impairment and goodwill", "climate": "Climate", "cybersecurity":
          "Cybersecurity", "legal_contingencies": "Legal contingencies", "controls":
          "Internal controls", "kpis": "Key performance metrics", "geopolitical":
          "China, Russia and sanctions", "crypto": "Crypto assets", "presentation":
          "Financial statement presentation", "audit_exhibits": "Audit report and exhibits",
          "governance_proxy": "Governance and proxy", "business_disclosure": "Business description",
          "financial_instruments": "Financial instruments and fair value", "mining_reserves":
          "Mining reserves", "risk_factors": "Risk factors"}


def _label(t: str) -> str:
    return LABELS.get(t, t.replace("_", " ").capitalize())


@dataclass
class ExaminerService:
    models_root: Path
    letters_path: Path
    edgar: EdgarClient | None = None

    @cached_property
    def registry(self) -> Registry:
        return Registry(self.models_root)

    @cached_property
    def records(self) -> list[dict]:
        from ..judge.harness import load_records

        return load_records(self.letters_path) if self.letters_path.exists() else []

    _model: Examiner | None = None
    _model_version: str | None = None

    def model(self) -> Examiner:
        champ = self.registry.state()["champion"]
        if champ is None:
            raise LookupError("no champion model yet: run `desk examiner-improve`")
        if self._model_version != champ:        # picks up promotions and rollbacks
            self._model, self._model_version = Examiner.load(self.models_root, champ), champ
        return self._model

    # --- examining ---------------------------------------------------------------------------
    def _result(self, case: Case, sections: dict[str, str], t0: float) -> dict:
        ex = self.model()
        history = history_before(self.records, case.filing_date)
        rows = ex.explain(case, history, sections)
        gaps = gaps_report(sections)
        past = sorted((r["letter"] for r in history if r["letter"]["cik"] == case.cik),
                      key=lambda L: L["letter_date"], reverse=True)
        top = [{**r, "label": _label(r["topic"]), "about": DESCRIPTIONS.get(r["topic"], ""),
                "missing": gaps.get(r["topic"], [])} for r in rows[:TOP_K]]
        return {
            "model": ex.version,
            "filing": {"company": case.company, "form": case.form, "filed": case.filing_date,
                       "period": case.period, "url": case.filing_url, "sic": case.sic},
            "predictions": top,
            "others": [{"topic": r["topic"], "label": _label(r["topic"]), "score": r["score"]}
                       for r in rows[TOP_K:]],
            "past_letters": [{"date": L["letter_date"], "topics": sorted(_letter_topics(L)),
                              "comments": len(L["comments"])} for L in past[:5]],
            "sections_read": sorted(k for k in sections if not k.startswith("__")),
            "secs": round(time.time() - t0, 2),
        }

    def examine_ticker(self, ticker: str) -> dict:
        t0 = time.time()
        edgar = self.edgar or EdgarClient()
        try:
            cik = edgar.cik(ticker)
        except KeyError as e:
            raise LookupError(f"unknown ticker {ticker!r}") from e
        subs = edgar.http.get(SUBMISSIONS_URL.format(cik=cik)).raise_for_status().json()
        filings = [f for f in edgar.filings_cik((cik,), PERIODIC) if not f.form.endswith("/A")]
        if not filings:
            raise LookupError(f"{ticker.upper()} has no 10-K, 10-Q or 20-F on EDGAR")
        f = filings[0]
        sections = extract(edgar.document(f), f.form)
        case = Case(f.accession, cik, subs.get("name", ticker.upper()), str(subs.get("sic", "")),
                    f.form, f.filing_date.isoformat(),
                    f.report_date.isoformat() if f.report_date else None, f.url, "", "", (), ())
        return self._result(case, sections, t0)

    def examine_draft(self, text: str, sic: str = "", form: str = "10-K",
                      company: str = "Draft") -> dict:
        """A draft that is not filed yet. Read in memory only; never stored or used to train."""
        t0 = time.time()
        if not text.strip():
            raise ValueError("draft is empty")
        if len(text) > MAX_DRAFT:
            raise ValueError(f"draft is over {MAX_DRAFT:,} characters")
        sections = {"body": text}
        case = Case("draft", -1, company, sic, form, date.today().isoformat(), None, "", "", "",
                    (), ())
        return self._result(case, sections, t0)

    # --- the self-improvement record ---------------------------------------------------------
    def status(self) -> dict:
        from ..judge.harness import IntegrityError, verify

        try:
            verify()
            sealed = True
        except IntegrityError:
            sealed = False
        state = self.registry.state()
        champ = state["champion"]
        meta = self.registry.meta(champ) if champ else {}

        def window(name: str) -> dict:
            w = meta.get(name, {})
            return {"f1": w.get("overall", {}).get("f1"), "n": w.get("overall", {}).get("n"),
                    "baselines": {k: v.get("f1") for k, v in meta.get(f"{name}_baselines",
                                                                     {}).items()}}

        recall = meta.get("holdout", {}).get("topic_recall", {})
        return {
            "champion": champ, "lineage": state.get("lineage", []), "judge_sealed": sealed,
            "selection": window("selection"), "holdout": window("holdout"),
            "trained_on": meta.get("trained_on"), "train_window": meta.get("train_window"),
            "topic_recall": sorted(({"topic": t, "label": _label(t), **v} for t, v in
                                    recall.items() if v.get("n")), key=lambda r: -r["n"]),
            "attempts": [{k: a.get(k) for k in ("time", "version", "parent", "changes",
                                                "rationale", "selection_f1", "holdout_f1",
                                                "decision", "reason")}
                         for a in reversed(self.registry.attempts())],
        }
