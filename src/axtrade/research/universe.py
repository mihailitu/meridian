"""Universe hygiene, per-day eligibility, and survivorship quantification.

Consumes daily.build_all() / daily.trading_calendar() output. See
docs/phase6-cross-sectional.md (Phase A).
"""

import numpy as np
import pandas as pd

from axtrade.common import get_logger

logger = get_logger("research.universe")

_WINDOW_SPLITS = [
    ("2024-08-01", "2025-08-01"),
    ("2025-08-01", "2026-02-01"),
]
_TRADING_DAYS_PER_YEAR = 252


def compute_eligibility(
    daily: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    *,
    window: int = 63,
    min_days: int = 21,
    min_coverage: float = 0.90,
    min_dollar_volume: float = 5_000_000.0,
    exclude: set[str] = frozenset(),
) -> pd.DataFrame:
    """Per (symbol, calendar date) trailing coverage/liquidity eligibility.

    NO LOOK-AHEAD: coverage and med_dollar_volume are computed from a
    trailing window ending at and including the current date only: values
    on date D never depend on data from after D. Consumers that trade at
    the next open (the realistic case) lag this by construction -- e.g. a
    strategy deciding at date D's close what to trade at D+1's open should
    use eligibility as-of D, which is what this function already returns
    for D; no additional shift is baked in here.

    Each symbol is reindexed onto `calendar`. Let idx0 be the position of
    the symbol's first calendar date with a daily row. For calendar
    position i >= idx0, elapsed = i - idx0 + 1 (trading days since the
    symbol's first appearance):
    - elapsed < min_days: coverage and med_dollar_volume are NaN (warmup;
      never eligible).
    - elapsed >= min_days: the trailing window is `window` calendar-index
      positions ending at i, expanding to `elapsed` positions while
      elapsed < window. coverage = fraction of those positions with a row;
      med_dollar_volume = NaN-skipping median of rth_dollar_volume over the
      same positions.

    Args:
        daily: build_all() output (needs symbol, date, rth_dollar_volume).
        calendar: trading_calendar() output.
        window: Trailing window length, in calendar-index positions.
        min_days: Minimum elapsed trading days since a symbol's first
            appearance before it can be eligible.
        min_coverage: Minimum trailing coverage fraction to be eligible.
        min_dollar_volume: Minimum trailing median RTH dollar volume.
        exclude: Symbols (e.g. benchmark ETFs) that are never eligible.

    Returns:
        Long frame: symbol, date, coverage, med_dollar_volume, eligible.
    """
    calendar = pd.DatetimeIndex(sorted(calendar))
    n = len(calendar)
    rows: list[pd.DataFrame] = []

    for symbol, sym_daily in daily.groupby("symbol", sort=True):
        sym_daily = sym_daily.set_index("date")
        has_row = calendar.isin(sym_daily.index)

        if not has_row.any():
            coverage = np.full(n, np.nan)
            med_dv = np.full(n, np.nan)
            eligible = np.zeros(n, dtype=bool)
        else:
            dv = sym_daily["rth_dollar_volume"].reindex(calendar).to_numpy(dtype=float)
            idx0 = int(np.argmax(has_row))
            positions = np.arange(n)
            elapsed = positions - idx0 + 1

            # Coverage via cumulative-sum trick over trailing positions.
            cum_has = np.cumsum(has_row.astype(np.int64))
            window_len = np.clip(np.minimum(elapsed, window), 1, None)
            start_idx = np.clip(positions - window_len + 1, 0, None)
            prev_cum = np.where(
                start_idx > 0, cum_has[np.clip(start_idx - 1, 0, n - 1)], 0
            )
            count_in_window = cum_has - prev_cum
            coverage = count_in_window / window_len
            coverage = np.where(elapsed < min_days, np.nan, coverage)

            # Trailing median dollar volume, NaN-skipping, same window.
            dv_from_idx0 = pd.Series(dv[idx0:])
            med_from_idx0 = dv_from_idx0.rolling(window=window, min_periods=1).median()
            med_dv = np.full(n, np.nan)
            med_dv[idx0:] = med_from_idx0.to_numpy()
            med_dv = np.where(elapsed < min_days, np.nan, med_dv)

            eligible = has_row & (coverage >= min_coverage) & (med_dv >= min_dollar_volume)

        if symbol in exclude:
            eligible = np.zeros(n, dtype=bool)

        rows.append(
            pd.DataFrame(
                {
                    "symbol": symbol,
                    "date": calendar,
                    "coverage": coverage,
                    "med_dollar_volume": med_dv,
                    "eligible": eligible,
                }
            )
        )

    if not rows:
        return pd.DataFrame(
            columns=["symbol", "date", "coverage", "med_dollar_volume", "eligible"]
        )

    result = pd.concat(rows, ignore_index=True)
    return result.sort_values(["symbol", "date"]).reset_index(drop=True)


