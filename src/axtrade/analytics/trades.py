"""Trade statistics and analysis."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any


@dataclass
class TradeRecord:
    """Record of a completed trade."""

    trade_id: str
    symbol: str
    strategy_id: str
    side: str  # position direction, e.g. "long"
    entry_time: datetime
    exit_time: datetime
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    pnl: Decimal
    commission: Decimal = Decimal("0")

    @property
    def is_winner(self) -> bool:
        """Check if trade was profitable."""
        return self.pnl > 0

    @property
    def duration(self) -> timedelta:
        """Get trade duration."""
        return self.exit_time - self.entry_time

    @property
    def return_pct(self) -> float:
        """Get return percentage."""
        cost = self.entry_price * self.quantity
        if cost == 0:
            return 0.0
        return float(self.pnl / cost) * 100


def pair_fills_fifo(fills: Iterable[Any]) -> list[TradeRecord]:
    """Pair buy/sell fills into round-trip trades via FIFO matching.

    This is the single source of truth for turning a raw fill stream into
    `TradeRecord`s with real P&L, shared by the live API (`analytics.py`,
    `strategies.py`) and anything else that needs trade-level analytics from
    fills rather than from a backtest's own trade log. Deliberately decoupled
    from `axtrade.oms` (no imports from it) — callers pass fill-like objects
    with the attributes below rather than the concrete `Fill` dataclass, so
    this module stays usable outside the OMS.

    Args:
        fills: Iterable of fill-like objects with attributes `id`,
            `strategy_id`, `symbol`, `side`, `quantity`, `price`,
            `commission`, `filled_at`. `side` may be an enum with a `.value`
            of "buy"/"sell" or a plain string.

    Returns:
        One TradeRecord per completed round trip (each sell fill that
        matches at least one buy lot), in the order the sells were
        processed. Sells with no matching buy lot (unmatched short sells)
        produce no record.
    """
    sorted_fills = sorted(fills, key=lambda f: f.filled_at)

    # FIFO buy lots per (strategy_id, symbol): list of [qty, price, commission, filled_at]
    buy_lots: dict[tuple[str, str], list[list]] = defaultdict(list)
    trades: list[TradeRecord] = []

    for fill in sorted_fills:
        side = getattr(fill.side, "value", fill.side)
        key = (fill.strategy_id, fill.symbol)
        qty = Decimal(str(fill.quantity))
        price = Decimal(str(fill.price))
        commission = Decimal(str(fill.commission))

        if side == "buy":
            buy_lots[key].append([qty, price, commission, fill.filled_at])
            continue

        # Sell - match against buy lots in FIFO order
        lots = buy_lots.get(key)
        if not lots:
            continue  # Unmatched short sell - nothing to pair against

        remaining_sell_qty = qty
        matched_qty = Decimal("0")
        cost_basis = Decimal("0")
        buy_commission_total = Decimal("0")
        entry_time = None

        while remaining_sell_qty > 0 and lots:
            lot = lots[0]
            lot_qty, lot_price, lot_commission, lot_filled_at = lot
            match_qty = min(remaining_sell_qty, lot_qty)

            if entry_time is None:
                entry_time = lot_filled_at

            cost_basis += lot_price * match_qty
            buy_commission_total += lot_commission * (match_qty / lot_qty)
            matched_qty += match_qty
            remaining_sell_qty -= match_qty

            if match_qty >= lot_qty:
                lots.pop(0)
            else:
                # Partial match - shrink the remaining lot's qty and
                # proportionally reduce its unconsumed commission
                new_lot_qty = lot_qty - match_qty
                lot[0] = new_lot_qty
                lot[2] = lot_commission * (new_lot_qty / lot_qty)

        if matched_qty == 0:
            continue

        sell_commission_portion = commission * (matched_qty / qty)
        entry_price = cost_basis / matched_qty
        pnl = (price * matched_qty - cost_basis) - buy_commission_total - sell_commission_portion

        trades.append(
            TradeRecord(
                trade_id=str(fill.id),
                symbol=fill.symbol,
                strategy_id=fill.strategy_id,
                side="long",
                entry_time=entry_time,
                exit_time=fill.filled_at,
                entry_price=entry_price,
                exit_price=price,
                quantity=matched_qty,
                pnl=pnl,
                commission=buy_commission_total + sell_commission_portion,
            )
        )

    return trades


@dataclass
class TradeStats:
    """Aggregate trade statistics."""

    total_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate: float  # As percentage
    loss_rate: float
    avg_win: Decimal
    avg_loss: Decimal
    avg_trade: Decimal
    avg_win_loss_ratio: float  # avg_win / avg_loss
    profit_factor: float  # gross_profit / gross_loss
    expectancy: Decimal  # Average expected profit per trade
    total_pnl: Decimal
    gross_profit: Decimal
    gross_loss: Decimal
    largest_win: Decimal
    largest_loss: Decimal
    avg_trade_duration: timedelta
    max_consecutive_wins: int
    max_consecutive_losses: int
    current_streak: int  # Positive for wins, negative for losses


@dataclass
class TimeAnalysis:
    """Time-based performance analysis."""

    hourly_pnl: dict[int, Decimal] = field(default_factory=dict)  # Hour (0-23) -> P&L
    hourly_trades: dict[int, int] = field(default_factory=dict)  # Hour -> count
    daily_pnl: dict[str, Decimal] = field(default_factory=dict)  # "Monday" etc -> P&L
    daily_trades: dict[str, int] = field(default_factory=dict)
    monthly_pnl: dict[str, Decimal] = field(default_factory=dict)  # "2024-01" -> P&L
    monthly_trades: dict[str, int] = field(default_factory=dict)


def calculate_trade_stats(trades: list[TradeRecord]) -> TradeStats:
    """Calculate comprehensive trade statistics.

    Args:
        trades: List of completed trades

    Returns:
        TradeStats with all metrics
    """
    if not trades:
        return TradeStats(
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            breakeven_trades=0,
            win_rate=0.0,
            loss_rate=0.0,
            avg_win=Decimal("0"),
            avg_loss=Decimal("0"),
            avg_trade=Decimal("0"),
            avg_win_loss_ratio=0.0,
            profit_factor=0.0,
            expectancy=Decimal("0"),
            total_pnl=Decimal("0"),
            gross_profit=Decimal("0"),
            gross_loss=Decimal("0"),
            largest_win=Decimal("0"),
            largest_loss=Decimal("0"),
            avg_trade_duration=timedelta(0),
            max_consecutive_wins=0,
            max_consecutive_losses=0,
            current_streak=0,
        )

    # Categorize trades
    winners = [t for t in trades if t.pnl > 0]
    losers = [t for t in trades if t.pnl < 0]
    breakeven = [t for t in trades if t.pnl == 0]

    total = len(trades)
    win_count = len(winners)
    loss_count = len(losers)

    # Basic rates
    win_rate = (win_count / total) * 100 if total > 0 else 0.0
    loss_rate = (loss_count / total) * 100 if total > 0 else 0.0

    # Averages
    gross_profit = sum(t.pnl for t in winners)
    gross_loss = abs(sum(t.pnl for t in losers))
    total_pnl = sum(t.pnl for t in trades)

    avg_win = gross_profit / win_count if win_count > 0 else Decimal("0")
    avg_loss = gross_loss / loss_count if loss_count > 0 else Decimal("0")
    avg_trade = total_pnl / total if total > 0 else Decimal("0")

    # Ratios
    avg_win_loss_ratio = float(avg_win / avg_loss) if avg_loss > 0 else 0.0
    profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0

    # Expectancy: (win_rate * avg_win) - (loss_rate * avg_loss)
    expectancy = (Decimal(str(win_rate / 100)) * avg_win) - (
        Decimal(str(loss_rate / 100)) * avg_loss
    )

    # Extremes
    largest_win = max((t.pnl for t in winners), default=Decimal("0"))
    largest_loss = min((t.pnl for t in losers), default=Decimal("0"))

    # Duration
    total_duration = sum((t.duration for t in trades), timedelta(0))
    avg_duration = total_duration / total if total > 0 else timedelta(0)

    # Consecutive streaks
    max_wins, max_losses, current = _calculate_streaks(trades)

    return TradeStats(
        total_trades=total,
        winning_trades=win_count,
        losing_trades=loss_count,
        breakeven_trades=len(breakeven),
        win_rate=win_rate,
        loss_rate=loss_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        avg_trade=avg_trade,
        avg_win_loss_ratio=avg_win_loss_ratio,
        profit_factor=profit_factor,
        expectancy=expectancy,
        total_pnl=total_pnl,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        largest_win=largest_win,
        largest_loss=largest_loss,
        avg_trade_duration=avg_duration,
        max_consecutive_wins=max_wins,
        max_consecutive_losses=max_losses,
        current_streak=current,
    )


def _calculate_streaks(trades: list[TradeRecord]) -> tuple[int, int, int]:
    """Calculate consecutive win/loss streaks.

    Args:
        trades: List of trades in chronological order

    Returns:
        Tuple of (max_wins, max_losses, current_streak)
    """
    if not trades:
        return 0, 0, 0

    max_wins = 0
    max_losses = 0
    current_wins = 0
    current_losses = 0

    for trade in sorted(trades, key=lambda t: t.exit_time):
        if trade.pnl > 0:
            current_wins += 1
            current_losses = 0
            max_wins = max(max_wins, current_wins)
        elif trade.pnl < 0:
            current_losses += 1
            current_wins = 0
            max_losses = max(max_losses, current_losses)
        else:
            # Breakeven resets both
            current_wins = 0
            current_losses = 0

    # Current streak (positive for wins, negative for losses)
    current_streak = current_wins if current_wins > 0 else -current_losses

    return max_wins, max_losses, current_streak


def analyze_time_performance(trades: list[TradeRecord]) -> TimeAnalysis:
    """Analyze performance by time of day, day of week, and month.

    Args:
        trades: List of completed trades

    Returns:
        TimeAnalysis with breakdowns
    """
    analysis = TimeAnalysis()

    # Initialize with zeros
    for hour in range(24):
        analysis.hourly_pnl[hour] = Decimal("0")
        analysis.hourly_trades[hour] = 0

    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for day in days:
        analysis.daily_pnl[day] = Decimal("0")
        analysis.daily_trades[day] = 0

    for trade in trades:
        # By hour (entry time)
        hour = trade.entry_time.hour
        analysis.hourly_pnl[hour] += trade.pnl
        analysis.hourly_trades[hour] += 1

        # By day of week
        day_name = trade.entry_time.strftime("%A")
        analysis.daily_pnl[day_name] += trade.pnl
        analysis.daily_trades[day_name] += 1

        # By month
        month_key = trade.entry_time.strftime("%Y-%m")
        if month_key not in analysis.monthly_pnl:
            analysis.monthly_pnl[month_key] = Decimal("0")
            analysis.monthly_trades[month_key] = 0
        analysis.monthly_pnl[month_key] += trade.pnl
        analysis.monthly_trades[month_key] += 1

    return analysis


def calculate_per_symbol_stats(
    trades: list[TradeRecord],
) -> dict[str, TradeStats]:
    """Calculate statistics per symbol.

    Args:
        trades: List of trades

    Returns:
        Dictionary mapping symbol to TradeStats
    """
    by_symbol: dict[str, list[TradeRecord]] = defaultdict(list)
    for trade in trades:
        by_symbol[trade.symbol].append(trade)

    return {symbol: calculate_trade_stats(trades) for symbol, trades in by_symbol.items()}
