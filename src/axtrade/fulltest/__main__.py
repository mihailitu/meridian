"""CLI entry point for full system backtest.

Usage:
    # Download data separately
    python -m axtrade.fulltest download \\
        --start 2025-08-01 --end 2026-02-01 \\
        --symbols AAPL MSFT GOOGL

    # Download all S&P 500 symbols
    python -m axtrade.fulltest download \\
        --start 2025-08-01 --end 2026-02-01 \\
        --universe sp500

    # Run backtest (uses already-downloaded data)
    python -m axtrade.fulltest run \\
        --start 2025-08-01 --end 2026-02-01 \\
        --symbols AAPL MSFT GOOGL \\
        --capital 100000

    # Run backtest with auto-download of missing data
    python -m axtrade.fulltest run \\
        --start 2025-08-01 --end 2026-02-01 \\
        --symbols AAPL MSFT GOOGL \\
        --download
"""

import argparse
import asyncio
import sys
from datetime import date

from axtrade.common import setup_logging


def parse_date(s: str) -> date:
    """Parse a YYYY-MM-DD date string."""
    return date.fromisoformat(s)


def _resolve_symbols(args) -> list[str]:
    """Resolve symbol list from args."""
    universe = getattr(args, "universe", None)
    if universe == "sp500":
        from .universe import SP500SymbolProvider
        provider = SP500SymbolProvider()
        symbols = asyncio.run(provider.get_symbols())
        print(f"Using S&P 500 universe: {len(symbols)} symbols")
        return symbols
    elif universe == "sp1500":
        from .universe import SP1500SymbolProvider
        provider = SP1500SymbolProvider()
        symbols = asyncio.run(provider.get_symbols())
        print(f"Using S&P 1500 universe: {len(symbols)} symbols")
        return symbols
    elif args.symbols:
        return [s.upper() for s in args.symbols]
    else:
        from axtrade.common import load_config
        config = load_config()
        symbols = [s.symbol for s in config.gateway.symbols]
        if not symbols:
            print("No symbols specified. Use --symbols, --universe sp500, or --universe sp1500.")
            sys.exit(1)
        return symbols


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add arguments shared by download and run subcommands."""
    parser.add_argument(
        "--start", required=True, type=parse_date, help="Start date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--end", required=True, type=parse_date, help="End date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--symbols", nargs="+", default=None, help="Symbols to process"
    )
    parser.add_argument(
        "--universe", choices=["sp500", "sp1500"], default=None,
        help="Use a predefined symbol universe instead of --symbols"
    )
    parser.add_argument(
        "--interval", default="1m", help="Bar interval (default: 1m)"
    )
    parser.add_argument(
        "--data-dir", default="data/historical",
        help="Historical data directory (default: data/historical)"
    )


def download_command(args) -> None:
    """Download historical data without running a backtest."""
    from .data import download_historical_alpaca

    setup_logging(log_name="fulltest")
    symbols = _resolve_symbols(args)

    print(f"Downloading {len(symbols)} symbols from {args.start} to {args.end}...")

    result = asyncio.run(download_historical_alpaca(
        symbols=symbols,
        start=args.start,
        end=args.end,
        interval=args.interval,
        data_dir=args.data_dir,
    ))

    downloaded = len(result)
    skipped = len(symbols) - downloaded
    print(f"\nComplete: {downloaded} downloaded, {skipped} skipped (already existed or failed)")


def run_command(args) -> None:
    """Run the backtest using existing (or auto-downloaded) data."""
    from .orchestrator import FullBacktestOrchestrator
    from .types import FullBacktestConfig

    setup_logging(log_name="fulltest")
    symbols = _resolve_symbols(args)

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
        skip_download=not args.download,
    )

    orchestrator = FullBacktestOrchestrator(bt_config)

    try:
        asyncio.run(orchestrator.run())
    except KeyboardInterrupt:
        print("\nBacktest interrupted.")
        sys.exit(1)
    except Exception as e:
        print(f"\nBacktest failed: {e}")
        sys.exit(1)


def main() -> None:
    """Main CLI entry point with download and run subcommands."""
    parser = argparse.ArgumentParser(
        prog="axtrade.fulltest",
        description="Full system backtest -- download data and run pipeline replay",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- download subcommand ---
    dl_parser = subparsers.add_parser(
        "download", help="Download historical data via Alpaca API"
    )
    _add_common_args(dl_parser)

    # --- run subcommand ---
    run_parser = subparsers.add_parser(
        "run", help="Run backtest against downloaded data"
    )
    _add_common_args(run_parser)
    run_parser.add_argument(
        "--capital", type=float, default=100000,
        help="Initial capital (default: 100000)"
    )
    run_parser.add_argument(
        "--ticks-per-bar", type=int, default=4,
        help="Synthetic ticks per bar (default: 4)"
    )
    run_parser.add_argument(
        "--no-discovery", action="store_true",
        help="Disable discovery scanning"
    )
    run_parser.add_argument(
        "--discovery-interval", type=int, default=60,
        help="Discovery scan interval in bars (default: 60)"
    )
    run_parser.add_argument(
        "--format", choices=["text", "json"], default="text",
        help="Report format (default: text)"
    )
    run_parser.add_argument(
        "--output-dir", default="data/fulltest_results",
        help="Output directory for reports (default: data/fulltest_results)"
    )
    run_parser.add_argument(
        "--redis-db", type=int, default=1,
        help="Redis database number for isolation (default: 1)"
    )
    run_parser.add_argument(
        "--db-name", default="axtrade_backtest",
        help="Backtest database name (default: axtrade_backtest)"
    )
    run_parser.add_argument(
        "--download", action="store_true",
        help="Auto-download missing data before running (default: skip download)"
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "download":
        download_command(args)
    elif args.command == "run":
        run_command(args)


if __name__ == "__main__":
    main()
