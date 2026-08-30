"""Invariant checks for the frozen futures contract-spec table (T1 Phase A2).

The table is assembled from primary sources (CME spec pages, IBKR schedule)
— see docs/t1-futures-plan.md §A2. These tests catch arithmetic and schema
regressions, not source accuracy (that is the two-source cross-check's job).
"""

from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

SPECS = Path(__file__).resolve().parents[2] / "config" / "futures_specs.csv"

REQUIRED_COLS = {
    "code", "name", "exchange", "sector", "size_class",
    "multiplier", "tick_size", "tick_value_usd", "source_url",
}


@pytest.fixture(scope="module")
def specs() -> "pd.DataFrame":
    if not SPECS.exists():
        pytest.skip("futures_specs.csv not yet assembled (Phase A2 pending)")
    return pd.read_csv(SPECS)


def test_schema(specs):
    assert REQUIRED_COLS.issubset(specs.columns)
    assert specs["code"].is_unique
    assert specs["size_class"].isin(["micro", "full"]).all()


def test_tick_value_arithmetic(specs):
    """tick_value == multiplier * tick_size for every row with all three."""
    rows = specs.dropna(subset=["multiplier", "tick_size", "tick_value_usd"])
    assert len(rows) > 0
    err = (rows["multiplier"] * rows["tick_size"] - rows["tick_value_usd"]).abs()
    bad = rows.loc[err > 1e-9, "code"].tolist()
    assert not bad, f"tick_value != multiplier*tick_size for {bad}"


def test_every_row_has_a_source(specs):
    assert specs["source_url"].notna().all()
    assert specs["source_url"].str.startswith("http").all()


def test_margin_below_notional(specs):
    """Initial margin must be a fraction of notional, never above it."""
    if "margin_initial_usd" not in specs.columns or "last_price" not in specs.columns:
        pytest.skip("optional margin/price columns absent")
    rows = specs.dropna(subset=["margin_initial_usd", "last_price", "multiplier"])
    if rows.empty:
        pytest.skip("no rows carry both margin and price")
    notional = rows["last_price"] * rows["multiplier"]
    bad = rows.loc[rows["margin_initial_usd"] >= notional, "code"].tolist()
    assert not bad, f"margin >= notional for {bad}"


def test_sector_coverage(specs):
    """Phase A2 targets >=4 sectors (docs/t1-futures-plan.md)."""
    assert specs["sector"].nunique() >= 4
