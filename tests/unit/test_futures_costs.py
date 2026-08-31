"""Invariant checks for the futures cost table (T1 Phase A5).

config/futures_costs.csv is built by scripts/research/futures/a5_cost_table.py
from the spec table, the empirical BID_ASK spread snapshot and the
hand-transcribed IBKR fee schedule. These tests catch arithmetic and join
regressions, not source accuracy.
"""

from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

ROOT = Path(__file__).resolve().parents[2] / "config"
COSTS = ROOT / "futures_costs.csv"
SPECS = ROOT / "futures_specs.csv"


@pytest.fixture(scope="module")
def costs() -> "pd.DataFrame":
    if not COSTS.exists():
        pytest.skip("futures_costs.csv not yet assembled (Phase A5 pending)")
    return pd.read_csv(COSTS)


def test_covers_every_spec_row(costs):
    specs = pd.read_csv(SPECS)
    assert set(costs["code"]) == set(specs["code"])
    assert costs["code"].is_unique


def test_round_trip_arithmetic(costs):
    rows = costs.dropna(subset=["commission_usd", "exchange_fee_usd",
                                "regulatory_fee_usd", "spread_median_usd"])
    assert len(rows) > 0
    fees = 2 * (rows["commission_usd"] + rows["exchange_fee_usd"] + rows["regulatory_fee_usd"])
    assert (fees - rows["rt_fees_usd"]).abs().max() < 1e-9
    assert ((fees + rows["spread_median_usd"]) - rows["rt_cost_usd"]).abs().max() < 1e-9
    bp = rows["rt_cost_usd"] / (rows["last_price"] * rows["multiplier"]) * 1e4
    assert (bp - rows["rt_cost_bp"]).abs().max() < 1e-6


def test_spreads_are_at_least_one_tick(costs):
    """A quoted spread below one tick is impossible — it would mean the
    BID_ASK bar convention (open=bid, close=ask) was misread."""
    rows = costs.dropna(subset=["spread_median_ticks"])
    assert (rows["spread_median_ticks"] >= 1.0 - 1e-9).all()


def test_missing_fees_are_annotated(costs):
    """Every row lacking a fee component must say why in fee_note."""
    missing = costs[costs[["commission_usd", "exchange_fee_usd"]].isna().any(axis=1)]
    assert missing["fee_note"].notna().all(), missing["code"].tolist()
