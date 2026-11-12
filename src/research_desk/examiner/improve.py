"""Self-improvement loop: diagnose -> propose -> train -> judge -> promote or reject -> audit.

No person picks the changes. The loop reads the judge's report on the current champion, finds
what is wrong, has an LLM (or a rule-based fallback) propose a recipe change inside
RECIPE_SPACE, trains the candidate, and promotes it only if the sealed judge passes it and it
beats the champion on the selection window. The holdout is recorded but never used to choose.
Every attempt, promoted or not, is appended to an audit log.
"""
import json
import time
from collections.abc import Callable
from pathlib import Path

from .model import RECIPE_SPACE, Recipe, validate
from .run import train_and_grade

MIN_GAIN = 0.005   # selection F1 a candidate must add over the champion to replace it


class Registry:
    """champion pointer + append-only audit log, stored as plain files beside the models."""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.state_path = root / "registry.json"
        self.audit_path = root / "audit.jsonl"

    def state(self) -> dict:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        return {"champion": None, "lineage": []}

    def set_champion(self, version: str) -> None:
        s = self.state()
        s["champion"] = version
        s["lineage"].append(version)
        self.state_path.write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")

    def rollback(self) -> str | None:
        """Revert to the previous promoted version (e.g. if the champion degrades in use)."""
        s = self.state()
        if len(s["lineage"]) < 2:
            return None
        s["lineage"].pop()
        s["champion"] = s["lineage"][-1]
        self.state_path.write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")
        self.log({"event": "rollback", "champion": s["champion"]})
        return s["champion"]

    def log(self, entry: dict) -> None:
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S"), **entry}) + "\n")

    def attempts(self) -> list[dict]:
        if not self.audit_path.exists():
            return []
        return [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8")
                .splitlines() if line.strip() and '"attempt"' in line]

    def meta(self, version: str) -> dict:
        return json.loads((self.root / version / "meta.json").read_text(encoding="utf-8"))

    def next_version(self) -> str:
        n = [int(p.name[1:]) for p in self.root.glob("v*") if p.name[1:].isdigit()]
        return f"v{max(n, default=0) + 1}"


def diagnose(meta: dict) -> list[dict]:
    """Turn the judge's report on a version into concrete, actionable findings."""
    out = []
    sel = meta["selection"]
    f1 = sel["overall"]["f1"]
    for topic, v in sel["topic_recall"].items():
        if v["n"] >= 10 and v["recall"] < 0.4:
            out.append({"kind": "weak_topic", "topic": topic, "recall": v["recall"], "n": v["n"]})
    if meta["val_f1"] - f1 > 0.08:
        out.append({"kind": "validation_overstates", "val_f1": meta["val_f1"], "selection_f1": f1,
                    "hint": "validation slice may be too small or unrepresentative"})
    if meta["weight_text"] in (0.0, 1.0):
        out.append({"kind": "signal_unused", "weight_text": meta["weight_text"],
                    "hint": "one of text / priors is ignored; the blend or prior weights may be off"})
    if sel["mean_secs"] > 5:
        out.append({"kind": "slow", "mean_secs": sel["mean_secs"]})
    if meta.get("train_secs", 0) > 600:
        out.append({"kind": "slow_training", "train_secs": meta["train_secs"]})
    if not meta["selection_gate"]["passed"]:
        out.append({"kind": "gate_fail", "checks": meta["selection_gate"]["checks"]})
    return out


# rule-based fallback: findings -> recipe changes to try, most promising first
FALLBACK = [
    # paraphrase-aware signal for topics word counts miss (needs `desk examiner-embed`)
    ("weak_topic", {"embed_grid": [0.0, 0.25, 0.5, 0.75]}),
    # omissions the staff asks about: topic discussed, expected disclosure missing
    ("weak_topic", {"gaps": True}),
    ("validation_overstates", {"val_fraction": 0.3}),
    ("signal_unused", {"weight_grid": [0.5, 0.6, 0.7, 0.8, 0.9]}),
    ("weak_topic", {"ngram_max": 1, "max_features": 100_000, "min_df": 2}),
    ("weak_topic", {"max_chars": 400_000}),
    ("signal_unused", {"prior_company": 0.6, "prior_industry": 0.3, "prior_recent": 0.1}),
    ("slow_training", {"max_chars": 120_000, "max_features": 30_000}),
    ("slow", {"max_features": 30_000}),
    ("weak_topic", {"c_grid": [1.0, 3.0, 10.0]}),
    ("weak_topic", {"class_weight": "none"}),
    ("validation_overstates", {"recent_days": 180}),
]


