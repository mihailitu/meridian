"""Backtest CLI command."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

from axtrade.backtest import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    HistoricalDataLoader,
)
from axtrade.common import DatabasePool, load_config


async def backtest_command(
    symbol: str,
    start: date,
    end: date,
    strategy: Optional[str] = None,
    interval: str = "1m",
    capital: float = 100000,
    position_size: int = 100,
    rsi_oversold: int = 40,
    rsi_overbought: int = 70,
    stop_loss: float = 0.02,
    data_dir: Optional[str] = None,
    use_db: bool = False,
) -> None:
    """Run backtest with given parameters.

    Args:
        symbol: Symbol to backtest
        start: Start date
        end: End date
        strategy: Strategy type (e.g., 'momentum'). If None, uses first enabled from config
        interval: Bar interval
        capital: Initial capital
        position_size: Position size in shares
        rsi_oversold: RSI oversold threshold
        rsi_overbought: RSI overbought threshold
        stop_loss: Stop loss percentage
        data_dir: Directory with historical data files. If None, uses default
        use_db: Force database usage instead of file-based data
    """
    config = load_config()

    # Determine strategy type
    strategy_type = strategy
    strategy_config = {}

    if strategy_type is None:
        # Get first enabled strategy from config
        enabled_strategies = config.strategies.get("enabled", [])
        for strat in enabled_strategies:
            if strat.get("enabled", True):
                strategy_type = strat["type"]
                strategy_config = strat.get("config", {})
                print(f"Using strategy from config: {strategy_type}")
                break

        if strategy_type is None:
            print("Error: No strategy specified and no enabled strategies in config")
            return

    # Override config with CLI args if using explicit strategy
    if strategy is not None:
        strategy_config = {
            "rsi_oversold": rsi_oversold,
            "rsi_overbought": rsi_overbought,
            "stop_loss_pct": stop_loss,
            "position_size": position_size,
        }

    bt_config = BacktestConfig(
        strategy_type=strategy_type,
        strategy_id=f"{strategy_type}_bt",
        symbol=symbol,
        start_date=start,
        end_date=end,
        strategy_config=strategy_config,
        interval=interval,
        initial_capital=Decimal(str(capital)),
    )

    # Determine data source
    data_loader = None
    db_pool = None

    if not use_db:
        # Try file-based first
        default_data_dir = data_dir or "data/historical"
        data_path = Path(default_data_dir)

        if data_path.exists():
            loader = HistoricalDataLoader(default_data_dir)
            # Check if we have data for this symbol/interval/range
            file_info = loader.find_file(symbol, interval, start, end)
            if file_info:
                data_loader = loader
                print(f"Using file-based data: {file_info['filename']}")

    if data_loader is None:
        # Fall back to database
        print("Using database for historical data")
        db_pool = DatabasePool(config.database)
        await db_pool.connect()

    try:
        engine = BacktestEngine(bt_config, db_pool=db_pool, data_loader=data_loader)
        result = await engine.run()
        print_results(result)
    finally:
        if db_pool:
            await db_pool.disconnect()


def print_results(result: BacktestResult) -> None:
    """Print formatted backtest results."""
    print()
    print(f"Backtest Results: {result.config.strategy_id} ({result.config.symbol})")
    print("=" * 55)
    print(f"Period:           {result.config.start_date} to {result.config.end_date}")
    print(f"Initial Capital:  ${result.config.initial_capital:,.2f}")
    print()

    if result.total_trades == 0:
        print("No trades executed.")
        print()
        print("This could mean:")
        print("  - No historical data for this period")
        print("  - Strategy conditions were never met")
        print("  - Indicators not yet initialized (need 20+ bars for SMA)")
        return

    # Summary statistics
    print("Performance Summary")
    print("-" * 55)
    print(f"Total Trades:     {result.total_trades}")
    print(f"Winning Trades:   {result.winning_trades}")
    print(f"Losing Trades:    {result.losing_trades}")
    print(f"Win Rate:         {result.win_rate:.1f}%")
    print()
    print(f"Total Return:     {result.total_return:+.2f}%")
    print(f"Annualized Return:{result.annualized_return:+.2f}%")
    print(f"Sharpe Ratio:     {result.sharpe_ratio:.2f}")
    print(f"Max Drawdown:     {result.max_drawdown:.1f}%")
    print(f"Profit Factor:    {result.profit_factor:.2f}")
    print()
    print(f"Avg Trade P&L:    ${result.avg_trade_pnl:,.2f}")
    print(f"Avg Winner:       ${result.avg_winner:,.2f}")
    print(f"Avg Loser:        ${result.avg_loser:,.2f}")
    print(f"Total Commission: ${result.total_commission:,.2f}")
    print()

    # Trade log
    if result.trades:
        print("Trade Log")
        print("-" * 55)
        print(f"{'Time':<20} {'Side':<6} {'Qty':<6} {'Price':<10} {'P&L':<12}")
        print("-" * 55)
        for trade in result.trades:
            time_str = trade.timestamp.strftime("%Y-%m-%d %H:%M")
            pnl_str = f"${trade.pnl:+,.2f}" if trade.pnl else ""
            print(
                f"{time_str:<20} {trade.side:<6} {trade.quantity:<6} "
                f"${trade.price:<9,.2f} {pnl_str:<12}"
            )
        print()


def parse_date(date_str: str) -> date:
    """Parse date string in YYYY-MM-DD format."""
    from datetime import datetime

    return datetime.strptime(date_str, "%Y-%m-%d").date()
