"""Backtest engine for strategy evaluation."""

from typing import Optional

from axtrade.common import BarRepository, DatabasePool
from axtrade.strategies import STRATEGY_TYPES, BarWithIndicators, BaseStrategy

from .analytics import PerformanceAnalyzer
from .broker import SimulatedBroker
from .data_loader import HistoricalDataLoader
from .types import BacktestConfig, BacktestResult


class BacktestEngine:
    """Event-driven backtesting engine."""

    def __init__(
        self,
        config: BacktestConfig,
        db_pool: Optional[DatabasePool] = None,
        data_loader: Optional[HistoricalDataLoader] = None,
    ):
        """Initialize backtest engine.

        Args:
            config: Backtest configuration
            db_pool: Database connection pool (optional)
            data_loader: Historical data loader for file-based data (optional)

        Note:
            At least one of db_pool or data_loader must be provided.
            If both are provided, data_loader takes priority.
        """
        self.config = config
        self.db_pool = db_pool
        self.data_loader = data_loader

        if db_pool is None and data_loader is None:
            raise ValueError("Either db_pool or data_loader must be provided")

        self.bar_repo = BarRepository(db_pool) if db_pool else None
        self.broker: SimulatedBroker | None = None
        self.strategy: BaseStrategy | None = None

    async def run(self) -> BacktestResult:
        """Run backtest and return results.

        Returns:
            BacktestResult with trades, equity curve, and metrics
        """
        # 1. Initialize strategy
        self._init_strategy()

        # 2. Initialize broker
        self.broker = SimulatedBroker(
            initial_capital=self.config.initial_capital,
            commission=self.config.commission_per_trade,
            slippage_bps=self.config.slippage_bps,
        )

        # 3. Load historical bars (file-based takes priority)
        bars = await self._load_bars()

        if not bars:
            # No data, return empty result
            return self._build_empty_result()

        # 4. Replay bars through strategy
        for bar_data in bars:
            bar = bar_data["bar"]
            bar_with_indicators = BarWithIndicators(
                bar=bar,
                sma_20=bar_data.get("sma_20"),
                rsi_14=bar_data.get("rsi_14"),
            )

            # Update strategy position from broker
            position = self.broker.get_position(self.config.symbol)
            if position:
                self.strategy.update_position(position)
            else:
                # Clear position in strategy if broker has none
                self.strategy.clear_position(self.config.symbol)

            # Get signal from strategy
            order = self.strategy.on_bar(bar_with_indicators)

            # Execute order if any
            if order:
                fill = self.broker.execute_order(
                    order, bar, self.config.strategy_id
                )
                if fill:
                    self.strategy.on_fill(fill)

            # Update equity curve
            self.broker.update_equity(bar, bar.timestamp)

        # 5. Calculate metrics
        metrics = PerformanceAnalyzer.calculate_metrics(
            trades=self.broker.trades,
            equity_curve=self.broker.equity_curve,
            initial_capital=self.config.initial_capital,
            start_date=self.config.start_date,
            end_date=self.config.end_date,
        )

        # 6. Build result
        return BacktestResult(
            config=self.config,
            trades=self.broker.trades,
            equity_curve=self.broker.equity_curve,
            **metrics,
        )

    async def _load_bars(self) -> list[dict]:
        """Load historical bars from file or database.

        Returns:
            List of bar dictionaries with 'bar', 'sma_20', 'rsi_14' keys
        """
        # File-based loader takes priority
        if self.data_loader is not None:
            return self.data_loader.load_bars(
                symbol=self.config.symbol,
                interval=self.config.interval,
                start=self.config.start_date,
                end=self.config.end_date,
            )

        # Fall back to database
        if self.bar_repo is not None:
            return await self.bar_repo.get_bars_range(
                symbol=self.config.symbol,
                interval=self.config.interval,
                start=self.config.start_date,
                end=self.config.end_date,
            )

        return []

    def _init_strategy(self) -> None:
        """Initialize strategy instance."""
        strategy_cls = STRATEGY_TYPES.get(self.config.strategy_type)
        if not strategy_cls:
            raise ValueError(f"Unknown strategy type: {self.config.strategy_type}")

        self.strategy = strategy_cls(
            strategy_id=self.config.strategy_id,
            config=self.config.strategy_config,
        )

    def _build_empty_result(self) -> BacktestResult:
        """Build empty result when no data available."""
        return BacktestResult(
            config=self.config,
            trades=[],
            equity_curve=[],
        )
