"""Unit tests for P&L calculation in OrderRepository.

Tests the FIFO matching logic for realized P&L calculation.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from axtrade.oms.repository import OrderRepository


class TestGetDailyRealizedPnl:
    """Tests for OrderRepository.get_daily_realized_pnl() FIFO matching."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        pool = MagicMock()
        pool.acquire = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool: MagicMock) -> OrderRepository:
        return OrderRepository(mock_pool)

    def _make_fill(
        self,
        strategy_id: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        commission: float = 1.0,
        filled_at: datetime | None = None,
    ) -> dict:
        """Helper to create fill records."""
        if filled_at is None:
            filled_at = datetime.now(UTC)
        return {
            "strategy_id": strategy_id,
            "symbol": symbol,
            "side": side,
            "quantity": Decimal(str(quantity)),
            "price": Decimal(str(price)),
            "commission": Decimal(str(commission)),
            "filled_at": filled_at,
        }

    @pytest.mark.asyncio
    async def test_no_fills_returns_zero(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Empty fills should return zero P&L."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_conn.fetch.return_value = []

        pnl = await repo.get_daily_realized_pnl()

        assert pnl == Decimal("0")

    @pytest.mark.asyncio
    async def test_only_buys_returns_zero(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Open positions (only buys) should not count as realized loss."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        now = datetime.now(UTC)
        mock_conn.fetch.return_value = [
            self._make_fill("strat1", "AAPL", "buy", 100, 180.00, filled_at=now),
            self._make_fill("strat1", "AAPL", "buy", 50, 182.00, filled_at=now),
        ]

        pnl = await repo.get_daily_realized_pnl()

        assert pnl == Decimal("0")

    @pytest.mark.asyncio
    async def test_simple_round_trip_profit(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Buy then sell at higher price should show profit."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        now = datetime.now(UTC)
        mock_conn.fetch.return_value = [
            self._make_fill("strat1", "AAPL", "buy", 100, 180.00, 1.0, now - timedelta(minutes=10)),
            self._make_fill("strat1", "AAPL", "sell", 100, 185.00, 1.0, now),
        ]

        pnl = await repo.get_daily_realized_pnl()

        # (185 - 180) * 100 - 2 commission = 498
        assert pnl == Decimal("498")

    @pytest.mark.asyncio
    async def test_simple_round_trip_loss(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Buy then sell at lower price should show loss."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        now = datetime.now(UTC)
        mock_conn.fetch.return_value = [
            self._make_fill("strat1", "AAPL", "buy", 100, 185.00, 1.0, now - timedelta(minutes=10)),
            self._make_fill("strat1", "AAPL", "sell", 100, 180.00, 1.0, now),
        ]

        pnl = await repo.get_daily_realized_pnl()

        # (180 - 185) * 100 - 2 commission = -502
        assert pnl == Decimal("-502")

    @pytest.mark.asyncio
    async def test_fifo_matching_multiple_buys(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """FIFO: sell should match against earliest buy first."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        now = datetime.now(UTC)
        mock_conn.fetch.return_value = [
            self._make_fill("strat1", "AAPL", "buy", 100, 180.00, 1.0, now - timedelta(minutes=30)),
            self._make_fill("strat1", "AAPL", "buy", 100, 190.00, 1.0, now - timedelta(minutes=20)),
            self._make_fill("strat1", "AAPL", "sell", 100, 185.00, 1.0, now),
        ]

        pnl = await repo.get_daily_realized_pnl()

        # Should match against first buy at 180, not second at 190
        # (185 - 180) * 100 - 2 commission = 498
        assert pnl == Decimal("498")

    @pytest.mark.asyncio
    async def test_partial_fill_matching(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Sell quantity less than buy should partially consume buy lot."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        now = datetime.now(UTC)
        mock_conn.fetch.return_value = [
            self._make_fill("strat1", "AAPL", "buy", 100, 180.00, 1.0, now - timedelta(minutes=10)),
            self._make_fill("strat1", "AAPL", "sell", 50, 185.00, 1.0, now),
        ]

        pnl = await repo.get_daily_realized_pnl()

        # (185 - 180) * 50 - 1.0 (full sell comm) - 0.5 (half buy comm) = 248.5
        assert pnl == Decimal("248.5")

    @pytest.mark.asyncio
    async def test_sell_spanning_multiple_buy_lots(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Large sell should consume multiple buy lots in FIFO order."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        now = datetime.now(UTC)
        mock_conn.fetch.return_value = [
            self._make_fill("strat1", "AAPL", "buy", 50, 180.00, 1.0, now - timedelta(minutes=30)),
            self._make_fill("strat1", "AAPL", "buy", 50, 190.00, 1.0, now - timedelta(minutes=20)),
            self._make_fill("strat1", "AAPL", "sell", 100, 185.00, 1.0, now),
        ]

        pnl = await repo.get_daily_realized_pnl()

        # First 50: (185 - 180) * 50 = 250, commission = 1 + 0.5 = 1.5
        # Second 50: (185 - 190) * 50 = -250, commission = 1 + 0.5 = 1.5
        # Total: 250 - 250 - 3 = -3
        assert pnl == Decimal("-3")

    @pytest.mark.asyncio
    async def test_multiple_symbols_tracked_separately(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Each symbol should have its own FIFO queue."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        now = datetime.now(UTC)
        mock_conn.fetch.return_value = [
            self._make_fill("strat1", "AAPL", "buy", 100, 180.00, 1.0, now - timedelta(minutes=30)),
            self._make_fill("strat1", "GOOGL", "buy", 100, 170.00, 1.0, now - timedelta(minutes=20)),
            self._make_fill("strat1", "AAPL", "sell", 100, 185.00, 1.0, now - timedelta(minutes=10)),
            self._make_fill("strat1", "GOOGL", "sell", 100, 175.00, 1.0, now),
        ]

        pnl = await repo.get_daily_realized_pnl()

        # AAPL: (185 - 180) * 100 - 2 = 498
        # GOOGL: (175 - 170) * 100 - 2 = 498
        # Total: 996
        assert pnl == Decimal("996")

    @pytest.mark.asyncio
    async def test_multiple_strategies_tracked_separately(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Each strategy should have its own FIFO queue per symbol."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        now = datetime.now(UTC)
        mock_conn.fetch.return_value = [
            self._make_fill("strat1", "AAPL", "buy", 100, 180.00, 1.0, now - timedelta(minutes=30)),
            self._make_fill("strat2", "AAPL", "buy", 100, 190.00, 1.0, now - timedelta(minutes=20)),
            self._make_fill("strat1", "AAPL", "sell", 100, 185.00, 1.0, now - timedelta(minutes=10)),
            self._make_fill("strat2", "AAPL", "sell", 100, 185.00, 1.0, now),
        ]

        pnl = await repo.get_daily_realized_pnl()

        # strat1: (185 - 180) * 100 - 2 = 498
        # strat2: (185 - 190) * 100 - 2 = -502
        # Total: -4
        assert pnl == Decimal("-4")

    @pytest.mark.asyncio
    async def test_strategy_filter(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Filter by strategy_id should only include that strategy."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        now = datetime.now(UTC)
        mock_conn.fetch.return_value = [
            self._make_fill("strat1", "AAPL", "buy", 100, 180.00, 1.0, now - timedelta(minutes=10)),
            self._make_fill("strat1", "AAPL", "sell", 100, 185.00, 1.0, now),
        ]

        pnl = await repo.get_daily_realized_pnl(strategy_id="strat1")

        # Verify correct query was used (with strategy filter)
        query_arg = mock_conn.fetch.call_args[0][0]
        assert "strategy_id = $1" in query_arg
        assert pnl == Decimal("498")

    @pytest.mark.asyncio
    async def test_only_today_sells_count(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Only sells from today should contribute to daily P&L."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        now = datetime.now(UTC)
        yesterday = now - timedelta(days=1)

        mock_conn.fetch.return_value = [
            # Yesterday's round trip - should not count
            self._make_fill("strat1", "AAPL", "buy", 100, 180.00, 1.0, yesterday - timedelta(hours=1)),
            self._make_fill("strat1", "AAPL", "sell", 100, 185.00, 1.0, yesterday),
            # Today's round trip - should count
            self._make_fill("strat1", "AAPL", "buy", 100, 190.00, 1.0, now - timedelta(minutes=10)),
            self._make_fill("strat1", "AAPL", "sell", 100, 195.00, 1.0, now),
        ]

        pnl = await repo.get_daily_realized_pnl()

        # Only today's trade: (195 - 190) * 100 - 2 = 498
        assert pnl == Decimal("498")

    @pytest.mark.asyncio
    async def test_historical_buy_sold_today(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Buy from yesterday, sold today should count in today's P&L."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        now = datetime.now(UTC)
        yesterday = now - timedelta(days=1)

        mock_conn.fetch.return_value = [
            self._make_fill("strat1", "AAPL", "buy", 100, 180.00, 1.0, yesterday),
            self._make_fill("strat1", "AAPL", "sell", 100, 190.00, 1.0, now),
        ]

        pnl = await repo.get_daily_realized_pnl()

        # (190 - 180) * 100 - 2 = 998
        assert pnl == Decimal("998")

    @pytest.mark.asyncio
    async def test_sell_without_matching_buy_ignored(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Orphan sells (no matching buy) should be ignored, not crash."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        now = datetime.now(UTC)
        mock_conn.fetch.return_value = [
            self._make_fill("strat1", "AAPL", "sell", 100, 185.00, 1.0, now),
        ]

        pnl = await repo.get_daily_realized_pnl()

        assert pnl == Decimal("0")


class TestGetDailyPnlSeries:
    """Tests for OrderRepository.get_daily_pnl_series() FIFO matching."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        pool = MagicMock()
        pool.acquire = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool: MagicMock) -> OrderRepository:
        return OrderRepository(mock_pool)

    def _make_fill(
        self,
        strategy_id: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        commission: float = 1.0,
        filled_at: datetime | None = None,
    ) -> dict:
        """Helper to create fill records."""
        if filled_at is None:
            filled_at = datetime.now(UTC)
        return {
            "strategy_id": strategy_id,
            "symbol": symbol,
            "side": side,
            "quantity": Decimal(str(quantity)),
            "price": Decimal(str(price)),
            "commission": Decimal(str(commission)),
            "filled_at": filled_at,
        }

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """No fills should return empty list."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_conn.fetch.return_value = []

        series = await repo.get_daily_pnl_series()

        assert series == []

    @pytest.mark.asyncio
    async def test_multiple_days_separated(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """P&L should be grouped by day."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        day1 = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
        day2 = datetime(2024, 1, 16, 10, 0, tzinfo=UTC)

        mock_conn.fetch.return_value = [
            # Day 1: profit
            self._make_fill("strat1", "AAPL", "buy", 100, 180.00, 1.0, day1 - timedelta(hours=1)),
            self._make_fill("strat1", "AAPL", "sell", 100, 185.00, 1.0, day1),
            # Day 2: loss
            self._make_fill("strat1", "AAPL", "buy", 100, 190.00, 1.0, day2 - timedelta(hours=1)),
            self._make_fill("strat1", "AAPL", "sell", 100, 185.00, 1.0, day2),
        ]

        series = await repo.get_daily_pnl_series()

        # Most recent first
        assert len(series) == 2
        assert series[0] == Decimal("-502")  # Day 2 loss
        assert series[1] == Decimal("498")   # Day 1 profit

    @pytest.mark.asyncio
    async def test_limit_parameter(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Limit should restrict number of days returned."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        days = [datetime(2024, 1, i, 10, 0, tzinfo=UTC) for i in range(10, 16)]
        fills = []
        for day in days:
            fills.append(self._make_fill("strat1", "AAPL", "buy", 100, 180.00, 1.0, day - timedelta(hours=1)))
            fills.append(self._make_fill("strat1", "AAPL", "sell", 100, 185.00, 1.0, day))

        mock_conn.fetch.return_value = fills

        series = await repo.get_daily_pnl_series(limit=3)

        assert len(series) == 3

    @pytest.mark.asyncio
    async def test_fifo_carries_across_days(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Buy on day 1, sell on day 2 should attribute P&L to day 2."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        day1 = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
        day2 = datetime(2024, 1, 16, 10, 0, tzinfo=UTC)

        mock_conn.fetch.return_value = [
            self._make_fill("strat1", "AAPL", "buy", 100, 180.00, 1.0, day1),
            self._make_fill("strat1", "AAPL", "sell", 100, 190.00, 1.0, day2),
        ]

        series = await repo.get_daily_pnl_series()

        # Only day 2 should have P&L (when the sell happened)
        assert len(series) == 1
        assert series[0] == Decimal("998")  # (190-180)*100 - 2


class TestPnlCalculationRegression:
    """Regression tests for the original bug."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        pool = MagicMock()
        pool.acquire = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool: MagicMock) -> OrderRepository:
        return OrderRepository(mock_pool)

    def _make_fill(
        self,
        strategy_id: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        commission: float = 1.0,
        filled_at: datetime | None = None,
    ) -> dict:
        if filled_at is None:
            filled_at = datetime.now(UTC)
        return {
            "strategy_id": strategy_id,
            "symbol": symbol,
            "side": side,
            "quantity": Decimal(str(quantity)),
            "price": Decimal(str(price)),
            "commission": Decimal(str(commission)),
            "filled_at": filled_at,
        }

    @pytest.mark.asyncio
    async def test_open_positions_not_counted_as_loss(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """
        Regression test: The original bug treated all buys as realized losses.
        Open positions (buys without matching sells) should NOT affect realized P&L.
        """
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        now = datetime.now(UTC)
        mock_conn.fetch.return_value = [
            # Multiple open positions - should NOT be counted as losses
            self._make_fill("momentum", "AAPL", "buy", 100, 176.62, 1.0, now - timedelta(minutes=30)),
            self._make_fill("momentum", "AAPL", "buy", 100, 176.42, 1.0, now - timedelta(minutes=20)),
            self._make_fill("pairs", "AAPL", "buy", 50, 177.20, 1.0, now - timedelta(minutes=10)),
        ]

        pnl = await repo.get_daily_realized_pnl()

        # Original bug would calculate: -(176.62*100 + 176.42*100 + 177.20*50) = -$35,264
        # Correct behavior: no sells = no realized P&L
        assert pnl == Decimal("0")

    @pytest.mark.asyncio
    async def test_mixed_open_and_closed_positions(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """
        Regression test: With mix of open and closed positions,
        only closed positions should contribute to realized P&L.
        """
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        now = datetime.now(UTC)
        mock_conn.fetch.return_value = [
            # Closed position (profit)
            self._make_fill("strat1", "AAPL", "buy", 100, 180.00, 1.0, now - timedelta(minutes=40)),
            self._make_fill("strat1", "AAPL", "sell", 100, 185.00, 1.0, now - timedelta(minutes=30)),
            # Open positions (should not count)
            self._make_fill("strat1", "GOOGL", "buy", 100, 170.00, 1.0, now - timedelta(minutes=20)),
            self._make_fill("strat2", "AAPL", "buy", 50, 182.00, 1.0, now - timedelta(minutes=10)),
        ]

        pnl = await repo.get_daily_realized_pnl()

        # Only the closed AAPL trade should count: (185-180)*100 - 2 = 498
        # Original bug would add: -(170*100 + 182*50) = -$26,100 extra loss
        assert pnl == Decimal("498")

    @pytest.mark.asyncio
    async def test_real_world_scenario(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """
        Regression test: Simulate the actual scenario that exposed the bug.
        Multiple strategies trading, some with open positions.
        """
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        now = datetime.now(UTC)
        mock_conn.fetch.return_value = [
            # Momentum strategy - one winning trade, one open
            self._make_fill("momentum_us_01", "AAPL", "buy", 100, 181.85, 1.0, now - timedelta(minutes=50)),
            self._make_fill("momentum_us_01", "AAPL", "sell", 100, 183.48, 1.0, now - timedelta(minutes=40)),
            self._make_fill("momentum_us_01", "AAPL", "buy", 100, 176.62, 1.0, now - timedelta(minutes=5)),  # Open

            # Pairs strategy - one losing trade, one open
            self._make_fill("pairs_aapl_msft", "AAPL", "buy", 50, 181.58, 1.0, now - timedelta(minutes=30)),
            self._make_fill("pairs_aapl_msft", "AAPL", "sell", 50, 175.54, 1.0, now - timedelta(minutes=25)),
            self._make_fill("pairs_aapl_msft", "AAPL", "buy", 50, 177.20, 1.0, now - timedelta(minutes=3)),  # Open

            # Mean reversion - one losing trade
            self._make_fill("mean_rev_01", "GOOGL", "buy", 100, 170.39, 1.0, now - timedelta(minutes=20)),
            self._make_fill("mean_rev_01", "GOOGL", "sell", 100, 166.40, 1.0, now - timedelta(minutes=15)),
        ]

        pnl = await repo.get_daily_realized_pnl()

        # Momentum: (183.48 - 181.85) * 100 - 2 = 161
        # Pairs: (175.54 - 181.58) * 50 - 2 = -304
        # Mean rev: (166.40 - 170.39) * 100 - 2 = -401
        # Total: 161 - 304 - 401 = -544
        expected = Decimal("161") + Decimal("-304") + Decimal("-401")
        assert pnl == expected
