"""CLI entry point for the phase-6 research data foundation.

Usage:
    python -m axtrade.research --data-dir data/historical --out data/daily \\
        [--benchmark SPY] [--min-dollar-volume 5e6] [--window 63] \\
        [--min-coverage 0.9] [--symbols AAPL MSFT GOOGL]

Builds daily bars, the data-driven trading calendar, per-day eligibility,
and a hygiene/survivorship report from the 1-minute historical parquet
archive. See docs/phase6-cross-sectional.md (Phase A).
"""

import argparse
from pathlib import Path

from axtrade.common import get_logger, setup_logging

from .daily import build_all, trading_calendar
from .universe import compute_eligibility, hygiene_report, survivorship_summary

logger = get_logger("research")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="axtrade.research",
        description=(
            "Build daily bars, trading calendar, eligibility and hygiene "
            "report from 1m historical data"
        ),
    )
    parser.add_argument(
        "--data-dir", default="data/historical",
        help="Directory of {SYMBOL}_1m_*.parquet files (default: data/historical)"
    )
    parser.add_argument(
        "--out", required=True, help="Output directory for research artifacts"
    )
    parser.add_argument(
        "--benchmark", default="SPY",
        help="Benchmark symbol, excluded from eligibility (default: SPY)"
    )
    parser.add_argument(
        "--min-dollar-volume", type=float, default=5_000_000.0,
        help="Minimum trailing median RTH dollar volume to be eligible (default: 5e6)"
    )
    parser.add_argument(
        "--window", type=int, default=63,
        help="Trailing window for coverage/liquidity, in trading days (default: 63)"
    )
    parser.add_argument(
        "--min-coverage", type=float, default=0.90,
        help="Minimum trailing coverage fraction to be eligible (default: 0.9)"
    )
    parser.add_argument(
        "--symbols", nargs="+", default=None,
        help="Limit the build to these symbols (for tests/smoke runs)"
    )
    return parser.parse_args(argv)


def main() -> None:
    """Build all research artifacts and write them to --out."""
    args = parse_args()
    setup_logging(log_name="research")

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Building daily bars from {data_dir} ...")
    daily = build_all(data_dir, symbols=args.symbols)
    n_symbols = daily["symbol"].nunique() if not daily.empty else 0
    daily_path = out_dir / "daily_bars.parquet"
    daily.to_parquet(daily_path, index=False)
    print(f"Wrote {daily_path} ({len(daily)} rows, {n_symbols} symbols)")

    calendar = trading_calendar(daily)
    calendar_path = out_dir / "calendar.txt"
    with open(calendar_path, "w") as f:
        for d in calendar:
            f.write(d.date().isoformat() + "\n")
    print(f"Wrote {calendar_path} ({len(calendar)} trading days)")

    benchmark_has_data = not daily.empty and (daily["symbol"] == args.benchmark).any()
    if not benchmark_has_data:
        logger.warning(
            "Benchmark symbol has no data in this build; survivorship_summary "
            "will fall back to dollar-volume weighting",
            benchmark=args.benchmark,
        )

    eligibility = compute_eligibility(
        daily,
        calendar,
        window=args.window,
        min_coverage=args.min_coverage,
        min_dollar_volume=args.min_dollar_volume,
        exclude={args.benchmark},
    )
    eligibility_path = out_dir / "eligibility.parquet"
    eligibility.to_parquet(eligibility_path, index=False)
    print(f"Wrote {eligibility_path} ({len(eligibility)} rows)")

    report = hygiene_report(
        daily,
        calendar,
        eligibility,
        exclude={args.benchmark},
        window=args.window,
        min_coverage=args.min_coverage,
        min_dollar_volume=args.min_dollar_volume,
    )
    report += "\n\n" + survivorship_summary(
        daily, eligibility, calendar, benchmark_symbol=args.benchmark
    )
    report_path = out_dir / "hygiene_report.md"
    with open(report_path, "w") as f:
        f.write(report)
    print(f"Wrote {report_path}")

    if not eligibility.empty:
        per_day = eligibility.groupby("date")["eligible"].sum()
        print(
            f"Eligible-universe size range: min={int(per_day.min())} "
            f"median={per_day.median():.0f} max={int(per_day.max())}"
        )
    else:
        print("Eligible-universe size range: n/a (no eligibility rows)")


if __name__ == "__main__":
    main()
