"""CLI entry point for axtrade."""

import argparse
import asyncio
import sys
from datetime import date

from .backtest import backtest_command, parse_date
from .bars import bars_command


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="axtrade",
        description="axtrade CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # bars command
    bars_parser = subparsers.add_parser("bars", help="Query historical bars")
    bars_parser.add_argument("symbol", help="Symbol to query (e.g., AAPL)")
    bars_parser.add_argument(
        "--limit", "-l", type=int, default=10, help="Number of bars to show (default: 10)"
    )
    bars_parser.add_argument(
        "--interval", "-i", default="1m", help="Bar interval (default: 1m)"
    )

    # backtest command
    bt_parser = subparsers.add_parser("backtest", help="Run strategy backtest")
    bt_parser.add_argument(
        "--strategy",
        help="Strategy type (e.g., momentum). If not specified, uses first enabled from config",
    )
    bt_parser.add_argument("--symbol", "-s", required=True, help="Symbol to backtest")
    bt_parser.add_argument(
        "--start", required=True, type=parse_date, help="Start date (YYYY-MM-DD)"
    )
    bt_parser.add_argument(
        "--end", required=True, type=parse_date, help="End date (YYYY-MM-DD)"
    )
    bt_parser.add_argument("--interval", "-i", default="1m", help="Bar interval")
    bt_parser.add_argument(
        "--capital", type=float, default=100000, help="Initial capital (default: 100000)"
    )
    bt_parser.add_argument(
        "--position-size", type=int, default=100, help="Position size (default: 100)"
    )
    bt_parser.add_argument(
        "--rsi-oversold", type=int, default=40, help="RSI oversold threshold (default: 40)"
    )
    bt_parser.add_argument(
        "--rsi-overbought", type=int, default=70, help="RSI overbought threshold (default: 70)"
    )
    bt_parser.add_argument(
        "--stop-loss", type=float, default=0.02, help="Stop loss percentage (default: 0.02)"
    )
    bt_parser.add_argument(
        "--data-dir",
        help="Directory with historical data files (default: data/historical)",
    )
    bt_parser.add_argument(
        "--use-db",
        action="store_true",
        help="Force database usage instead of file-based data",
    )

    # fulltest command
    ft_parser = subparsers.add_parser("fulltest", help="Run full system backtest")
    ft_parser.add_argument(
        "--start", required=True, type=parse_date, help="Start date (YYYY-MM-DD)"
    )
    ft_parser.add_argument(
        "--end", required=True, type=parse_date, help="End date (YYYY-MM-DD)"
    )
    ft_parser.add_argument(
        "--symbols", nargs="+", default=None, help="Symbols to backtest"
    )
    ft_parser.add_argument(
        "--universe", choices=["sp500"], default=None,
        help="Use a predefined symbol universe instead of --symbols"
    )
    ft_parser.add_argument(
        "--interval", "-i", default="1m", help="Bar interval (default: 1m)"
    )
    ft_parser.add_argument(
        "--capital", type=float, default=100000, help="Initial capital (default: 100000)"
    )
    ft_parser.add_argument(
        "--data-dir", default="data/historical", help="Historical data directory"
    )
    ft_parser.add_argument(
        "--no-discovery", action="store_true", help="Disable discovery scanning"
    )
    ft_parser.add_argument(
        "--format", choices=["text", "json"], default="text", help="Report format"
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "bars":
        asyncio.run(bars_command(args.symbol, args.limit, args.interval))
    elif args.command == "fulltest":
        from axtrade.fulltest.orchestrator import FullBacktestOrchestrator
        from axtrade.fulltest.types import FullBacktestConfig

        if getattr(args, "universe", None) == "sp500":
            from axtrade.fulltest.universe import SP500SymbolProvider
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
            initial_capital=args.capital,
            discovery_enabled=not args.no_discovery,
            report_format=args.format,
        )
        orchestrator = FullBacktestOrchestrator(bt_config)
        asyncio.run(orchestrator.run())
    elif args.command == "backtest":
        asyncio.run(
            backtest_command(
                symbol=args.symbol,
                start=args.start,
                end=args.end,
                strategy=args.strategy,
                interval=args.interval,
                capital=args.capital,
                position_size=args.position_size,
                rsi_oversold=args.rsi_oversold,
                rsi_overbought=args.rsi_overbought,
                stop_loss=args.stop_loss,
                data_dir=args.data_dir,
                use_db=args.use_db,
            )
        )


if __name__ == "__main__":
    main()
