"""CLI entry point for axtrade."""

import argparse
import asyncio
import sys

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
    bt_parser.add_argument("strategy", help="Strategy type (e.g., momentum)")
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

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "bars":
        asyncio.run(bars_command(args.symbol, args.limit, args.interval))
    elif args.command == "backtest":
        asyncio.run(
            backtest_command(
                strategy=args.strategy,
                symbol=args.symbol,
                start=args.start,
                end=args.end,
                interval=args.interval,
                capital=args.capital,
                position_size=args.position_size,
                rsi_oversold=args.rsi_oversold,
                rsi_overbought=args.rsi_overbought,
                stop_loss=args.stop_loss,
            )
        )


if __name__ == "__main__":
    main()
