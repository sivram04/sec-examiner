"""Risk factors: split Item 1A into individual factors and diff them across filings.

In 10-Ks each factor opens with a one-sentence headline paragraph (bold or italic in the HTML)
followed by longer explanatory paragraphs; short lines without a full stop are category
headers ("Risks Related to Our Industry").
"""
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class RiskFactor:
    category: str
    headline: str
    body: str


@dataclass(frozen=True)
class RiskChange:
    kind: str            # added | removed | changed | unchanged
    old: RiskFactor | None
    new: RiskFactor | None
    similarity: float    # headline+body similarity between old and new (0..1)


def _is_headline(p: str, nxt: str | None) -> bool:
    return 40 <= len(p) <= 500 and p.rstrip().endswith((".", "?")) and (
        nxt is not None and len(nxt) > len(p))


def _is_category(p: str) -> bool:
    return len(p) < 120 and not p.rstrip().endswith((".", "?", ":")) and p[:1].isupper()


# boilerplate lead-in ("The following risk factors should be considered...")
INTRO_RE = re.compile(r"^(the following|in addition to the other information)\b.*risk", re.IGNORECASE)
# category headers: "Business and Industry Risks", "Risks Related to Our Industry", "Workforce risks"
CATEGORY_RE = re.compile(r"^(?!.*[.?]\s*$)(?=.{0,100}$)(.*\brisks?\b\s*:?\s*$|risks?\s+(related|relating)"
                         r"\s+to\b.*)", re.IGNORECASE)
BULLET_RE = re.compile(r"^[•●▪–—\-*·]\s*")


def split_risk_factors(text: str, headings: list[str] | None = None) -> list[RiskFactor]:
    """Split Item 1A text into factors.

    headings: the section's bold/italic paragraphs from the parser. When the filer formats
    headlines that way (nearly all do) they are the headline signal; the text heuristic is
    only the fallback. Bullets (the "Risk Factors Summary" list) are never headlines.
    """
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    emph = set(headings or [])
    use_emph = len(emph) >= 5
    out: list[RiskFactor] = []
    category, head, body = "", None, []
    for i, p in enumerate(paras):
        nxt = paras[i + 1] if i + 1 < len(paras) else None
        bold = p in emph
        if use_emph and bold:
            p = BULLET_RE.sub("", p)  # some filers (MMM) mark bold headlines with "*"
        if (BULLET_RE.match(p) and not (use_emph and bold)) or not p[:1].isupper() \
                or INTRO_RE.match(p):
            is_head = False
        elif use_emph:
            # bold, and either a sentence or a Title Case / ALL CAPS line (AMZN, PFE)
            # that isn't a category header like "Interest Rate Risks"
            is_head = bold and len(p) >= 12 and not CATEGORY_RE.search(p) and (
                p.rstrip().endswith((".", "?"))
                or (not p.rstrip().endswith(":") and nxt is not None and len(nxt) > len(p)))
        else:
            is_head = _is_headline(p, nxt)
        if use_emph:
            is_cat = not is_head and bold and bool(CATEGORY_RE.search(p))
        else:
            is_cat = not is_head and _is_category(p) and bool(nxt) and not _is_category(nxt)
        if is_cat:
            if head:
                out.append(RiskFactor(category, head, "\n\n".join(body)))
                head, body = None, []
            category = p
        elif is_head:
            if head:
                out.append(RiskFactor(category, head, "\n\n".join(body)))
            head, body = p, []
        elif head:
            body.append(p)
    if head:
        out.append(RiskFactor(category, head, "\n\n".join(body)))
    return out


def _tokens(s: str) -> set[str]:
    return set(WORD_RE.findall(s.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def diff_risks(old: list[RiskFactor], new: list[RiskFactor], match_at: float = 0.5,
               same_at: float = 0.97) -> list[RiskChange]:
    """Greedy best-match by headline token overlap, then body similarity decides changed vs
    unchanged. Deterministic: no LLM is involved in deciding what changed.
    """
    pairs = sorted(((_jaccard(_tokens(o.headline), _tokens(n.headline)), i, j)
                    for i, o in enumerate(old) for j, n in enumerate(new)), reverse=True)
    used_o: set[int] = set()
    used_n: set[int] = set()
    out: list[RiskChange] = []
    for score, i, j in pairs:
        if score < match_at:
            break
        if i in used_o or j in used_n:
            continue
        used_o.add(i)
        used_n.add(j)
        o, n = old[i], new[j]
        sim = SequenceMatcher(None, o.headline + o.body, n.headline + n.body,
                              autojunk=False).quick_ratio()
        out.append(RiskChange("unchanged" if sim >= same_at else "changed", o, n, round(sim, 3)))
    out += [RiskChange("removed", o, None, 0.0) for i, o in enumerate(old) if i not in used_o]
    out += [RiskChange("added", None, n, 0.0) for j, n in enumerate(new) if j not in used_n]
    order = {"added": 0, "removed": 1, "changed": 2, "unchanged": 3}
    return sorted(out, key=lambda c: (order[c.kind], c.similarity))


def stable_snapshots(filings: list[tuple[str, str, list[RiskFactor]]]
                     ) -> list[tuple[str, str, dict[str, str]]]:
    """Give each risk a stable identity across filings: a reworded factor keeps the headline
    it was first seen with, so the temporal graph shows one continuing edge, not churn.
    Returns (filing_date, accession, {identity: current headline + body excerpt}).
    """
    out: list[tuple[str, str, dict[str, str]]] = []
    prev: list[RiskFactor] = []
    prev_ids: dict[int, str] = {}
    for day, acc, rfs in sorted(filings, key=lambda f: f[0]):
        ids: dict[int, str] = {}
        by_obj = {id(r): i for i, r in enumerate(prev)}
        for c in diff_risks(prev, rfs):
            if c.new is None:
                continue
            j = next(k for k, r in enumerate(rfs) if r is c.new)
            ids[j] = prev_ids[by_obj[id(c.old)]] if c.old is not None else c.new.headline
        out.append((day, acc, {ids[j]: f"{r.headline}\n\n{r.body[:400]}"
                               for j, r in enumerate(rfs)}))
        prev, prev_ids = rfs, ids
    return out
