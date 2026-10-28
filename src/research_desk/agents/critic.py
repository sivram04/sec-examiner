"""Critic / verifier: rejects any claim that isn't backed by its citations.

Deterministic checks (no LLM):
  1. every claim cites at least one evidence id that exists;
  2. every number in the claim appears in a cited passage or in a cited quant result
     (so the LLM cannot introduce arithmetic of its own: N2);
An optional LLM judge then checks that the cited text actually supports the wording.
"""
import re
from collections.abc import Callable
from dataclasses import dataclass, field

# 4.6, 13, 1,234.5, 18.3%, $4.5 billion -> numeric tokens; years are ignored (dates, not data)
NUM_RE = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])\d+(?:\.\d+)?")
YEAR_RE = re.compile(r"^(19|20)\d{2}$")


@dataclass
class Claim:
    text: str
    citations: list[str]                 # evidence ids: chunk ids or "quant:<name>"
    stance: str = "neutral"              # bull | bear | neutral


@dataclass
class Verdict:
    claim: Claim
    ok: bool
    reasons: list[str] = field(default_factory=list)


# ISO dates in evidence labels ("period ending 2025-03-31") back the day in "March 31, 2025"
# (only the report period: the filing date says when it was filed, not what it covers)
ISO_DATE_RE = re.compile(r"period ending \d{4}-(\d{2})-(\d{2})\b")


def numbers(text: str) -> set[str]:
    out = set()
    for m in NUM_RE.findall(text):
        n = m.replace(",", "")
        if YEAR_RE.match(n) or n in {"0", "1"}:
            continue
        out.add(_canon(n))
    return out


def _canon(n: str) -> str:
    return n.rstrip("0").rstrip(".") if "." in n else n


SCALES = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}
SCALED_RE = re.compile(r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
                       r"(thousand|million|billion|trillion)\b", re.IGNORECASE)


def _scaled(text: str) -> dict[str, str]:
    """'€500 million' -> {'500': '500000000'}: the same amount written two ways."""
    out = {}
    for num, word in SCALED_RE.findall(text):
        raw = num.replace(",", "")
        out[_canon(raw)] = _canon(f"{float(raw) * SCALES[word.lower()]:.0f}")
    return out


def mentions(text: str) -> list[set[str]]:
    """Each number in text with its equivalent forms; a mention is backed if any form is."""
    sc = _scaled(text)
    return [{n, sc[n]} if n in sc else {n} for n in numbers(text)]


def pool(text: str) -> set[str]:
    """Every form of every number a source states, scaled amounts included."""
    iso = {str(int(part)) for m in ISO_DATE_RE.findall(text) for part in m}
    # ISO dates are labels, not data: their parts must not back arbitrary numbers
    body = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", text)
    return numbers(body) | set(_scaled(body).values()) | iso


def _render(v) -> str:
    """Quant values as text, with a couple of common roundings so 0.4567 matches '45.7'."""
    if isinstance(v, dict):
        return " ".join(_render(x) for x in v.values())
    if isinstance(v, list):
        return " ".join(_render(x) for x in v)
    if isinstance(v, (int, float)):
        f = float(v)
        forms = {f"{f:.0f}", f"{f:.1f}", f"{f:.2f}", f"{f * 100:.1f}", f"{f * 100:.0f}",
                 f"{f / 1e9:.1f}", f"{f / 1e6:.1f}"}
        return " ".join(forms)
    return str(v)


def verify(claims: list[Claim], evidence: dict[str, str], quant: dict[str, dict],
           judge: Callable[[str, str], bool] | None = None) -> list[Verdict]:
    out = []
    for c in claims:
        reasons = []
        cited_text = []
        for cid in c.citations:
            if cid.startswith("quant:"):
                if cid[6:] in quant:
                    cited_text.append(_render(quant[cid[6:]]))
                else:
                    reasons.append(f"unknown quant result {cid}")
            elif cid in evidence:
                cited_text.append(evidence[cid])
            else:
                reasons.append(f"unknown citation {cid}")
        if not c.citations:
            reasons.append("no citation")
        have = pool(" ".join(cited_text))
        missing = sorted(min(forms) for forms in mentions(c.text) if not forms & have)
        if missing:
            reasons.append(f"numbers not in cited sources: {', '.join(missing)}")
        if not reasons and judge and not judge(c.text, "\n---\n".join(cited_text)):
            reasons.append("judge: citation does not support claim")
        out.append(Verdict(c, not reasons, reasons))
    return out