def hygiene_report(
    daily: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    eligibility: pd.DataFrame,
    *,
    exclude: set[str] = frozenset(),
    window: int = 63,
    min_days: int = 21,
    min_coverage: float = 0.90,
    min_dollar_volume: float = 5_000_000.0,
) -> str:
    """Markdown hygiene report: totals, coverage, pathologies, liquidity.

    The window/min_days/min_coverage/min_dollar_volume parameters are for
    display only (the "Parameters used" section) -- pass the same values
    used to produce `eligibility` via compute_eligibility().

    Args:
        daily: build_all() output.
        calendar: trading_calendar() output.
        eligibility: compute_eligibility() output.
        exclude: Symbols excluded from eligibility (stated in the report).
        window: Trailing window used for eligibility (display only).
        min_days: Warmup floor used for eligibility (display only).
        min_coverage: Coverage floor used for eligibility (display only).
        min_dollar_volume: Liquidity floor used for eligibility (display
            only).

    Returns:
        Markdown report string.
    """
    lines: list[str] = ["# Universe hygiene report", ""]

    n_symbols = daily["symbol"].nunique() if not daily.empty else 0
    n_days = len(calendar)
    date_min = calendar.min().date() if n_days else None
    date_max = calendar.max().date() if n_days else None

    lines += [
        "## Totals",
        f"- Symbols: {n_symbols}",
        f"- Trading days: {n_days}",
        f"- Date range: {date_min} to {date_max}",
        f"- Daily rows: {len(daily)}",
        "",
    ]

    # --- Coverage over the full calendar ---
    lines.append("## Coverage (full-period, per symbol)")
    if n_days == 0 or daily.empty:
        lines.append("- No data.")
    else:
        on_calendar = daily[daily["date"].isin(calendar)]
        full_coverage = on_calendar.groupby("symbol")["date"].nunique() / n_days
        deciles = full_coverage.quantile(np.arange(0.0, 1.01, 0.1))
        lines.append("- Deciles (0%..100%):")
        for q, v in deciles.items():
            lines.append(f"  - p{int(round(q * 100))}: {v:.4f}")

        low_cov = full_coverage[full_coverage < 0.90].sort_values()
        lines.append(f"- Symbols with <90% full-period coverage: {len(low_cov)}")
        for sym, cov in low_cov.head(20).items():
            lines.append(f"  - {sym}: {cov:.4f}")
    lines.append("")

    # --- Pathologies ---
    lines.append("## Pathologies")
    if daily.empty:
        lines.append("- No data.")
    else:
        # Late opens: first RTH bar after 09:35.
        late = daily[daily["first_bar_min"] > 575].sort_values(
            "first_bar_min", ascending=False
        )
        lines.append(f"- Late opens (first_bar_min > 575): {len(late)}")
        for row in late.head(10).itertuples(index=False):
            lines.append(f"  - {row.symbol} {row.date.date()}: {row.first_bar_min}")

        # Half-days vs. per-symbol truncation: modal last_bar_min per date.
        modal_last = daily.groupby("date")["last_bar_min"].agg(
            lambda s: s.mode().iloc[0]
        )
        half_days = modal_last[modal_last < 959].sort_index()
        normal_days = modal_last[modal_last == 959].index

        normal = daily[daily["date"].isin(normal_days)]
        early_end = normal[normal["last_bar_min"] < 955].sort_values("last_bar_min")
        lines.append(
            f"- Early data end on full days (last_bar_min < 955, "
            f"excludes detected half-days): {len(early_end)}"
        )
        for row in early_end.head(10).itertuples(index=False):
            lines.append(f"  - {row.symbol} {row.date.date()}: {row.last_bar_min}")

        lines.append(f"- Detected half-days (calendar-modal last_bar_min < 959): {len(half_days)}")
        for date, modal in half_days.items():
            lines.append(f"  - {date.date()}: modal last_bar_min={modal}")

        # Extreme moves.
        with_cc = daily.dropna(subset=["cc_ret"])
        extreme = with_cc[with_cc["cc_ret"].abs() > 0.5]
        extreme = extreme.reindex(extreme["cc_ret"].abs().sort_values(ascending=False).index)
        lines.append(f"- Extreme moves (|cc_ret| > 0.5): {len(extreme)}")
        for row in extreme.head(10).itertuples(index=False):
            lines.append(f"  - {row.symbol} {row.date.date()}: {row.cc_ret:.4f}")

        # Zero-volume RTH days.
        zero_vol = daily[daily["rth_volume"] == 0].sort_values(["symbol", "date"])
        lines.append(f"- Zero-volume RTH days: {len(zero_vol)}")
        for row in zero_vol.head(10).itertuples(index=False):
            lines.append(f"  - {row.symbol} {row.date.date()}")

        # bar1600 missing, full days only -- fraction of symbol-days.
        if len(normal) > 0:
            missing_frac = normal["bar1600_close"].isna().mean()
        else:
            missing_frac = float("nan")
        lines.append(
            f"- bar1600 missing on full days: {missing_frac:.4f} "
            f"({normal['bar1600_close'].isna().sum() if len(normal) else 0} of "
            f"{len(normal)} symbol-days)"
        )
    lines.append("")

    # --- Liquidity ---
    lines.append("## Liquidity")
    if daily.empty:
        lines.append("- No data.")
    else:
        med_dv_by_symbol = daily.groupby("symbol")["rth_dollar_volume"].median()
        pct = med_dv_by_symbol.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
        lines.append("- Per-symbol median RTH dollar volume percentiles:")
        for q, v in pct.items():
            lines.append(f"  - p{int(round(q * 100))}: ${v:,.0f}")

        if eligibility.empty:
            lines.append("- Eligible-universe size: no eligibility data.")
        else:
            per_day = eligibility.groupby("date")["eligible"].sum()
            per_day = per_day.reindex(calendar).fillna(0)
            lines.append(
                f"- Eligible-universe size per day: min={int(per_day.min())} "
                f"median={per_day.median():.0f} max={int(per_day.max())}"
            )
            if len(per_day) > 0:
                lines.append(
                    f"  - First date ({per_day.index.min().date()}): "
                    f"{int(per_day.iloc[0])}"
                )
                lines.append(
                    f"  - Last date ({per_day.index.max().date()}): "
                    f"{int(per_day.iloc[-1])}"
                )
    lines.append("")

    # --- Parameters ---
    lines += [
        "## Parameters used",
        f"- window: {window}",
        f"- min_days: {min_days}",
        f"- min_coverage: {min_coverage}",
        f"- min_dollar_volume: {min_dollar_volume}",
        f"- excluded symbols: {sorted(exclude) if exclude else '(none)'}",
    ]

    return "\n".join(lines)


