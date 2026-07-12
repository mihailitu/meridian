"""Tests for DiscoveryRepository (audit P1-3): persists DiscoveryService scan
results so processes without a live scanner (e.g. the API) can read them."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from axtrade.discovery.repository import DiscoveryRepository
from axtrade.discovery.types import DiscoveredSymbol


@pytest.fixture
def mock_pool() -> MagicMock:
    """Mock DatabasePool exposing an async acquire() context manager."""
    pool = MagicMock()
    pool.acquire = MagicMock()
    return pool


@pytest.fixture
def repo(mock_pool: MagicMock) -> DiscoveryRepository:
    return DiscoveryRepository(mock_pool)


def _mock_conn(mock_pool: MagicMock) -> AsyncMock:
    """Wire a mock connection (with a transaction() context manager) through
    pool.acquire() and return it.

    conn.transaction() is sync (returns an async context manager), unlike
    conn.execute()/fetch() etc. which are coroutines -- it must be a MagicMock,
    not an AsyncMock, or "async with conn.transaction():" gets a coroutine
    instead of a context manager.
    """
    mock_conn = AsyncMock()
    mock_conn.transaction = MagicMock()
    mock_conn.transaction.return_value.__aenter__ = AsyncMock(return_value=None)
    mock_conn.transaction.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    return mock_conn


class TestReplaceScan:
    """Tests for DiscoveryRepository.replace_scan (upsert/replace semantics)."""

    async def test_replace_scan_deletes_then_inserts(
        self, repo: DiscoveryRepository, mock_pool: MagicMock
    ) -> None:
        """A scan's results should mirror the cache: delete all rows, then
        bulk-insert the current cache."""
        mock_conn = _mock_conn(mock_pool)

        discovered = [
            DiscoveredSymbol(symbol="AAPL", source="momentum", score=80.0, price=185.0),
            DiscoveredSymbol(symbol="TSLA", source="trend", score=-60.0, price=250.0),
        ]

        await repo.replace_scan(discovered)

        mock_conn.execute.assert_called_once_with("DELETE FROM discovered_symbols")
        mock_conn.executemany.assert_called_once()
        query, records = mock_conn.executemany.call_args[0]
        assert "INSERT INTO discovered_symbols" in query
        assert len(records) == 2
        symbols_inserted = {r[0] for r in records}
        assert symbols_inserted == {"AAPL", "TSLA"}

    async def test_replace_scan_empty_cache_deletes_without_insert(
        self, repo: DiscoveryRepository, mock_pool: MagicMock
    ) -> None:
        """An empty scan cache should clear the table without attempting an
        empty bulk insert (symbol dropped out of discovery -> row removed)."""
        mock_conn = _mock_conn(mock_pool)

        await repo.replace_scan([])

        mock_conn.execute.assert_called_once_with("DELETE FROM discovered_symbols")
        mock_conn.executemany.assert_not_called()

    async def test_replace_scan_serializes_metadata_as_json(
        self, repo: DiscoveryRepository, mock_pool: MagicMock
    ) -> None:
        mock_conn = _mock_conn(mock_pool)

        discovered = [
            DiscoveredSymbol(
                symbol="AAPL",
                source="manual",
                score=0.0,
                metadata={"notes": "earnings play"},
            ),
        ]

        await repo.replace_scan(discovered)

        _, records = mock_conn.executemany.call_args[0]
        metadata_json = records[0][-1]
        assert json.loads(metadata_json) == {"notes": "earnings play"}


class TestGetDiscovered:
    """Tests for DiscoveryRepository.get_discovered."""

    def _row(self, **overrides) -> dict:
        row = {
            "symbol": "AAPL",
            "source": "momentum",
            "score": 80.0,
            "price": 185.0,
            "volume": 1_000_000,
            "change_pct": 1.5,
            "discovered_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "metadata": "{}",
        }
        row.update(overrides)
        return row

    async def test_get_discovered_returns_symbols(
        self, repo: DiscoveryRepository, mock_pool: MagicMock
    ) -> None:
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [self._row()]
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        results = await repo.get_discovered()

        assert len(results) == 1
        assert results[0].symbol == "AAPL"
        assert results[0].metadata == {}

    async def test_get_discovered_applies_min_score_filter(
        self, repo: DiscoveryRepository, mock_pool: MagicMock
    ) -> None:
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        await repo.get_discovered(min_score=60.0)

        query, params = mock_conn.fetch.call_args[0][0], mock_conn.fetch.call_args[0][1:]
        assert "ABS(score) >=" in query
        assert 60.0 in params

    async def test_get_discovered_decodes_json_metadata(
        self, repo: DiscoveryRepository, mock_pool: MagicMock
    ) -> None:
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [self._row(metadata=json.dumps({"notes": "x"}))]
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        results = await repo.get_discovered()

        assert results[0].metadata == {"notes": "x"}


class TestCountAndLastScan:
    async def test_count(self, repo: DiscoveryRepository, mock_pool: MagicMock) -> None:
        mock_conn = AsyncMock()
        mock_conn.fetchval.return_value = 3
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        assert await repo.count() == 3

    async def test_count_empty_table_returns_zero(
        self, repo: DiscoveryRepository, mock_pool: MagicMock
    ) -> None:
        mock_conn = AsyncMock()
        mock_conn.fetchval.return_value = None
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        assert await repo.count() == 0

    async def test_last_scan_at(self, repo: DiscoveryRepository, mock_pool: MagicMock) -> None:
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        mock_conn = AsyncMock()
        mock_conn.fetchval.return_value = now
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        assert await repo.last_scan_at() == now