def _tried(changes: dict, attempts: list[dict], parent: str) -> bool:
    key = json.dumps(changes, sort_keys=True)
    return any(a.get("parent") == parent and json.dumps(a.get("changes"), sort_keys=True) == key
               for a in attempts)


def rule_propose(findings: list[dict], attempts: list[dict], parent: str) -> tuple[dict, str]:
    kinds = {f["kind"] for f in findings}
    for kind, changes in FALLBACK:
        if kind in kinds and not _tried(changes, attempts, parent):
            return changes, f"rule: address {kind}"
    for _kind, changes in FALLBACK:   # nothing matched: explore anything untried
        if not _tried(changes, attempts, parent):
            return changes, "rule: explore untried change"
    return {}, "rule: search space exhausted"


PROMPT = """You improve a machine-learning system that predicts which topics the SEC staff will
raise in comment letters on a company's 10-K/20-F. You may only change fields of its Recipe.

Allowed fields and ranges:
{space}

Current recipe:
{recipe}

Judge findings on the current version (selection window):
{findings}

Per-topic recall on the selection window (n = cases where the SEC raised it):
{topics}

Previous attempts from this parent and their outcomes (do not repeat them):
{attempts}

Propose ONE change set likely to raise F1@5 on unseen filings. Prefer small, targeted changes
that address the findings; avoid changes that only help the validation slice.
Reply with JSON only: {{"changes": {{<field>: <value>, ...}}, "rationale": "<one sentence>"}}"""


def llm_propose(findings, recipe: Recipe, meta: dict, attempts: list[dict], parent: str,
                llm: Callable[[str, str], str]) -> tuple[dict, str]:
    from ..agents.desk import parse_json

    past = [{"changes": a["changes"], "decision": a["decision"],
             "selection_f1": a.get("selection_f1")} for a in attempts if a.get("parent") == parent]
    topics = {t: v for t, v in list(meta["selection"]["topic_recall"].items())[:15]}
    reply = llm("You are a careful ML engineer. Reply with JSON only.", PROMPT.format(
        space=json.dumps(RECIPE_SPACE, indent=1), recipe=json.dumps(recipe.to_dict()),
        findings=json.dumps(findings), topics=json.dumps(topics), attempts=json.dumps(past)))
    out = parse_json(reply)
    changes = validate(out.get("changes") or {})
    if not changes or _tried(changes, attempts, parent):
        raise ValueError("empty or repeated proposal")
    return changes, "llm: " + str(out.get("rationale", ""))[:300]


