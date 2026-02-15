"""Report generation for full system backtest."""

import json
from decimal import Decimal
from typing import Optional

import asyncpg

from axtrade.common import DatabaseConfig, get_logger

from .types import (
    DiscoveryResultSummary,
    FullBacktestConfig,
    FullBacktestResult,
    StrategyResult,
)

logger = get_logger("fulltest.report")


class ReportGenerator:
    """Generates reports from backtest database results."""

    def __init__(self, db_config: DatabaseConfig, backtest_db_name: str):
        self._db_config = db_config
        self._db_name = backtest_db_name

    async def generate(
        self,
        config: FullBacktestConfig,
        result: FullBacktestResult,
    ) -> FullBacktestResult:
        """Query the backtest DB and populate result with detailed metrics.

        Args:
            config: Backtest configuration
            result: Partially populated result to fill in

        Returns:
            Fully populated FullBacktestResult
        """
        conn = await asyncpg.connect(
            host=self._db_config.host,
            port=self._db_config.port,
            database=self._db_name,
            user=self._db_config.user,
            password=self._db_config.password,
        )

        try:
            # Count orders and fills
            result.total_orders = await conn.fetchval(
                "SELECT COUNT(*) FROM orders"
            ) or 0
            result.total_fills = await conn.fetchval(
                "SELECT COUNT(*) FROM fills"
            ) or 0

            # Get per-strategy results
            result.strategy_results = await self._get_strategy_results(conn)

            # Calculate final equity
            total_realized_pnl = await conn.fetchval(
                "SELECT COALESCE(SUM(realized_pnl), 0) FROM positions"
            )
            result.final_equity = config.initial_capital + float(
                total_realized_pnl or 0
            )

            # Get discovery results
            result.discovery = await self._get_discovery_results(conn)

        finally:
            await conn.close()

        return result

    async def _get_strategy_results(
        self, conn: asyncpg.Connection
    ) -> list[StrategyResult]:
        """Query per-strategy metrics from fills and positions."""
        # Get distinct strategies from fills
        strategies = await conn.fetch(
            "SELECT DISTINCT strategy_id FROM fills ORDER BY strategy_id"
        )

        results = []
        for row in strategies:
            strategy_id = row["strategy_id"]

            # Count fills (trades)
            trade_count = await conn.fetchval(
                "SELECT COUNT(*) FROM fills WHERE strategy_id = $1",
                strategy_id,
            ) or 0

            # Get realized P&L from positions
            pnl_row = await conn.fetchrow(
                """
                SELECT
                    COALESCE(SUM(realized_pnl), 0) as total_pnl,
                    COUNT(DISTINCT symbol) as symbols_count
                FROM positions
                WHERE strategy_id = $1
                """,
                strategy_id,
            )

            total_pnl = float(pnl_row["total_pnl"]) if pnl_row else 0.0
            symbols_count = pnl_row["symbols_count"] if pnl_row else 0

            # Get win/loss counts from closed positions
            wins = await conn.fetchval(
                """
                SELECT COUNT(*) FROM positions
                WHERE strategy_id = $1
                    AND closed_at IS NOT NULL
                    AND realized_pnl > 0
                """,
                strategy_id,
            ) or 0

            losses = await conn.fetchval(
                """
                SELECT COUNT(*) FROM positions
                WHERE strategy_id = $1
                    AND closed_at IS NOT NULL
                    AND realized_pnl <= 0
                """,
                strategy_id,
            ) or 0

            # Profit factor
            gross_profit = await conn.fetchval(
                """
                SELECT COALESCE(SUM(realized_pnl), 0) FROM positions
                WHERE strategy_id = $1 AND realized_pnl > 0
                """,
                strategy_id,
            ) or Decimal(0)

            gross_loss = await conn.fetchval(
                """
                SELECT COALESCE(ABS(SUM(realized_pnl)), 0) FROM positions
                WHERE strategy_id = $1 AND realized_pnl < 0
                """,
                strategy_id,
            ) or Decimal(0)

            profit_factor = None
            if gross_loss and float(gross_loss) > 0:
                profit_factor = float(gross_profit) / float(gross_loss)

            # Traded symbols
            traded = await conn.fetch(
                "SELECT DISTINCT symbol FROM fills WHERE strategy_id = $1",
                strategy_id,
            )
            symbols_traded = [r["symbol"] for r in traded]

            # Determine strategy type from ID
            strategy_type = strategy_id.split("-")[0] if "-" in strategy_id else strategy_id

            results.append(StrategyResult(
                strategy_id=strategy_id,
                strategy_type=strategy_type,
                trade_count=trade_count,
                win_count=wins,
                loss_count=losses,
                total_pnl=total_pnl,
                profit_factor=profit_factor,
                symbols_traded=symbols_traded,
            ))

        return results

    async def _get_discovery_results(
        self, conn: asyncpg.Connection
    ) -> DiscoveryResultSummary:
        """Query discovery results from database."""
        summary = DiscoveryResultSummary()

        # Check if discovery tables exist
        has_table = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'discovered_symbols'
            )
            """
        )

        if has_table:
            try:
                summary.symbols_discovered = await conn.fetchval(
                    "SELECT COUNT(DISTINCT symbol) FROM discovered_symbols"
                ) or 0
            except Exception:
                pass

        return summary


def format_text_report(result: FullBacktestResult) -> str:
    """Format the backtest result as a text report."""
    lines = []
    lines.append("=" * 70)
    lines.append("FULL SYSTEM BACKTEST REPORT")
    lines.append("=" * 70)
    lines.append("")

    # Overview
    cfg = result.config
    lines.append("Configuration:")
    lines.append(f"  Period:           {cfg.start} to {cfg.end}")
    lines.append(f"  Symbols:          {', '.join(cfg.symbols[:10])}")
    if len(cfg.symbols) > 10:
        lines.append(f"                    ... and {len(cfg.symbols) - 10} more")
    lines.append(f"  Interval:         {cfg.interval}")
    lines.append(f"  Initial Capital:  ${cfg.initial_capital:,.2f}")
    lines.append(f"  Discovery:        {'enabled' if cfg.discovery_enabled else 'disabled'}")
    lines.append("")

    # Timing
    lines.append("Execution:")
    lines.append(f"  Wall Clock:       {result.wall_clock_seconds:.1f}s")
    lines.append(f"  Bars Processed:   {result.total_bars_processed:,}")
    lines.append(f"  Ticks Generated:  {result.total_ticks_generated:,}")
    lines.append(f"  Total Orders:     {result.total_orders:,}")
    lines.append(f"  Total Fills:      {result.total_fills:,}")
    lines.append("")

    # Overall P&L
    lines.append("Overall:")
    lines.append(f"  Final Equity:     ${result.final_equity:,.2f}")
    lines.append(f"  Total P&L:        ${result.total_pnl:,.2f}")
    pct = (result.total_pnl / cfg.initial_capital * 100) if cfg.initial_capital else 0
    lines.append(f"  Return:           {pct:+.2f}%")
    lines.append("")

    # Per-strategy results
    if result.strategy_results:
        lines.append("-" * 70)
        lines.append("STRATEGY RESULTS")
        lines.append("-" * 70)
        lines.append("")
        lines.append(
            f"{'Strategy':<25} {'Trades':>7} {'Win%':>7} {'P&L':>12} {'PF':>7} {'Symbols':>8}"
        )
        lines.append("-" * 70)

        for sr in result.strategy_results:
            win_pct = f"{sr.win_rate * 100:.1f}%"
            pf = f"{sr.profit_factor:.2f}" if sr.profit_factor else "N/A"
            lines.append(
                f"{sr.strategy_id:<25} {sr.trade_count:>7} {win_pct:>7} "
                f"${sr.total_pnl:>10,.2f} {pf:>7} {len(sr.symbols_traded):>8}"
            )

        lines.append("")

    # Discovery results
    if cfg.discovery_enabled and result.discovery:
        lines.append("-" * 70)
        lines.append("DISCOVERY RESULTS")
        lines.append("-" * 70)
        lines.append(f"  Total Scans:          {result.discovery.total_scans}")
        lines.append(f"  Symbols Discovered:   {result.discovery.symbols_discovered}")
        lines.append("")

    lines.append("=" * 70)
    return "\n".join(lines)


def format_json_report(result: FullBacktestResult) -> str:
    """Format the backtest result as JSON."""
    data = {
        "config": {
            "start": str(result.config.start),
            "end": str(result.config.end),
            "symbols": result.config.symbols,
            "interval": result.config.interval,
            "initial_capital": result.config.initial_capital,
            "discovery_enabled": result.config.discovery_enabled,
        },
        "timing": {
            "wall_clock_seconds": result.wall_clock_seconds,
            "start_time": result.start_time.isoformat(),
            "end_time": result.end_time.isoformat(),
        },
        "data": {
            "bars_processed": result.total_bars_processed,
            "ticks_generated": result.total_ticks_generated,
        },
        "results": {
            "total_orders": result.total_orders,
            "total_fills": result.total_fills,
            "final_equity": result.final_equity,
            "total_pnl": result.total_pnl,
            "return_pct": (result.total_pnl / result.config.initial_capital * 100)
            if result.config.initial_capital
            else 0,
        },
        "strategies": [
            {
                "strategy_id": sr.strategy_id,
                "strategy_type": sr.strategy_type,
                "trade_count": sr.trade_count,
                "win_count": sr.win_count,
                "loss_count": sr.loss_count,
                "win_rate": sr.win_rate,
                "total_pnl": sr.total_pnl,
                "profit_factor": sr.profit_factor,
                "symbols_traded": sr.symbols_traded,
            }
            for sr in result.strategy_results
        ],
        "discovery": {
            "total_scans": result.discovery.total_scans,
            "symbols_discovered": result.discovery.symbols_discovered,
        },
    }
    return json.dumps(data, indent=2)
