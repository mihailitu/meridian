"""Unit tests for database module.

Note: These tests use mocking to avoid requiring a real database.
Integration tests with TimescaleDB should be run separately.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from axtrade.common import Bar, DatabaseConfig
from axtrade.common.db import BarRepository, DatabasePool


class TestDatabasePool:
    """Tests for DatabasePool."""

    def test_init(self) -> None:
        config = DatabaseConfig(
            host="localhost",
            port=8112,
            database="testdb",
            user="testuser",
            password="testpass",
        )
        pool = DatabasePool(config)
        assert pool.config == config
        assert pool._pool is None

    @pytest.mark.asyncio
    async def test_connect_creates_pool(self) -> None:
        config = DatabaseConfig()
        pool = DatabasePool(config)

        mock_pool = MagicMock()
        with patch(
            "axtrade.common.db.asyncpg.create_pool",
            new_callable=AsyncMock,
            return_value=mock_pool
        ) as mock_create:
            await pool.connect()

            mock_create.assert_called_once_with(
                host=config.host,
                port=config.port,
                database=config.database,
                user=config.user,
                password=config.password,
                min_size=config.min_pool_size,
                max_size=config.max_pool_size,
            )
            assert pool._pool == mock_pool

    @pytest.mark.asyncio
    async def test_disconnect_closes_pool(self) -> None:
        config = DatabaseConfig()
        pool = DatabasePool(config)

        mock_pool = AsyncMock()
        pool._pool = mock_pool

        await pool.disconnect()

        mock_pool.close.assert_called_once()
        assert pool._pool is None

    @pytest.mark.asyncio
    async def test_acquire_without_pool_raises(self) -> None:
        config = DatabaseConfig()
        pool = DatabasePool(config)

        with pytest.raises(RuntimeError, match="not initialized"):
            async with pool.acquire():
                pass


class TestBarRepository:
    """Tests for BarRepository."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        pool = MagicMock()
        pool.acquire = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool: MagicMock) -> BarRepository:
        return BarRepository(mock_pool)

    @pytest.mark.asyncio
    async def test_insert_bar_executes_query(
        self, repo: BarRepository, mock_pool: MagicMock
    ) -> None:
        bar = Bar(
            symbol="AAPL",
            open=185.0,
            high=186.0,
            low=184.0,
            close=185.5,
            volume=1000,
            timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
        )

        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        await repo.insert_bar(bar, "1m", sma_20=185.2, rsi_14=55.5)

        mock_conn.execute.assert_called_once()
        args = mock_conn.execute.call_args[0]
        assert "INSERT INTO bars" in args[0]
        assert args[1] == bar.timestamp
        assert args[2] == "AAPL"
        assert args[3] == "1m"
        assert args[4] == Decimal("185.0")

    @pytest.mark.asyncio
    async def test_insert_bar_with_none_indicators(
        self, repo: BarRepository, mock_pool: MagicMock
    ) -> None:
        bar = Bar(
            symbol="AAPL",
            open=185.0,
            high=186.0,
            low=184.0,
            close=185.5,
            volume=1000,
            timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
        )

        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        await repo.insert_bar(bar, "1m", sma_20=None, rsi_14=None)

        args = mock_conn.execute.call_args[0]
        # sma_20 and rsi_14 should be None
        assert args[9] is None
        assert args[10] is None

    @pytest.mark.asyncio
    async def test_get_bars_returns_formatted_data(
        self, repo: BarRepository, mock_pool: MagicMock
    ) -> None:
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        mock_rows = [
            {
                "time": datetime(2024, 1, 15, 9, 31, tzinfo=timezone.utc),
                "symbol": "AAPL",
                "interval": "1m",
                "open": Decimal("185.5"),
                "high": Decimal("186.0"),
                "low": Decimal("185.0"),
                "close": Decimal("185.8"),
                "volume": 500,
                "sma_20": Decimal("185.2"),
                "rsi_14": Decimal("55.5"),
            },
            {
                "time": datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
                "symbol": "AAPL",
                "interval": "1m",
                "open": Decimal("185.0"),
                "high": Decimal("185.5"),
                "low": Decimal("184.5"),
                "close": Decimal("185.2"),
                "volume": 1000,
                "sma_20": None,
                "rsi_14": None,
            },
        ]
        mock_conn.fetch.return_value = mock_rows

        bars = await repo.get_bars("AAPL", "1m", 10)

        assert len(bars) == 2
        assert bars[0]["symbol"] == "AAPL"
        assert bars[0]["open"] == 185.5
        assert bars[0]["sma_20"] == 185.2
        assert bars[1]["sma_20"] is None

    @pytest.mark.asyncio
    async def test_get_recent_closes_returns_oldest_first(
        self, repo: BarRepository, mock_pool: MagicMock
    ) -> None:
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        # Query returns newest first
        mock_rows = [
            {"close": Decimal("186.0")},  # newest
            {"close": Decimal("185.5")},
            {"close": Decimal("185.0")},  # oldest
        ]
        mock_conn.fetch.return_value = mock_rows

        closes = await repo.get_recent_closes("AAPL", "1m", 3)

        # Should be reversed to oldest first
        assert closes == [185.0, 185.5, 186.0]
