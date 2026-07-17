"""Report generation for full system backtest."""

import json
from decimal import Decimal
from typing import Optional

import asyncpg

from axtrade.common import DatabaseConfig, get_logger

from .analytics import compute_analytics
from .types import (
    DiscoveryResultSummary,
    FullBacktestConfig,
    FullBacktestResult,
    StrategyResult,
    SymbolPnL,
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
            # Data coverage: how far the persisted bars actually reach.
            result.last_bar_time = await conn.fetchval(
                "SELECT MAX(time) FROM bars WHERE interval = '1m'"
            )

            # Count orders and fills
            result.total_orders = await conn.fetchval(
                "SELECT COUNT(*) FROM orders"
            ) or 0
            result.total_fills = await conn.fetchval(
                "SELECT COUNT(*) FROM fills"
            ) or 0

            # Get per-strategy results
            result.strategy_results = await self._get_strategy_results(
                conn, config
            )

            # Mark open positions to the last available 1m close so equity
            # reflects what's still held (realized_pnl alone reports $0 for
            # anything not yet closed). Distribute per strategy too.
            unrealized_by_strategy = await self._get_unrealized_by_strategy(conn)
            total_unrealized = sum(unrealized_by_strategy.values())
            for sr in result.strategy_results:
                sr.unrealized_pnl = unrealized_by_strategy.get(sr.strategy_id, 0.0)

            # Final equity = capital + realized + open-position value change
            # - commissions (realized_pnl is gross of commissions; they only
            # ever leave cash via fills).
            total_realized_pnl = await conn.fetchval(
                "SELECT COALESCE(SUM(realized_pnl), 0) FROM positions"
            )
            total_commission = await conn.fetchval(
                "SELECT COALESCE(SUM(commission), 0) FROM fills"
            )
            result.total_unrealized_pnl = total_unrealized
            result.final_equity = (
                config.initial_capital
                + float(total_realized_pnl or 0)
                + total_unrealized
                - float(total_commission or 0)
            )

            # Get discovery results from DB (supplements in-memory stats)
            db_discovery = await self._get_discovery_results(conn)
            if db_discovery.symbols_discovered > result.discovery.symbols_discovered:
                result.discovery.symbols_discovered = db_discovery.symbols_discovered
            if db_discovery.top_symbols:
                result.discovery.top_symbols = db_discovery.top_symbols

            # Compute overall portfolio analytics
            overall = await compute_analytics(
                conn,
                strategy_id=None,
                initial_capital=config.initial_capital,
                start_date=config.start,
                end_date=config.end,
            )
            result.overall_sharpe = overall["sharpe_ratio"]
            result.overall_max_drawdown = overall["max_drawdown"]
            result.overall_annualized_return = overall["annualized_return"]
            result.overall_total_return = overall["total_return"]
            result.overall_profit_factor = overall["profit_factor"]
            result.overall_win_rate = overall["win_rate"]
            result.overall_total_trades = overall["total_trades"]
            result.overall_avg_trade_pnl = (
                float(overall["avg_trade_pnl"])
                if overall["avg_trade_pnl"]
                else None
            )
            result.overall_total_commission = (
                float(overall["total_commission"])
                if overall["total_commission"]
                else None
            )

        finally:
            await conn.close()

        return result

    async def _get_unrealized_by_strategy(
        self, conn: asyncpg.Connection
    ) -> dict[str, float]:
        """Mark-to-market P&L of open positions, keyed by strategy_id.

        Each open position is valued at its symbol's last persisted 1m bar
        close (the end of the replayed window).
        """
        rows = await conn.fetch(
            """
            SELECT p.strategy_id, p.symbol, p.side, p.quantity,
                   p.avg_entry_price, b.close AS last_close
            FROM positions p
            JOIN LATERAL (
                SELECT close FROM bars
                WHERE symbol = p.symbol AND interval = '1m'
                ORDER BY time DESC
                LIMIT 1
            ) b ON TRUE
            WHERE p.closed_at IS NULL AND p.quantity > 0
            """
        )
        unrealized: dict[str, float] = {}
        for row in rows:
            sign = -1 if row["side"] == "short" else 1
            pnl = (
                (float(row["last_close"]) - float(row["avg_entry_price"]))
                * float(row["quantity"])
                * sign
            )
            unrealized[row["strategy_id"]] = (
                unrealized.get(row["strategy_id"], 0.0) + pnl
            )
        return unrealized

    async def _get_strategy_results(
        self, conn: asyncpg.Connection, config: FullBacktestConfig
    ) -> list[StrategyResult]:
        """Query per-strategy metrics from fills and positions."""
        # Get distinct strategies from fills
        strategies = await conn.fetch(
            "SELECT DISTINCT strategy_id FROM fills ORDER BY strategy_id"
        )

        results = []
        for row in strategies:
            strategy_id = row["strategy_id"]

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

            # Traded symbols
            traded = await conn.fetch(
                "SELECT DISTINCT symbol FROM fills WHERE strategy_id = $1",
                strategy_id,
            )
            symbols_traded = [r["symbol"] for r in traded]

            # Determine strategy type from ID
            strategy_type = strategy_id.split("-")[0] if "-" in strategy_id else strategy_id

            # Compute analytics via FIFO matching
            metrics = await compute_analytics(
                conn,
                strategy_id=strategy_id,
                initial_capital=config.initial_capital,
                start_date=config.start,
                end_date=config.end,
            )

            per_symbol_raw = metrics.get("per_symbol", {})
            per_symbol_pnl = sorted(
                (
                    SymbolPnL(
                        symbol=sym,
                        pnl=float(s.pnl),
                        trades=s.trades,
                        wins=s.wins,
                        losses=s.losses,
                    )
                    for sym, s in per_symbol_raw.items()
                ),
                key=lambda p: p.pnl,
            )

            results.append(StrategyResult(
                strategy_id=strategy_id,
                strategy_type=strategy_type,
                trade_count=metrics["total_trades"],
                win_count=metrics["winning_trades"],
                loss_count=metrics["losing_trades"],
                total_pnl=total_pnl,
                max_drawdown=metrics["max_drawdown"],
                sharpe_ratio=metrics["sharpe_ratio"],
                profit_factor=metrics["profit_factor"],
                annualized_return=metrics["annualized_return"],
                total_return=metrics["total_return"],
                avg_winner=float(metrics["avg_winner"]) if metrics["avg_winner"] else None,
                avg_loser=float(metrics["avg_loser"]) if metrics["avg_loser"] else None,
                avg_trade_pnl=float(metrics["avg_trade_pnl"]) if metrics["avg_trade_pnl"] else None,
                total_commission=float(metrics["total_commission"]) if metrics["total_commission"] else None,
                symbols_traded=symbols_traded,
                per_symbol_pnl=per_symbol_pnl,
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


def _fmt_pct(value: Optional[float]) -> str:
    """Format a percentage value for display."""
    if value is None:
        return "N/A"
    return f"{value:+.2f}%"


def _fmt_dollar(value: Optional[float]) -> str:
    """Format a dollar value for display."""
    if value is None:
        return "N/A"
    return f"${value:,.2f}"


def _fmt_ratio(value: Optional[float]) -> str:
    """Format a ratio value for display."""
    if value is None:
        return "N/A"
    return f"{value:.2f}"


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
    if result.last_bar_time is not None:
        lines.append(f"  Data Through:     {result.last_bar_time:%Y-%m-%d %H:%M} (window end {cfg.end})")
        shortfall = (cfg.end - result.last_bar_time.date()).days
        if shortfall > 4:
            lines.append(
                f"  *** WARNING: bars stop {shortfall} days before the window end - "
                "pipeline truncated, all metrics understate the period ***"
            )
    lines.append("")

    # Overall P&L
    lines.append("Overall:")
    lines.append(f"  Final Equity:     ${result.final_equity:,.2f}")
    lines.append(f"  Realized P&L:     ${result.total_pnl:,.2f}")
    lines.append(f"  Unrealized P&L:   ${result.total_unrealized_pnl:,.2f} (open positions at last close)")
    total = result.total_pnl + result.total_unrealized_pnl
    pct = (total / cfg.initial_capital * 100) if cfg.initial_capital else 0
    lines.append(f"  Return:           {pct:+.2f}% (realized + unrealized, before commissions)")
    lines.append("")

    # Portfolio analytics
    lines.append("-" * 70)
    lines.append("PORTFOLIO ANALYTICS")
    lines.append("-" * 70)
    lines.append(f"  Sharpe (rf=0):     {_fmt_ratio(result.overall_sharpe)}")
    lines.append(f"  Max Drawdown:      {_fmt_pct(result.overall_max_drawdown)}")
    lines.append(f"  Annualized Return: {_fmt_pct(result.overall_annualized_return)}")
    lines.append(f"  Total Return:      {_fmt_pct(result.overall_total_return)}")
    lines.append(f"  Profit Factor:     {_fmt_ratio(result.overall_profit_factor)}")
    lines.append(f"  Total Trades:      {result.overall_total_trades}")
    win_rate_str = _fmt_pct(result.overall_win_rate) if result.overall_win_rate is not None else "N/A"
    lines.append(f"  Win Rate:          {win_rate_str}")
    lines.append(f"  Avg Trade P&L:     {_fmt_dollar(result.overall_avg_trade_pnl)}")
    lines.append(f"  Total Commission:  {_fmt_dollar(result.overall_total_commission)}")
    lines.append("")

    # Per-strategy detailed results
    if result.strategy_results:
        lines.append("-" * 70)
        lines.append("STRATEGY RESULTS")
        lines.append("-" * 70)

        for sr in result.strategy_results:
            lines.append("")
            lines.append(f"  {sr.strategy_id} ({sr.strategy_type})")
            lines.append(f"  {'~' * 40}")
            lines.append(f"    Trades:          {sr.trade_count} ({sr.win_count}W / {sr.loss_count}L)")
            lines.append(f"    Win Rate:        {sr.win_rate * 100:.1f}%")
            lines.append(f"    Realized P&L:    {_fmt_dollar(sr.total_pnl)}")
            if sr.unrealized_pnl:
                lines.append(f"    Unrealized P&L:  {_fmt_dollar(sr.unrealized_pnl)} (open positions)")
            lines.append(f"    Sharpe (rf=0):   {_fmt_ratio(sr.sharpe_ratio)}")
            lines.append(f"    Max Drawdown:    {_fmt_pct(sr.max_drawdown)}")
            lines.append(f"    Annualized Ret:  {_fmt_pct(sr.annualized_return)}")
            lines.append(f"    Profit Factor:   {_fmt_ratio(sr.profit_factor)}")
            lines.append(f"    Avg Winner:      {_fmt_dollar(sr.avg_winner)}")
            lines.append(f"    Avg Loser:       {_fmt_dollar(sr.avg_loser)}")
            lines.append(f"    Avg Trade P&L:   {_fmt_dollar(sr.avg_trade_pnl)}")
            lines.append(f"    Commission:      {_fmt_dollar(sr.total_commission)}")
            lines.append(f"    Symbols:         {', '.join(sr.symbols_traded[:10])}")
            if len(sr.symbols_traded) > 10:
                lines.append(f"                     ... and {len(sr.symbols_traded) - 10} more")

            # Per-symbol P&L: show worst 5 + best 5 to surface bad-apples.
            if sr.per_symbol_pnl:
                lines.append("")
                lines.append("    Per-symbol P&L (worst first):")
                worst = sr.per_symbol_pnl[:5]
                best = sr.per_symbol_pnl[-5:][::-1] if len(sr.per_symbol_pnl) > 5 else []
                for p in worst:
                    lines.append(
                        f"      {p.symbol:<8} {_fmt_dollar(p.pnl):>11}  "
                        f"({p.trades} trades, {p.wins}W/{p.losses}L)"
                    )
                if best:
                    lines.append("      ...")
                    for p in best:
                        lines.append(
                            f"      {p.symbol:<8} {_fmt_dollar(p.pnl):>11}  "
                            f"({p.trades} trades, {p.wins}W/{p.losses}L)"
                        )

        lines.append("")

    # Discovery results
    if cfg.discovery_enabled and result.discovery:
        lines.append("-" * 70)
        lines.append("DISCOVERY RESULTS")
        lines.append("-" * 70)
        lines.append(f"  Total Scans:          {result.discovery.total_scans}")
        lines.append(f"  Symbols Discovered:   {result.discovery.symbols_discovered}")
        lines.append(f"  Symbols Fed to GW:    {result.discovery.symbols_fed_to_gateway}")
        if result.discovery.symbols_fed_list:
            fed_str = ", ".join(result.discovery.symbols_fed_list[:20])
            lines.append(f"  Fed Symbols:          {fed_str}")
            if len(result.discovery.symbols_fed_list) > 20:
                lines.append(f"                        ... and {len(result.discovery.symbols_fed_list) - 20} more")
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
            "last_bar_time": result.last_bar_time.isoformat()
            if result.last_bar_time
            else None,
        },
        "results": {
            "total_orders": result.total_orders,
            "total_fills": result.total_fills,
            "final_equity": result.final_equity,
            "total_pnl": result.total_pnl,
            "total_unrealized_pnl": result.total_unrealized_pnl,
            "return_pct": (result.total_pnl / result.config.initial_capital * 100)
            if result.config.initial_capital
            else 0,
        },
        "analytics": {
            "sharpe_ratio": result.overall_sharpe,
            "max_drawdown": result.overall_max_drawdown,
            "annualized_return": result.overall_annualized_return,
            "total_return": result.overall_total_return,
            "profit_factor": result.overall_profit_factor,
            "win_rate": result.overall_win_rate,
            "total_trades": result.overall_total_trades,
            "avg_trade_pnl": result.overall_avg_trade_pnl,
            "total_commission": result.overall_total_commission,
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
                "unrealized_pnl": sr.unrealized_pnl,
                "sharpe_ratio": sr.sharpe_ratio,
                "max_drawdown": sr.max_drawdown,
                "annualized_return": sr.annualized_return,
                "total_return": sr.total_return,
                "profit_factor": sr.profit_factor,
                "avg_winner": sr.avg_winner,
                "avg_loser": sr.avg_loser,
                "avg_trade_pnl": sr.avg_trade_pnl,
                "total_commission": sr.total_commission,
                "symbols_traded": sr.symbols_traded,
                "per_symbol_pnl": [
                    {
                        "symbol": p.symbol,
                        "pnl": p.pnl,
                        "trades": p.trades,
                        "wins": p.wins,
                        "losses": p.losses,
                    }
                    for p in sr.per_symbol_pnl
                ],
            }
            for sr in result.strategy_results
        ],
        "discovery": {
            "total_scans": result.discovery.total_scans,
            "symbols_discovered": result.discovery.symbols_discovered,
            "symbols_fed_to_gateway": result.discovery.symbols_fed_to_gateway,
            "symbols_fed_list": result.discovery.symbols_fed_list,
        },
    }
    return json.dumps(data, indent=2)
