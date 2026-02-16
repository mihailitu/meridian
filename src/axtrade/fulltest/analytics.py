"""Analytics bridge for full system backtest.

Transforms fills stored in TimescaleDB into TradeRecord and EquityPoint
sequences suitable for the existing PerformanceAnalyzer.
"""

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

import asyncpg

from axtrade.backtest.analytics import PerformanceAnalyzer
from axtrade.backtest.types import EquityPoint, TradeRecord


async def _fetch_fills(
    conn: asyncpg.Connection,
    strategy_id: Optional[str] = None,
) -> list:
    """Fetch fills from DB ordered chronologically."""
    if strategy_id:
        return await conn.fetch(
            """
            SELECT strategy_id, symbol, side, quantity, price, commission, filled_at
            FROM fills
            WHERE strategy_id = $1
            ORDER BY filled_at ASC
            """,
            strategy_id,
        )
    return await conn.fetch(
        """
        SELECT strategy_id, symbol, side, quantity, price, commission, filled_at
        FROM fills
        ORDER BY filled_at ASC
        """
    )


def _process_fills(
    rows: list,
    initial_capital: Decimal,
) -> tuple[list[TradeRecord], list[EquityPoint]]:
    """Process fill rows into trade records and equity curve in one pass.

    FIFO matches sells against buys per (strategy_id, symbol). Simultaneously
    tracks cash and position cost basis for the equity curve.

    Args:
        rows: Fill rows with strategy_id, symbol, side, quantity, price,
              commission, filled_at fields
        initial_capital: Starting cash for equity curve

    Returns:
        Tuple of (trade_records, equity_curve)
    """
    trades: list[TradeRecord] = []
    curve: list[EquityPoint] = []

    if not rows:
        return trades, curve

    # FIFO buy lots per (strategy_id, symbol): [[qty, price, commission], ...]
    buy_lots: dict[tuple[str, str], list[list]] = defaultdict(list)

    cash = initial_capital
    open_position_cost = Decimal("0")
    peak = initial_capital

    for row in rows:
        key = (row["strategy_id"], row["symbol"])
        qty = Decimal(str(row["quantity"]))
        price = Decimal(str(row["price"]))
        commission = Decimal(str(row["commission"]))
        filled_at = row["filled_at"]

        if row["side"] == "buy":
            buy_lots[key].append([qty, price, commission])

            # Equity: cash decreases by cost + commission, position value increases by cost
            cash -= price * qty + commission
            open_position_cost += price * qty

            trades.append(TradeRecord(
                timestamp=filled_at,
                side="BUY",
                quantity=qty,
                price=price,
                commission=commission,
                pnl=None,
            ))
        else:
            # Sell -- FIFO match against buys
            remaining = qty
            total_pnl = Decimal("0")
            total_buy_commission = Decimal("0")
            cost_basis_sold = Decimal("0")

            while remaining > 0 and buy_lots[key]:
                lot = buy_lots[key][0]
                lot_qty, lot_price, lot_commission = lot

                match_qty = min(remaining, lot_qty)

                total_pnl += (price - lot_price) * match_qty
                buy_comm_portion = lot_commission * (match_qty / lot_qty)
                total_buy_commission += buy_comm_portion
                cost_basis_sold += lot_price * match_qty

                remaining -= match_qty

                if match_qty >= lot_qty:
                    buy_lots[key].pop(0)
                else:
                    new_qty = lot_qty - match_qty
                    new_commission = lot_commission * (new_qty / lot_qty)
                    buy_lots[key][0] = [new_qty, lot_price, new_commission]

            total_pnl -= total_buy_commission + commission

            # Equity: cash increases by proceeds, position cost decreases by sold cost basis
            cash += price * qty - commission
            open_position_cost -= cost_basis_sold

            trades.append(TradeRecord(
                timestamp=filled_at,
                side="SELL",
                quantity=qty,
                price=price,
                commission=commission,
                pnl=total_pnl,
            ))

        equity = cash + open_position_cost
        if equity > peak:
            peak = equity

        drawdown = Decimal("0")
        if peak > 0:
            drawdown = (peak - equity) / peak * 100

        curve.append(EquityPoint(
            timestamp=filled_at,
            equity=equity,
            drawdown=drawdown,
        ))

    return trades, curve


