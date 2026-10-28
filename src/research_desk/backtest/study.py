"""Backtest: does risk-language deterioration in a 10-K predict later excess returns?

Research only, not investment advice.

Point-in-time rules, enforced in code and tested:
  - a filing's signal uses only that filing and the previous 10-K (both filed on/before it);
  - returns start at the first close strictly AFTER the filing date, so a same-day reaction
    the signal could not have known about is excluded;
  - the benchmark (SPY) is measured over exactly the same window.
"""
import csv
import itertools
import math
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from ..graph.risks import RiskFactor, diff_risks


@dataclass(frozen=True)
class Observation:
    ticker: str
    accession: str
    filing_date: str
    prev_filing_date: str
    n_risks: int
    added: int
    removed: int
    changed: int
    signal: float          # risk deterioration score
    fwd_return: float | None = None
    fwd_excess: float | None = None


def deterioration(old: list[RiskFactor], new: list[RiskFactor]) -> dict:
    """Signal = (added + 0.5 * changed) / risks in the old filing.

    Added risk factors weigh most; rewritten ones count half; removals are tracked but do
    not count as deterioration.
    """
    ch = diff_risks(old, new)
    added = sum(c.kind == "added" for c in ch)
    removed = sum(c.kind == "removed" for c in ch)
    changed = sum(c.kind == "changed" for c in ch)
    return {"n_risks": len(new), "added": added, "removed": removed, "changed": changed,
            "signal": round((added + 0.5 * changed) / max(1, len(old)), 4)}


def observations(ticker: str, filings: list[tuple[str, str, list[RiskFactor]]]
                 ) -> list[Observation]:
    """filings: (filing_date, accession, risk factors), any order."""
    fs = sorted(filings, key=lambda f: f[0])
    out = []
    for (d0, _, old), (d1, acc, new) in itertools.pairwise(fs):
        assert d0 < d1, "signal may only compare against an earlier filing"
        out.append(Observation(ticker, acc, d1, d0, **deterioration(old, new)))
    return out


Prices = dict[str, list[tuple[str, float]]]   # ticker -> [(YYYY-MM-DD, adj close)], ascending


def forward_return(px: list[tuple[str, float]], after: str, days: int) -> float | None:
    """Return from the first close strictly after `after` to `days` trading days later."""
    i = next((k for k, (d, _) in enumerate(px) if d > after), None)
    if i is None or i + days >= len(px):
        return None
    return px[i + days][1] / px[i][1] - 1


def attach_returns(obs: list[Observation], prices: Prices, days: int, bench: str = "SPY"
                   ) -> list[Observation]:
    out = []
    for o in obs:
        r = forward_return(prices.get(o.ticker, []), o.filing_date, days)
        b = forward_return(prices.get(bench, []), o.filing_date, days)
        out.append(Observation(**{**asdict(o), "fwd_return": r,
                                  "fwd_excess": None if r is None or b is None else r - b}))
    return out


def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return cov / (sx * sy) if sx and sy else None


def summarize(obs: list[Observation]) -> dict:
    """Signal vs forward excess return, against the unconditional baseline (all filings)."""
    ok = [o for o in obs if o.fwd_excess is not None]
    if not ok:
        return {"n": 0}
    ok.sort(key=lambda o: o.signal)
    k = max(1, len(ok) // 3)
    low, high = ok[:k], ok[-k:]

    def mean(xs):
        return sum(xs) / len(xs)

    rho = spearman([o.signal for o in ok], [o.fwd_excess for o in ok])
    return {
        "n": len(ok),
        "tickers": len({o.ticker for o in ok}),
        "baseline_mean_excess": round(mean([o.fwd_excess for o in ok]), 4),
        "low_tercile_mean_excess": round(mean([o.fwd_excess for o in low]), 4),
        "high_tercile_mean_excess": round(mean([o.fwd_excess for o in high]), 4),
        "high_minus_low": round(mean([o.fwd_excess for o in high])
                                - mean([o.fwd_excess for o in low]), 4),
        "spearman_signal_vs_excess": None if rho is None else round(rho, 3),
        # rough guide: |rho| below ~2/sqrt(n) is indistinguishable from noise
        "noise_band": round(2 / math.sqrt(len(ok)), 3),
    }


def load_prices(path: Path) -> Prices:
    out: Prices = {}
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.setdefault(row["ticker"], []).append((row["date"], float(row["close"])))
    return {t: sorted(v) for t, v in out.items()}


def fetch_prices(tickers: list[str], start: date, path: Path) -> Prices:
    """Adjusted daily closes from Yahoo Finance via yfinance, cached to CSV."""
    import yfinance as yf

    syms = sorted(set(tickers) | {"SPY"})
    df = yf.download([s.replace(".", "-") for s in syms], start=start.isoformat(),
                     auto_adjust=True, progress=False)["Close"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ticker", "date", "close"])
        for col in df.columns:
            for d, v in df[col].dropna().items():
                w.writerow([col, d.date().isoformat(), f"{v:.6f}"])
    return load_prices(path)
