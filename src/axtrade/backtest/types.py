"""Backtest data types."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional


@dataclass
class BacktestConfig:
    """Configuration for a backtest run."""

    strategy_type: str
    strategy_id: str
    symbol: str
    start_date: date
    end_date: date
    strategy_config: dict = field(default_factory=dict)
    interval: str = "1m"
    initial_capital: Decimal = Decimal("100000")
    commission_per_trade: Decimal = Decimal("1.00")
    slippage_bps: int = 5


@dataclass
class TradeRecord:
    """Record of a single trade execution."""

    timestamp: datetime
    side: str  # "BUY" or "SELL"
    quantity: Decimal
    price: Decimal
    commission: Decimal
    pnl: Optional[Decimal] = None  # None for opening trades

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "side": self.side,
            "quantity": str(self.quantity),
            "price": str(self.price),
            "commission": str(self.commission),
            "pnl": str(self.pnl) if self.pnl is not None else None,
        }


@dataclass
class EquityPoint:
    """Point on the equity curve."""

    timestamp: datetime
    equity: Decimal
    drawdown: Decimal  # Percentage drawdown from peak

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "equity": str(self.equity),
            "drawdown": str(self.drawdown),
        }


@dataclass
class BacktestResult:
    """Results from a backtest run."""

    config: BacktestConfig
    trades: list[TradeRecord]
    equity_curve: list[EquityPoint]

    # Summary metrics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_return: float = 0.0
    annualized_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    avg_trade_pnl: Decimal = Decimal("0")
    avg_winner: Decimal = Decimal("0")
    avg_loser: Decimal = Decimal("0")
    total_commission: Decimal = Decimal("0")

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "strategy_type": self.config.strategy_type,
            "strategy_id": self.config.strategy_id,
            "symbol": self.config.symbol,
            "interval": self.config.interval,
            "start_date": self.config.start_date.isoformat(),
            "end_date": self.config.end_date.isoformat(),
            "initial_capital": str(self.config.initial_capital),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "total_return": self.total_return,
            "annualized_return": self.annualized_return,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "profit_factor": self.profit_factor,
            "avg_trade_pnl": str(self.avg_trade_pnl),
            "avg_winner": str(self.avg_winner),
            "avg_loser": str(self.avg_loser),
            "total_commission": str(self.total_commission),
            "trades": [t.to_dict() for t in self.trades],
        }