async def build_trade_records(
    conn: asyncpg.Connection,
    strategy_id: Optional[str] = None,
) -> list[TradeRecord]:
    """Build TradeRecords from fills using FIFO matching.

    Queries fills ordered by filled_at ASC and matches sells against buys
    in FIFO order per (strategy_id, symbol). Buy fills produce TradeRecords
    with pnl=None. Sell fills produce TradeRecords with pnl computed from
    the matched buy price minus proportional commissions from both sides.

    Args:
        conn: Database connection
        strategy_id: Optional filter by strategy

    Returns:
        List of TradeRecords in chronological order
    """
    rows = await _fetch_fills(conn, strategy_id)
    trades, _ = _process_fills(rows, Decimal("0"))
    return trades


def build_equity_curve(
    trades: list[TradeRecord],
    initial_capital: Decimal,
) -> list[EquityPoint]:
    """Build an equity curve from trade records.

    Note: This standalone function works correctly only when trade records
    include buy-side commission info in pnl. For precise equity tracking,
    use compute_analytics which processes fills in a single pass.

    Args:
        trades: Chronological list of TradeRecords
        initial_capital: Starting cash

    Returns:
        List of EquityPoints, one per trade
    """
    if not trades:
        return []

    equity = initial_capital
    peak = initial_capital
    curve: list[EquityPoint] = []

    for trade in trades:
        if trade.side == "BUY":
            # Buying at cost basis changes equity only by commission
            equity -= trade.commission
        elif trade.pnl is not None:
            # For sell: equity changes by pnl + buy_commission_portion
            # Since pnl already deducts buy commission, and equity already
            # dropped by buy commission at buy time, we add back the full pnl
            # plus buy commission to avoid double-counting.
            # Simplified: equity change = sell_proceeds - cost_basis_sold
            # = (sell_price * qty - sell_commission) - buy_price * qty
            # = (sell_price - buy_price) * qty - sell_commission
            # = pnl + buy_commission (since pnl = above - buy_commission)
            # We don't have buy_commission, so we approximate using total
            # commissions on the trade. For precise tracking, use _process_fills.
            equity += trade.pnl + trade.commission
            # This gives: equity_change = pnl + sell_commission
            # Which equals: (sell-buy)*qty - buy_comm
            # Close but not exact. Use _process_fills for precision.

        if equity > peak:
            peak = equity

        drawdown = Decimal("0")
        if peak > 0:
            drawdown = (peak - equity) / peak * 100

        curve.append(EquityPoint(
            timestamp=trade.timestamp,
            equity=equity,
            drawdown=drawdown,
        ))

    return curve


def resample_equity_daily(curve: list[EquityPoint]) -> list[EquityPoint]:
    """Collapse equity curve to one point per calendar day (last point wins).

    Needed for Sharpe calculation with daily frequency.

    Args:
        curve: Intraday equity curve

    Returns:
        Daily equity curve
    """
    if not curve:
        return []

    daily: dict[date, EquityPoint] = {}
    for point in curve:
        day = point.timestamp.date() if isinstance(point.timestamp, datetime) else point.timestamp
        daily[day] = point

    return [daily[d] for d in sorted(daily.keys())]


async def compute_analytics(
    conn: asyncpg.Connection,
    strategy_id: Optional[str],
    initial_capital: float,
    start_date: date,
    end_date: date,
) -> dict:
    """Compute full analytics for a strategy or overall portfolio.

    Processes fills in a single pass for both trade records and equity curve,
    ensuring precise cost-basis tracking.

    Args:
        conn: Database connection
        strategy_id: Strategy to analyze, or None for portfolio-level
        initial_capital: Starting capital
        start_date: Backtest start date
        end_date: Backtest end date

    Returns:
        Dictionary of performance metrics from PerformanceAnalyzer
    """
    capital = Decimal(str(initial_capital))

    rows = await _fetch_fills(conn, strategy_id)
    if not rows:
        return PerformanceAnalyzer.calculate_metrics(
            [], [], capital, start_date, end_date
        )

    trades, curve = _process_fills(rows, capital)
    daily_curve = resample_equity_daily(curve)

    metrics = PerformanceAnalyzer.calculate_metrics(
        trades, daily_curve, capital, start_date, end_date
    )

    # Override Sharpe with daily-frequency calculation
    metrics["sharpe_ratio"] = PerformanceAnalyzer.calculate_sharpe(
        daily_curve, periods_per_year=252
    )

    return metrics
