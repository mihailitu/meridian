"""Data types for full system backtest."""

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional


@dataclass
class FullBacktestConfig:
    """Configuration for a full system backtest run."""

    start: date
    end: date
    symbols: list[str]
    interval: str = "1m"
    data_dir: str = "data/historical"
    ticks_per_bar: int = 4
    redis_db: int = 1
    backtest_db_name: str = "axtrade_backtest"
    stream_prefix: str = "bt:stream"
    consumer_group_prefix: str = "bt_"
    initial_capital: float = 100000.0
    discovery_enabled: bool = True
    discovery_scan_interval_bars: int = 60
    output_dir: str = "data/fulltest_results"
    report_format: str = "text"
    skip_download: bool = True
    strategies: list[str] | None = None


@dataclass
class TradeRecord:
    """A single trade for reporting."""

    strategy_id: str
    symbol: str
    side: str
    quantity: str
    price: str
    filled_at: Optional[datetime] = None


@dataclass
class StrategyResult:
    """Results for a single strategy."""

    strategy_id: str
    strategy_type: str
    trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: Optional[float] = None
    profit_factor: Optional[float] = None
    annualized_return: Optional[float] = None
    total_return: Optional[float] = None
    avg_winner: Optional[float] = None
    avg_loser: Optional[float] = None
    avg_trade_pnl: Optional[float] = None
    total_commission: Optional[float] = None
    symbols_traded: list[str] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        closed = self.win_count + self.loss_count
        if closed == 0:
            return 0.0
        return self.win_count / closed


@dataclass
class DiscoveryResultSummary:
    """Summary of discovery results."""

    total_scans: int = 0
    symbols_discovered: int = 0
    symbols_fed_to_gateway: int = 0
    symbols_fed_list: list[str] = field(default_factory=list)
    screener_stats: dict[str, int] = field(default_factory=dict)
    top_symbols: list[dict] = field(default_factory=list)


@dataclass
class FullBacktestResult:
    """Complete results from a full system backtest."""

    config: FullBacktestConfig
    start_time: datetime
    end_time: datetime
    total_bars_processed: int = 0
    total_ticks_generated: int = 0
    total_orders: int = 0
    total_fills: int = 0
    final_equity: float = 0.0
    strategy_results: list[StrategyResult] = field(default_factory=list)
    discovery: DiscoveryResultSummary = field(default_factory=DiscoveryResultSummary)
    overall_sharpe: Optional[float] = None
    overall_max_drawdown: Optional[float] = None
    overall_annualized_return: Optional[float] = None
    overall_total_return: Optional[float] = None
    overall_profit_factor: Optional[float] = None
    overall_win_rate: Optional[float] = None
    overall_total_trades: int = 0
    overall_avg_trade_pnl: Optional[float] = None
    overall_total_commission: Optional[float] = None

    @property
    def wall_clock_seconds(self) -> float:
        return (self.end_time - self.start_time).total_seconds()

    @property
    def total_pnl(self) -> float:
        return sum(s.total_pnl for s in self.strategy_results)
