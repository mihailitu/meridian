"""Entry point for axtrade gateway."""

import argparse
import asyncio

from .common import setup_logging
from .gateway import run_gateway


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="AXTrade Data Gateway",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--adapter",
        choices=["mock", "ibkr"],
        default=None,
        help="Data adapter to use (overrides config)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to configuration file",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level",
    )

    args = parser.parse_args()

    setup_logging(args.log_level)

    asyncio.run(run_gateway(config_path=args.config, adapter=args.adapter))


if __name__ == "__main__":
    main()