def step(records: list[dict], filings_root: Path, reg: Registry,
         llm: Callable[[str, str], str] | None = None, log=print,
         seed: tuple[Recipe, str] | None = None) -> dict:
    """One improvement attempt. Bootstraps a champion (default or seed recipe) if none exists."""
    state = reg.state()
    if state["champion"] is None:
        v = reg.next_version()
        recipe, why = seed or (Recipe(), "default recipe")
        meta = train_and_grade(records, filings_root, reg.root, v, recipe, log=log)
        passed = meta["selection_gate"]["passed"]
        entry = {"attempt": True, "version": v, "parent": None, "changes": {},
                 "rationale": f"bootstrap: {why}", "findings": [],
                 "selection_f1": meta["selection"]["overall"]["f1"],
                 "holdout_f1": meta["holdout"]["overall"]["f1"],
                 "decision": "promote" if passed else "reject",
                 "reason": "passes the judge" if passed else "fails the judge gate"}
        reg.log(entry)
        if passed:
            reg.set_champion(v)
        return entry

    parent = state["champion"]
    pmeta = reg.meta(parent)
    findings = diagnose(pmeta)
    attempts = reg.attempts()
    recipe = Recipe.from_dict(pmeta["recipe"])
    changes, why = {}, ""
    if llm is not None:
        try:
            changes, why = llm_propose(findings, recipe, pmeta, attempts, parent, llm)
        except Exception as e:  # noqa: BLE001 - any LLM failure falls back to rules
            log(f"llm proposal unusable ({e!r}); using rule fallback"[:200])
    if not changes:
        changes, why = rule_propose(findings, attempts, parent)
    if not changes:
        entry = {"attempt": True, "version": None, "parent": parent, "changes": {},
                 "rationale": why, "findings": findings, "decision": "stop",
                 "reason": "no untried change left"}
        reg.log(entry)
        return entry

    cand = Recipe.from_dict({**recipe.to_dict(), **changes})
    return _evaluate(records, filings_root, reg, parent, pmeta, cand, changes, why, findings, log)


def _evaluate(records, filings_root: Path, reg: Registry, parent: str, pmeta: dict,
              cand: Recipe, changes: dict, why: str, findings: list, log=print,
              extra: dict | None = None) -> dict:
    """Train a candidate, let the judge grade it, promote only if it passes and beats the parent."""
    v = reg.next_version()
    log(f"{v}: from {parent}, trying {changes} ({why})")
    t0 = time.time()
    base = {"attempt": True, "version": v, "parent": parent, "changes": changes,
            "rationale": why, "findings": findings, **(extra or {})}
    try:
        meta = train_and_grade(records, filings_root, reg.root, v, cand, log=log)
    except Exception as e:  # noqa: BLE001 - a crashing candidate is a rejected candidate
        entry = {**base, "decision": "reject", "reason": f"crashed: {e!r}"[:300],
                 "secs": round(time.time() - t0, 1)}
        reg.log(entry)
        return entry

    sel_f1 = meta["selection"]["overall"]["f1"]
    champ_f1 = pmeta["selection"]["overall"]["f1"]
    passed = meta["selection_gate"]["passed"]
    better = sel_f1 >= champ_f1 + MIN_GAIN
    decision = "promote" if passed and better else "reject"
    reason = ("passes the judge and beats the champion" if decision == "promote" else
              "fails the judge gate" if not passed else
              f"no gain over champion ({sel_f1:.3f} vs {champ_f1:.3f}, need +{MIN_GAIN})")
    entry = {**base, "selection_f1": sel_f1, "champion_f1": champ_f1,
             "holdout_f1": meta["holdout"]["overall"]["f1"],
             "decision": decision, "reason": reason, "secs": round(time.time() - t0, 1)}
    reg.log(entry)
    if decision == "promote":
        reg.set_champion(v)
    log(f"{v}: {decision} ({reason})")
    return entry


CODE_PROMPT = """You improve a machine-learning system that predicts which topics SEC staff will raise
in comment letters on a company's 10-K, 10-Q or 20-F. It already uses word counts (TF-IDF) and
the SEC's past letters. Write ONE new Python function that extracts extra numeric features from
a filing's text, aimed at the topics it currently misses:

{weak}

What staff usually expect with those topics (absence of these often triggers a comment):
{expected}

Plugins already tried for this champion (do not repeat their idea):
{tried}

Rules (code that breaks any rule is discarded before it runs):
- Exactly: def features(text: str) -> dict[str, float]. `text` is the whole filing, lowercased,
  up to 400,000 characters. Return at most 16 numeric features with short snake_case names.
- Only `import re` and `import math` are allowed. No files, network, eval/exec, getattr,
  str.format, dunder or underscore attributes, classes, or global state.
- Must be fast (well under 1 second per filing) and deterministic.
- Prefer features that capture what is MISSING or unusually thin (e.g. a topic is discussed but
  its expected disclosure is absent), normalised by text length.

Reply with one ```python code block containing only the function (and its imports), then one
line starting with RATIONALE: explaining the idea in one sentence."""


