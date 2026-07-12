"""Repository for persisting discovery scan results.

Makes DiscoveryService's in-memory ``_discovered`` cache visible outside the
process that ran the scan (audit P1-3): the API process no longer scans, so
it must read discoveries from the database instead of a live DiscoveryService.
"""

import json
from typing import Optional

from axtrade.common.db import DatabasePool
from axtrade.common.logging import get_logger

from .types import DiscoveredSymbol


class DiscoveryRepository:
    """Persists and reads the `discovered_symbols` table.

    The table is treated as a mirror of DiscoveryService._discovered: one row
    per currently-discovered symbol. The schema (scripts/migrations/004_discovery.sql)
    has no per-symbol unique key -- it was designed to allow a history of scans
    via UNIQUE(symbol, source, discovered_at) -- so there is no natural ON
    CONFLICT target to upsert against. replace_scan() instead overwrites the
    whole table in one transaction (delete + bulk insert), which is the
    simplest way to guarantee the table exactly mirrors the in-memory cache,
    including symbols that dropped out of the latest scan.
    """

    def __init__(self, pool: DatabasePool):
        self.pool = pool
        self.logger = get_logger("discovery.repository")

    async def replace_scan(self, discovered: list[DiscoveredSymbol]) -> None:
        """Replace all rows with the current scan cache.

        Args:
            discovered: The full current DiscoveryService._discovered cache
                (values()), i.e. the desired end state of the table.
        """
        records = [
            (
                s.symbol,
                s.source,
                s.score,
                s.price,
                s.volume,
                s.change_pct,
                s.discovered_at,
                json.dumps(s.metadata),
            )
            for s in discovered
        ]

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM discovered_symbols")
                if records:
                    await conn.executemany(
                        """
                        INSERT INTO discovered_symbols
                            (symbol, source, score, price, volume, change_pct, discovered_at, metadata)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        """,
                        records,
                    )

        self.logger.debug("Persisted discovery scan", symbol_count=len(discovered))

    async def get_discovered(
        self,
        min_score: Optional[float] = None,
        source: Optional[str] = None,
        bullish_only: bool = False,
        bearish_only: bool = False,
        limit: int = 50,
    ) -> list[DiscoveredSymbol]:
        """Get discovered symbols with optional filtering.

        Mirrors DiscoveryService.get_discovered's filtering/sorting semantics.
        """
        conditions = []
        params: list = []

        if min_score is not None:
            params.append(min_score)
            conditions.append(f"ABS(score) >= ${len(params)}")
        if source:
            params.append(source)
            conditions.append(f"source = ${len(params)}")
        if bullish_only:
            conditions.append("score > 0")
        if bearish_only:
            conditions.append("score < 0")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        query = f"""
            SELECT symbol, source, score, price, volume, change_pct, discovered_at, metadata
            FROM discovered_symbols
            {where}
            ORDER BY ABS(score) DESC
            LIMIT ${len(params)}
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [self._row_to_symbol(row) for row in rows]

    async def count(self) -> int:
        """Total number of currently discovered symbols."""
        async with self.pool.acquire() as conn:
            result = await conn.fetchval("SELECT COUNT(*) FROM discovered_symbols")
        return result or 0

    async def last_scan_at(self):
        """Most recent discovered_at timestamp, or None if the table is empty."""
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT MAX(discovered_at) FROM discovered_symbols")

    def _row_to_symbol(self, row) -> DiscoveredSymbol:
        metadata = row["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata) if metadata else {}
        return DiscoveredSymbol(
            symbol=row["symbol"],
            source=row["source"],
            score=row["score"],
            price=row["price"],
            volume=row["volume"],
            change_pct=row["change_pct"],
            discovered_at=row["discovered_at"],
            metadata=metadata or {},
        )
