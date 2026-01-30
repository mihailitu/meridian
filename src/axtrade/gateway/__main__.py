"""Entry point for running gateway as a module."""

import argparse
import asyncio

from .service import run_gateway


def main():
    parser = argparse.ArgumentParser(description="axtrade Gateway Service")
    parser.add_argument("--config", "-c", help="Path to config file")
    parser.add_argument(
        "--adapter",
        "-a",
        choices=["mock", "ibkr"],
        help="Override adapter type",
    )
    args = parser.parse_args()

    asyncio.run(run_gateway(config_path=args.config, adapter=args.adapter))


if __name__ == "__main__":
    main()