def code_propose(pmeta: dict, attempts: list[dict], parent: str, llm) -> tuple[str, str]:
    """Ask the LLM for a feature plugin; return (code, rationale)."""
    import re as _re

    from .gaps import NAMES

    recall = pmeta.get("selection", {}).get("topic_recall", {})
    weak = sorted(((t, v) for t, v in recall.items() if v.get("n", 0) >= 10
                   and v.get("recall", 1) < 0.5), key=lambda x: x[1]["recall"])[:6]
    tried = [a for a in attempts if a.get("parent") == parent and a.get("code_summary")]
    prompt = CODE_PROMPT.format(
        weak="\n".join(f"- {t}: recall {v['recall']:.2f} on {v['n']} filings" for t, v in weak)
        or "- (none below 0.5; improve overall ranking)",
        expected="\n".join(f"- {t}: {', '.join(NAMES.get(t, []))}" for t, _ in weak
                           if NAMES.get(t)) or "- (no rules for these topics)",
        tried="\n".join(f"- {a['code_summary']} -> {a['decision']} ({a['reason']})"
                        for a in tried) or "- none yet")
    out = llm("You write small, safe, deterministic Python feature extractors.", prompt)
    m = _re.search(r"```(?:python)?\s*\n(.*?)```", out, _re.DOTALL)
    if not m:
        raise ValueError("no python code block in the reply")
    why = _re.search(r"RATIONALE:\s*(.+)", out)
    return m.group(1).strip() + "\n", (why.group(1).strip() if why else "")[:300]


def code_step(records: list[dict], filings_root: Path, reg: Registry, llm, log=print) -> dict:
    """One attempt where the system writes code: LLM plugin -> safety check -> sandbox -> judge."""
    from ..judge.cases import cases_from
    from .plugins import UnsafeCode, extract, plugin_id

    state = reg.state()
    parent = state["champion"]
    if parent is None:
        raise RuntimeError("no champion yet: run a normal step first")
    pmeta = reg.meta(parent)
    attempts = reg.attempts()
    code, why = code_propose(pmeta, attempts, parent, llm)
    pid = plugin_id(code)
    summary = why or "generated feature plugin"
    extra = {"code_summary": summary, "code_path": f"plugins/{pid}/code.py",
             "code_sha": pid[1:]}
    log(f"generated plugin {pid}: {summary}")
    try:
        case_ids = sorted({c.case_id for c in cases_from(records)})
        extract(code, filings_root, case_ids, reg.root.parent / "plugins", log=log)
    except UnsafeCode as e:
        (reg.root.parent / "plugins" / pid).mkdir(parents=True, exist_ok=True)
        (reg.root.parent / "plugins" / pid / "code.py").write_text(code, encoding="utf-8")
        entry = {"attempt": True, "version": None, "parent": parent, "changes": {"plugin": pid},
                 "rationale": "llm-code: " + summary, "findings": [], **extra,
                 "decision": "reject", "reason": f"blocked before training: {e}"[:300]}
        reg.log(entry)
        log(f"{pid}: rejected before training ({e})")
        return entry
    recipe = Recipe.from_dict(pmeta["recipe"])
    cand = Recipe.from_dict({**recipe.to_dict(), "plugin": pid})
    return _evaluate(records, filings_root, reg, parent, pmeta, cand, {"plugin": pid},
                     "llm-code: " + summary, [], log, extra)


def run(records, filings_root: Path, reg: Registry, iterations: int, llm=None,
        max_minutes: float = 120, log=print, seed=None) -> list[dict]:
    """Up to `iterations` attempts within a time budget; stops early when nothing is left."""
    out, t0 = [], time.time()
    for _ in range(iterations):
        if (time.time() - t0) / 60 > max_minutes:
            log("time budget reached")
            break
        e = step(records, filings_root, reg, llm, log, seed=seed)
        out.append(e)
        if e["decision"] == "stop":
            break
    return out
