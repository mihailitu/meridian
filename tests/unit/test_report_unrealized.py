"""Tests for ReportGenerator._get_unrealized_by_strategy.

Mocks the asyncpg connection's fetch() so no real DB is needed.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from axtrade.common import DatabaseConfig
from axtrade.fulltest.report import ReportGenerator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(
    strategy_id: str,
    symbol: str,
    side: str,
    quantity: float,
    avg_entry_price: float,
    last_close: float,
) -> dict:
    """Build a dict matching the columns returned by the SQL query."""
    return {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "side": side,
        "quantity": Decimal(str(quantity)),
        "avg_entry_price": Decimal(str(avg_entry_price)),
        "last_close": Decimal(str(last_close)),
    }


def _make_conn(rows: list[dict]) -> MagicMock:
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=rows)
    return conn


def _make_gen() -> ReportGenerator:
    return ReportGenerator(
        db_config=DatabaseConfig(),
        backtest_db_name="axtrade_backtest_test",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetUnrealizedByStrategy:
    async def test_long_position_positive_pnl(self) -> None:
        rows = [_make_row("strat_a", "AAPL", "long", 41, 100.0, 110.0)]
        gen = _make_gen()
        result = await gen._get_unrealized_by_strategy(_make_conn(rows))
        # pnl = (110 - 100) * 41 * +1 = 410
        assert result == {"strat_a": pytest.approx(410.0)}

    async def test_short_position_negative_pnl(self) -> None:
        rows = [_make_row("strat_a", "AAPL", "short", 41, 100.0, 110.0)]
        gen = _make_gen()
        result = await gen._get_unrealized_by_strategy(_make_conn(rows))
        # pnl = (110 - 100) * 41 * -1 = -410
        assert result == {"strat_a": pytest.approx(-410.0)}

    async def test_two_positions_same_strategy_are_summed(self) -> None:
        rows = [
            _make_row("strat_a", "AAPL", "long", 41, 100.0, 110.0),   # +410
            _make_row("strat_a", "MSFT", "long", 10, 200.0, 210.0),   # +100
        ]
        gen = _make_gen()
        result = await gen._get_unrealized_by_strategy(_make_conn(rows))
        assert result == {"strat_a": pytest.approx(510.0)}

    async def test_two_strategies_keyed_separately(self) -> None:
        rows = [
            _make_row("strat_a", "AAPL", "long", 41, 100.0, 110.0),  # +410
            _make_row("strat_b", "MSFT", "short", 41, 100.0, 110.0), # -410
        ]
        gen = _make_gen()
        result = await gen._get_unrealized_by_strategy(_make_conn(rows))
        assert set(result.keys()) == {"strat_a", "strat_b"}
        assert result["strat_a"] == pytest.approx(410.0)
        assert result["strat_b"] == pytest.approx(-410.0)

    async def test_empty_fetch_returns_empty_dict(self) -> None:
        gen = _make_gen()
        result = await gen._get_unrealized_by_strategy(_make_conn([]))
        assert result == {}