def _compound(returns: pd.Series) -> float:
    """Total compounded return from a series of periodic returns."""
    if returns.empty:
        return float("nan")
    return float((1.0 + returns).prod() - 1.0)


def _annualize(total_return: float, n_periods: int) -> float:
    """Annualize a total return over n_periods trading days."""
    if n_periods <= 0 or pd.isna(total_return):
        return float("nan")
    return float((1.0 + total_return) ** (_TRADING_DAYS_PER_YEAR / n_periods) - 1.0)


def survivorship_summary(
    daily: pd.DataFrame,
    eligibility: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    benchmark_symbol: str = "SPY",
) -> str:
    """Quantify the survivorship/size drift of the eligible universe.

    Equal-weight (EW) eligible-universe daily return on date D = mean of
    cc_ret on D over symbols eligible as of the PREVIOUS calendar date
    (portfolio formed at D-1's close, held to D's close -- no look-ahead).
    Dates with no eligible-and-returning symbol contribute a zero return to
    the compound (they don't move the portfolio). Benchmark leg = cc_ret of
    `benchmark_symbol` compounded over the same dates; benchmark_symbol is
    expected to be present in `daily` but excluded from eligibility. If it
    has no rows in `daily`, falls back to a dollar-volume-weighted universe
    return (weights = prior-day med_dollar_volume of eligible symbols,
    renormalized daily) and states that in the output.

    Args:
        daily: build_all() output.
        eligibility: compute_eligibility() output (must have been run with
            benchmark_symbol excluded for the benchmark leg to be a clean
            comparison).
        calendar: trading_calendar() output.
        benchmark_symbol: Cap-weighted benchmark proxy symbol.

    Returns:
        Markdown report string.
    """
    calendar = pd.DatetimeIndex(sorted(calendar))
    lines: list[str] = ["## Survivorship quantification", ""]

    if len(calendar) < 2 or daily.empty or eligibility.empty:
        lines.append("- Insufficient data for a survivorship estimate.")
        return "\n".join(lines)

    cc_ret = daily.pivot_table(index="date", columns="symbol", values="cc_ret")
    cc_ret = cc_ret.reindex(calendar)

    elig = eligibility.pivot_table(index="date", columns="symbol", values="eligible")
    elig = elig.reindex(calendar).fillna(False).astype(bool)
    elig_prev = elig.shift(1).fillna(False)

    dv = eligibility.pivot_table(index="date", columns="symbol", values="med_dollar_volume")
    dv = dv.reindex(calendar)
    dv_prev = dv.shift(1)

    common_cols = cc_ret.columns.intersection(elig_prev.columns)
    cc_common = cc_ret[common_cols]
    elig_common = elig_prev[common_cols]

    masked_ret = cc_common.where(elig_common)
    ew_ret = masked_ret.mean(axis=1, skipna=True).fillna(0.0)
    ew_ret = ew_ret.iloc[1:]  # first date has no prior-day eligibility

    use_dates = ew_ret.index

    fallback = False
    if benchmark_symbol in cc_ret.columns:
        bench_ret = cc_ret[benchmark_symbol].reindex(use_dates).fillna(0.0)
        bench_label = f"Benchmark ({benchmark_symbol})"
    else:
        fallback = True
        logger.warning(
            "Benchmark symbol has no data, falling back to dollar-volume weighting",
            benchmark=benchmark_symbol,
        )
        dv_common = dv_prev[common_cols].where(elig_common)
        weights = dv_common.div(dv_common.sum(axis=1), axis=0)
        bench_ret = (cc_common * weights).sum(axis=1, skipna=True)
        bench_ret = bench_ret.reindex(use_dates).fillna(0.0)
        bench_label = "Benchmark (dollar-volume-weighted universe fallback)"

    def _window_stats(ret: pd.Series, start: str | None, end: str | None) -> tuple[float, float, int]:
        sub = ret
        if start is not None:
            sub = sub[sub.index >= pd.Timestamp(start)]
        if end is not None:
            sub = sub[sub.index < pd.Timestamp(end)]
        total = _compound(sub)
        ann = _annualize(total, len(sub))
        return total, ann, len(sub)

    ew_total, ew_ann, ew_n = _window_stats(ew_ret, None, None)
    bench_total, bench_ann, bench_n = _window_stats(bench_ret, None, None)
    spread_total = ew_total - bench_total
    spread_ann = ew_ann - bench_ann

    if fallback:
        lines.append(
            f"- {benchmark_symbol} has no rows in `daily`; using the "
            "dollar-volume-weighted eligible-universe fallback as the "
            "benchmark leg instead."
        )
        lines.append("")

    lines += [
        f"### Full period ({ew_n} trading days)",
        f"- EW eligible-universe total return: {ew_total * 100:.4f}% "
        f"(annualized: {ew_ann * 100:.4f}%)",
        f"- {bench_label} total return: {bench_total * 100:.4f}% "
        f"(annualized: {bench_ann * 100:.4f}%)",
        f"- Spread (EW - benchmark) total: {spread_total * 100:.4f}% "
        f"(annualized: {spread_ann * 100:.4f}%)",
        "",
        "### Per-window splits",
    ]

    for start, end in _WINDOW_SPLITS:
        ew_t, ew_a, n = _window_stats(ew_ret, start, end)
        bn_t, bn_a, _ = _window_stats(bench_ret, start, end)
        lines += [
            f"- {start} to {end} ({n} trading days):",
            f"  - EW: total {ew_t * 100:.4f}% (annualized {ew_a * 100:.4f}%)",
            f"  - Benchmark: total {bn_t * 100:.4f}% (annualized {bn_a * 100:.4f}%)",
            f"  - Spread: total {(ew_t - bn_t) * 100:.4f}% "
            f"(annualized {(ew_a - bn_a) * 100:.4f}%)",
        ]

    lines += [
        "",
        "This spread is the survivorship + size drift baked into the "
        "current-membership universe, and should be cited alongside every "
        "phase-6 result.",
        "Note: returns exclude dividends (split-adjusted-only source data), "
        "which UNDERSTATES both legs and biases the EW-benchmark spread "
        "further positive by roughly the dividend-yield gap.",
    ]

    return "\n".join(lines)
