import pytest

from research_desk.backtest.study import (
    attach_returns,
    deterioration,
    forward_return,
    observations,
    spearman,
    summarize,
)
from research_desk.graph.risks import RiskFactor


def rf(h):
    return RiskFactor("", h, "body " * 50)


A = rf("We depend on a single foundry partner to manufacture our products.")
B = rf("Export controls could restrict sales of our products to China.")
C = rf("New tariffs on imported components could increase our costs.")

PX = [(f"2025-01-{d:02d}", 100.0 + d) for d in range(1, 31)]


def test_deterioration_counts_added_risks():
    d = deterioration([A, B], [A, B, C])
    assert (d["added"], d["removed"], d["signal"]) == (1, 0, 0.5)
    assert deterioration([A, B], [A, B])["signal"] == 0


def test_forward_return_starts_after_filing_day():
    # filed on the 10th: entry is the 11th's close (111), never the 10th's (110)
    assert forward_return(PX, "2025-01-10", 5) == pytest.approx(116 / 111 - 1)
    assert forward_return(PX, "2025-01-28", 5) is None   # not enough future data


def test_no_lookahead_leakage():
    """Changing any price on or before the filing date must not change the result."""
    base = forward_return(PX, "2025-01-10", 5)
    tampered = [(d, p * (3 if d <= "2025-01-10" else 1)) for d, p in PX]
    assert forward_return(tampered, "2025-01-10", 5) == base


def test_observations_only_compare_backwards():
    obs = observations("X", [("2025-02-01", "a2", [A, B, C]), ("2024-02-01", "a1", [A, B])])
    assert len(obs) == 1 and obs[0].prev_filing_date == "2024-02-01" and obs[0].added == 1


def test_excess_vs_benchmark_and_summary():
    obs = observations("X", [("2025-01-01", "a0", [A]), ("2025-01-05", "a1", [A, B]),
                             ("2025-01-09", "a2", [A, B]), ("2025-01-13", "a3", [A, B, C])])
    spy = [(d, 100.0) for d, _ in PX]
    out = attach_returns(obs, {"X": PX, "SPY": spy}, days=3)
    assert all(o.fwd_excess == pytest.approx(o.fwd_return) for o in out)
    s = summarize(out)
    assert s["n"] == 3 and "noise_band" in s


def test_spearman():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 2], [1, 2]) is None
