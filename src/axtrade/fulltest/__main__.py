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

    # In-sample / out-of-sample comparison: run two backtests back-to-back
    # and emit a side-by-side report.
    python -m axtrade.fulltest oos \\
        --is-start 2024-08-01 --is-end 2025-08-01 \\
        --oos-start 2025-08-01 --oos-end 2026-02-01 \\
        --symbols AAPL MSFT GOOGL AMZN NVDA \\
        --capital 100000 \\
        --strategy-overrides params.yaml
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


def _load_overrides(path: str | None) -> dict[str, dict]:
    """Load YAML strategy parameter overrides.

    Format: {strategy_type: {key: value, ...}, ...}. Returns empty dict when
    path is None.
    """
    if not path:
        return {}
    import yaml
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Strategy overrides file must be a mapping: {path}")
    for stype, patch in data.items():
        if not isinstance(patch, dict):
            raise ValueError(
                f"Strategy overrides for {stype!r} must be a mapping, got {type(patch).__name__}"
            )
    return data


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add date + universe args shared by download and run subcommands."""
    parser.add_argument(
        "--start", required=True, type=parse_date, help="Start date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--end", required=True, type=parse_date, help="End date (YYYY-MM-DD)"
    )
    _add_universe_args(parser)


def _add_universe_args(parser: argparse.ArgumentParser) -> None:
    """Add symbol / universe / interval / data_dir args."""
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


def _add_run_only_args(parser: argparse.ArgumentParser) -> None:
    """Add run-time args shared by `run` and `oos`."""
    parser.add_argument(
        "--capital", type=float, default=100000,
        help="Initial capital (default: 100000)"
    )
    parser.add_argument(
        "--ticks-per-bar", type=int, default=4,
        help="Synthetic ticks per bar (default: 4)"
    )
    parser.add_argument(
        "--no-discovery", action="store_true",
        help="Disable discovery scanning"
    )
    parser.add_argument(
        "--format", choices=["text", "json"], default="text",
        help="Report format (default: text)"
    )
    parser.add_argument(
        "--output-dir", default="data/fulltest_results",
        help="Output directory for reports (default: data/fulltest_results)"
    )
    parser.add_argument(
        "--redis-db", type=int, default=1,
        help="Redis database number for isolation (default: 1)"
    )
    parser.add_argument(
        "--db-name", default="axtrade_backtest",
        help="Backtest database name (default: axtrade_backtest)"
    )
    parser.add_argument(
        "--download", action="store_true",
        help="Auto-download missing data before running (default: skip download)"
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)"
    )
    parser.add_argument(
        "--strategy-overrides", default=None,
        help="YAML file with per-strategy config overrides (strategy_type -> dict)"
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


def _build_run_config(args, start: date, end: date, symbols: list[str],
                      overrides: dict[str, dict]):
    """Construct a FullBacktestConfig from shared CLI args."""
    from .types import FullBacktestConfig
    return FullBacktestConfig(
        start=start,
        end=end,
        symbols=symbols,
        interval=args.interval,
        data_dir=args.data_dir,
        ticks_per_bar=args.ticks_per_bar,
        redis_db=args.redis_db,
        backtest_db_name=args.db_name,
        initial_capital=args.capital,
        discovery_enabled=not args.no_discovery,
        output_dir=args.output_dir,
        report_format=args.format,
        skip_download=not args.download,
        strategy_overrides=overrides,
    )


def run_command(args) -> None:
    """Run the backtest using existing (or auto-downloaded) data."""
    from .orchestrator import FullBacktestOrchestrator

    setup_logging(level=args.log_level, log_name="fulltest")
    symbols = _resolve_symbols(args)
    overrides = _load_overrides(args.strategy_overrides)

    bt_config = _build_run_config(args, args.start, args.end, symbols, overrides)
    orchestrator = FullBacktestOrchestrator(bt_config)

    try:
        asyncio.run(orchestrator.run())
    except KeyboardInterrupt:
        print("\nBacktest interrupted.")
        sys.exit(1)
    except Exception as e:
        print(f"\nBacktest failed: {e}")
        sys.exit(1)


def oos_command(args) -> None:
    """Run IS and OOS backtests back-to-back, emit a comparison report."""
    from .comparison import (
        build_comparison,
        format_comparison_json,
        format_comparison_text,
        write_comparison_report,
    )
    from .orchestrator import FullBacktestOrchestrator

    setup_logging(level=args.log_level, log_name="fulltest")
    symbols = _resolve_symbols(args)
    overrides = _load_overrides(args.strategy_overrides)

    is_cfg = _build_run_config(args, args.is_start, args.is_end, symbols, overrides)
    oos_cfg = _build_run_config(args, args.oos_start, args.oos_end, symbols, overrides)

    print(f"\n>>> IS run: {args.is_start} → {args.is_end}\n")
    try:
        is_result = asyncio.run(FullBacktestOrchestrator(is_cfg).run())
    except KeyboardInterrupt:
        print("\nIS backtest interrupted.")
        sys.exit(1)
    except Exception as e:
        print(f"\nIS backtest failed: {e}")
        sys.exit(1)

    print(f"\n>>> OOS run: {args.oos_start} → {args.oos_end}\n")
    try:
        oos_result = asyncio.run(FullBacktestOrchestrator(oos_cfg).run())
    except KeyboardInterrupt:
        print("\nOOS backtest interrupted.")
        sys.exit(1)
    except Exception as e:
        print(f"\nOOS backtest failed: {e}")
        sys.exit(1)

    comparison = build_comparison(
        is_result=is_result,
        oos_result=oos_result,
        label=args.label,
    )
    text = format_comparison_text(comparison)
    print(text)
    txt_path, json_path = write_comparison_report(
        comparison, output_dir=args.output_dir
    )
    print(f"\nComparison report: {txt_path}")
    print(f"Comparison JSON:   {json_path}")


def main() -> None:
    """Main CLI entry point with download, run, and oos subcommands."""
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
    _add_run_only_args(run_parser)

    # --- oos subcommand ---
    oos_parser = subparsers.add_parser(
        "oos",
        help="Run paired in-sample / out-of-sample backtests and emit a comparison",
    )
    oos_parser.add_argument(
        "--is-start", required=True, type=parse_date,
        help="In-sample start date (YYYY-MM-DD)"
    )
    oos_parser.add_argument(
        "--is-end", required=True, type=parse_date,
        help="In-sample end date (YYYY-MM-DD)"
    )
    oos_parser.add_argument(
        "--oos-start", required=True, type=parse_date,
        help="Out-of-sample start date (YYYY-MM-DD)"
    )
    oos_parser.add_argument(
        "--oos-end", required=True, type=parse_date,
        help="Out-of-sample end date (YYYY-MM-DD)"
    )
    oos_parser.add_argument(
        "--label", default=None,
        help="Free-form tag stamped into the comparison report"
    )
    _add_universe_args(oos_parser)
    _add_run_only_args(oos_parser)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "download":
        download_command(args)
    elif args.command == "run":
        run_command(args)
    elif args.command == "oos":
        oos_command(args)


if __name__ == "__main__":
    main()
