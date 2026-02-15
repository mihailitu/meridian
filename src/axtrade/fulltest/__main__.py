"""CLI entry point for full system backtest.

Usage:
    python -m axtrade.fulltest \\
        --start 2025-08-01 --end 2026-02-01 \\
        --symbols AAPL MSFT GOOGL AMZN NVDA META TSLA \\
        --interval 1m \\
        --capital 100000 \\
        --format text
"""

import argparse
import asyncio
import sys
from datetime import date

from axtrade.common import setup_logging

from .orchestrator import FullBacktestOrchestrator
from .types import FullBacktestConfig


def parse_date(s: str) -> date:
    """Parse a YYYY-MM-DD date string."""
    return date.fromisoformat(s)


def main() -> None:
    """Run the full system backtest from command line."""
    parser = argparse.ArgumentParser(
        prog="axtrade.fulltest",
        description="Run a full system backtest through the complete pipeline",
    )
    parser.add_argument(
        "--start",
        required=True,
        type=parse_date,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        required=True,
        type=parse_date,
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="Symbols to backtest (default: uses config)",
    )
    parser.add_argument(
        "--universe",
        choices=["sp500"],
        default=None,
        help="Use a predefined symbol universe instead of --symbols",
    )
    parser.add_argument(
        "--interval",
        default="1m",
        help="Bar interval (default: 1m)",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100000,
        help="Initial capital (default: 100000)",
    )
    parser.add_argument(
        "--data-dir",
        default="data/historical",
        help="Historical data directory (default: data/historical)",
    )
    parser.add_argument(
        "--ticks-per-bar",
        type=int,
        default=4,
        help="Synthetic ticks per bar (default: 4)",
    )
    parser.add_argument(
        "--no-discovery",
        action="store_true",
        help="Disable discovery scanning",
    )
    parser.add_argument(
        "--discovery-interval",
        type=int,
        default=60,
        help="Discovery scan interval in bars (default: 60)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Report format (default: text)",
    )
    parser.add_argument(
        "--output-dir",
        default="data/fulltest_results",
        help="Output directory for reports (default: data/fulltest_results)",
    )
    parser.add_argument(
        "--redis-db",
        type=int,
        default=1,
        help="Redis database number for isolation (default: 1)",
    )
    parser.add_argument(
        "--db-name",
        default="axtrade_backtest",
        help="Backtest database name (default: axtrade_backtest)",
    )

    args = parser.parse_args()

    setup_logging(log_name="fulltest")

    # Resolve symbols
    if args.universe == "sp500":
        from .universe import SP500SymbolProvider
        provider = SP500SymbolProvider()
        symbols = asyncio.run(provider.get_symbols())
        print(f"Using S&P 500 universe: {len(symbols)} symbols")
    elif args.symbols:
        symbols = [s.upper() for s in args.symbols]
    else:
        from axtrade.common import load_config
        config = load_config()
        symbols = [s.symbol for s in config.gateway.symbols]
        if not symbols:
            print("No symbols specified and none in config. Use --symbols or --universe sp500.")
            sys.exit(1)

    bt_config = FullBacktestConfig(
        start=args.start,
        end=args.end,
        symbols=symbols,
        interval=args.interval,
        data_dir=args.data_dir,
        ticks_per_bar=args.ticks_per_bar,
        redis_db=args.redis_db,
        backtest_db_name=args.db_name,
        initial_capital=args.capital,
        discovery_enabled=not args.no_discovery,
        discovery_scan_interval_bars=args.discovery_interval,
        output_dir=args.output_dir,
        report_format=args.format,
    )

    orchestrator = FullBacktestOrchestrator(bt_config)

    try:
        result = asyncio.run(orchestrator.run())
    except KeyboardInterrupt:
        print("\nBacktest interrupted.")
        sys.exit(1)
    except Exception as e:
        print(f"\nBacktest failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
