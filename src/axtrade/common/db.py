"""Database connection pool and repositories."""

from contextlib import asynccontextmanager
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import AsyncIterator, Optional

import asyncpg

from .config import DatabaseConfig
from .logging import get_logger
from .types import Bar


class DatabasePool:
    """Async PostgreSQL connection pool manager."""

    def __init__(self, config: DatabaseConfig):
        """Initialize database pool.

        Args:
            config: Database configuration
        """
        self.config = config
        self.logger = get_logger("db.pool")
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        """Create the connection pool."""
        self.logger.info(
            "Connecting to database",
            host=self.config.host,
            port=self.config.port,
            database=self.config.database,
        )
        self._pool = await asyncpg.create_pool(
            host=self.config.host,
            port=self.config.port,
            database=self.config.database,
            user=self.config.user,
            password=self.config.password,
            min_size=self.config.min_pool_size,
            max_size=self.config.max_pool_size,
        )
        self.logger.info("Database pool created")

    async def disconnect(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            self.logger.info("Database pool closed")

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[asyncpg.Connection]:
        """Acquire a connection from the pool.

        Yields:
            Database connection
        """
        if not self._pool:
            raise RuntimeError("Database pool not initialized")
        async with self._pool.acquire() as conn:
            yield conn


class BarRepository:
    """Repository for bar data persistence."""

    def __init__(self, pool: DatabasePool):
        """Initialize bar repository.

        Args:
            pool: Database connection pool
        """
        self.pool = pool
        self.logger = get_logger("db.bars")

    async def insert_bar(
        self,
        bar: Bar,
        interval: str,
        sma_20: Optional[float] = None,
        rsi_14: Optional[float] = None,
    ) -> None:
        """Insert a bar with indicators.

        Uses UPSERT to handle duplicate bars gracefully.

        Args:
            bar: Bar data
            interval: Bar interval (1m, 5m, etc.)
            sma_20: 20-period SMA value
            rsi_14: 14-period RSI value
        """
        query = """
            INSERT INTO bars (time, symbol, interval, open, high, low, close, volume, sma_20, rsi_14)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (symbol, interval, time)
            DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                sma_20 = EXCLUDED.sma_20,
                rsi_14 = EXCLUDED.rsi_14
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                bar.timestamp,
                bar.symbol,
                interval,
                Decimal(str(bar.open)),
                Decimal(str(bar.high)),
                Decimal(str(bar.low)),
                Decimal(str(bar.close)),
                bar.volume,
                Decimal(str(sma_20)) if sma_20 is not None else None,
                Decimal(str(rsi_14)) if rsi_14 is not None else None,
            )

    async def get_bars(
        self,
        symbol: str,
        interval: str = "1m",
        limit: int = 100,
    ) -> list[dict]:
        """Get recent bars for a symbol.

        Args:
            symbol: Symbol to query
            interval: Bar interval
            limit: Maximum number of bars to return

        Returns:
            List of bar dictionaries with indicators
        """
        query = """
            SELECT time, symbol, interval, open, high, low, close, volume, sma_20, rsi_14
            FROM bars
            WHERE symbol = $1 AND interval = $2
            ORDER BY time DESC
            LIMIT $3
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, symbol, interval, limit)

        return [
            {
                "time": row["time"],
                "symbol": row["symbol"],
                "interval": row["interval"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": row["volume"],
                "sma_20": float(row["sma_20"]) if row["sma_20"] else None,
                "rsi_14": float(row["rsi_14"]) if row["rsi_14"] else None,
            }
            for row in rows
        ]

    async def get_recent_closes(
        self,
        symbol: str,
        interval: str,
        count: int,
    ) -> list[float]:
        """Get recent close prices for indicator warmup.

        Args:
            symbol: Symbol to query
            interval: Bar interval
            count: Number of closes to retrieve

        Returns:
            List of close prices, oldest first
        """
        query = """
            SELECT close
            FROM bars
            WHERE symbol = $1 AND interval = $2
            ORDER BY time DESC
            LIMIT $3
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, symbol, interval, count)

        # Return oldest first for proper buffer initialization
        return [float(row["close"]) for row in reversed(rows)]

    async def get_bars_range(
        self,
        symbol: str,
        interval: str,
        start: date,
        end: date,
    ) -> list[dict]:
        """Get bars with indicators for a date range.

        Args:
            symbol: Trading symbol
            interval: Bar interval (1m, 5m, etc.)
            start: Start date (inclusive)
            end: End date (inclusive)

        Returns:
            List of dicts with bar and indicator data, ordered by time ASC
        """
        # Convert dates to timestamps
        start_ts = datetime.combine(start, time.min, tzinfo=timezone.utc)
        end_ts = datetime.combine(end, time.max, tzinfo=timezone.utc)

        query = """
            SELECT time, symbol, open, high, low, close, volume, sma_20, rsi_14
            FROM bars
            WHERE symbol = $1 AND interval = $2
              AND time >= $3 AND time <= $4
            ORDER BY time ASC
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, symbol, interval, start_ts, end_ts)

        results = []
        for row in rows:
            bar = Bar(
                symbol=row["symbol"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=row["volume"],
                timestamp=row["time"],
            )
            results.append(
                {
                    "bar": bar,
                    "sma_20": float(row["sma_20"]) if row["sma_20"] else None,
                    "rsi_14": float(row["rsi_14"]) if row["rsi_14"] else None,
                }
            )

        return results

    async def get_recent_bars(
        self,
        symbol: str,
        interval: str,
        limit: int = 50,
    ) -> list[Bar]:
        """Get recent bars as Bar objects.

        Args:
            symbol: Symbol to query
            interval: Bar interval
            limit: Maximum number of bars to return

        Returns:
            List of Bar objects, oldest first
        """
        query = """
            SELECT time, symbol, open, high, low, close, volume
            FROM bars
            WHERE symbol = $1 AND interval = $2
            ORDER BY time DESC
            LIMIT $3
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, symbol, interval, limit)

        # Return oldest first for proper processing order
        return [
            Bar(
                symbol=row["symbol"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=row["volume"],
                timestamp=row["time"],
            )
            for row in reversed(rows)
        ]

    async def get_bars_since(
        self,
        symbol: str,
        interval: str,
        since: datetime,
    ) -> list[Bar]:
        """Get bars since a given timestamp.

        Args:
            symbol: Symbol to query
            interval: Bar interval
            since: Start timestamp (inclusive)

        Returns:
            List of Bar objects, oldest first
        """
        query = """
            SELECT time, symbol, open, high, low, close, volume
            FROM bars
            WHERE symbol = $1 AND interval = $2 AND time >= $3
            ORDER BY time ASC
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, symbol, interval, since)

        return [
            Bar(
                symbol=row["symbol"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=row["volume"],
                timestamp=row["time"],
            )
            for row in rows
        ]
