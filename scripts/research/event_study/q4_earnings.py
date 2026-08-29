"""E4 Phase 2 analysis: Q4 (earnings share of idiosyncratic risk).

Tier-2 scratch script. Definitions are FROZEN in docs/event-study-plan.md §4a:
  - reaction-day mapping: BMO -> that trading day; AMC -> next trading day;
    unknown/unverified session -> date-only (the date AND the next trading
    day both count) -- the §3 fallback. In date-only mode (chosen when the
    §3 spot-check gate rejects session tags) EVERY row uses the date-only
    rule regardless of its tagged session.
  - universe: phase-6 eligible names (eligibility.parquet, `eligible` True
    on at least one date) with >= 250 rows in the daily panel.
  - (i) per name: share of its top-5 |cc_ret| days that are reaction days;
    cross-name distribution.
  - (ii) panel: median/p90 of |cc_ret| on reaction days vs all other days,
    pooled across the universe.
  - (iii) share of >2sigma idiosyncratic moves (rolling 63d OLS beta vs SPY
    cc_ret, residual sigma, shifted -- the sigma used for day t comes from
    data through t-1) landing on reaction days, vs the base rate.

Data: data/daily/daily_bars.parquet (symbol, date, cc_ret, ... -- see
src/axtrade/research/daily.py), data/daily/eligibility.parquet (symbol,
date, eligible), data/daily/calendar.txt (one trading date per line, the
data-driven calendar from research.daily.trading_calendar()), and
data/research/event_study/earnings_calendar.parquet (symbol, date, session,
source -- built by fetch_earnings.py).

Outputs: data/research/event_study/{q4_pername.csv,q4_summary.csv} + stdout.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = Path("data/research/event_study")
DEFAULT_DAILY_DIR = Path("data/daily")
DEFAULT_CALENDAR = OUT_DIR / "earnings_calendar.parquet"

MIN_ROWS = 250
BETA_WINDOW = 63
LARGE_Z = 2.0
TOP_N = 5


# --- loading -----------------------------------------------------------

def load_daily(daily_dir: Path) -> pd.DataFrame:
    df = pd.read_parquet(daily_dir / "daily_bars.parquet")
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_calendar_index(daily_dir: Path) -> pd.DatetimeIndex:
    """Data-driven trading-day index, one date per line (research.daily)."""
    with open(daily_dir / "calendar.txt") as f:
        dates = [line.strip() for line in f if line.strip()]
    return pd.DatetimeIndex(sorted(pd.to_datetime(dates)))


def load_earnings_calendar(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    missing = {"symbol", "date", "session"} - set(df.columns)
    if missing:
        raise ValueError(f"earnings calendar missing columns: {sorted(missing)}")
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    return df


def eligible_universe(daily_dir: Path, daily: pd.DataFrame) -> set[str]:
    """Phase-6 eligible names (eligible on >=1 date) with >=250 daily rows."""
    elig = pd.read_parquet(daily_dir / "eligibility.parquet")
    ever_eligible = set(elig.loc[elig["eligible"], "symbol"].unique())
    row_counts = daily.groupby("symbol").size()
    enough_rows = set(row_counts[row_counts >= MIN_ROWS].index)
    return ever_eligible & enough_rows


# --- reaction-day mapping ------------------------------------------------

def snap_on_or_after(dates: pd.DatetimeIndex, calendar: pd.DatetimeIndex) -> np.ndarray:
    """First calendar day >= each date (the date itself if it's a trading day)."""
    idx = calendar.searchsorted(dates, side="left")
    idx = np.clip(idx, 0, len(calendar) - 1)
    return calendar.to_numpy()[idx]


def next_after(dates: pd.DatetimeIndex, calendar: pd.DatetimeIndex) -> np.ndarray:
    """First calendar day strictly after each date; NaT past the calendar end."""
    idx = calendar.searchsorted(dates, side="right")
    out = np.full(len(dates), np.datetime64("NaT"), dtype="datetime64[ns]")
    valid = idx < len(calendar)
    out[valid] = calendar.to_numpy()[idx[valid]]
    return out


def build_reaction_days(
    earnings: pd.DataFrame, calendar: pd.DatetimeIndex, mapping: str
) -> pd.DataFrame:
    """One row per (symbol, reaction_date), deduplicated.

    mapping="date-only": every row marks the date AND the next trading day.
    mapping="session": bmo -> that trading day; amc -> next trading day;
    unknown -> both (the date-only fallback), per the frozen §4a spec.
    """
    dates = pd.DatetimeIndex(earnings["date"])
    on_or_after = snap_on_or_after(dates, calendar)
    after = next_after(dates, calendar)

    if mapping == "date-only":
        d1, d2 = on_or_after, after
        symbols = np.concatenate([earnings["symbol"].to_numpy(), earnings["symbol"].to_numpy()])
        rdates = np.concatenate([d1, d2])
    elif mapping == "session":
        session = earnings["session"].to_numpy()
        is_bmo = session == "bmo"
        is_amc = session == "amc"
        is_unknown = ~(is_bmo | is_amc)

        symbols_parts = [earnings["symbol"].to_numpy()[is_bmo], earnings["symbol"].to_numpy()[is_amc]]
        rdates_parts = [on_or_after[is_bmo], after[is_amc]]
        # unknown/unverified session -> date-only fallback (both days count)
        symbols_parts.append(earnings["symbol"].to_numpy()[is_unknown])
        rdates_parts.append(on_or_after[is_unknown])
        symbols_parts.append(earnings["symbol"].to_numpy()[is_unknown])
        rdates_parts.append(after[is_unknown])

        symbols = np.concatenate(symbols_parts)
        rdates = np.concatenate(rdates_parts)
    else:
        raise ValueError(f"unknown mapping {mapping!r}")

    out = pd.DataFrame({"symbol": symbols, "date": rdates})
    out = out.dropna(subset=["date"]).drop_duplicates()
    out["is_reaction"] = True
    return out


# --- statistic (i): per-name top-5 share --------------------------------

def top5_reaction_share(panel: pd.DataFrame, universe: set[str]) -> pd.DataFrame:
    sub = panel[panel["symbol"].isin(universe)].dropna(subset=["cc_ret"])
    rows = []
    for symbol, g in sub.groupby("symbol", sort=True):
        top5 = g.reindex(g["cc_ret"].abs().sort_values(ascending=False).index).head(TOP_N)
        n_reaction = int(top5["is_reaction"].sum())
        rows.append(
            {
                "symbol": symbol,
                "n_days": len(g),
                "n_top5": len(top5),
                "n_reaction_in_top5": n_reaction,
                "share_reaction_top5": n_reaction / len(top5) if len(top5) else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("symbol").reset_index(drop=True)


# --- statistic (ii): panel |cc_ret| reaction vs other -------------------

def panel_abs_ret_stats(panel: pd.DataFrame, universe: set[str]) -> pd.DataFrame:
    sub = panel[panel["symbol"].isin(universe)].dropna(subset=["cc_ret"])
    abs_ret = sub["cc_ret"].abs()
    rows = []
    for label, mask in [("reaction", sub["is_reaction"]), ("other", ~sub["is_reaction"])]:
        vals = abs_ret[mask]
        rows.append(
            {
                "group": label,
                "n": int(mask.sum()),
                "median_abs_cc_ret": float(vals.median()) if len(vals) else np.nan,
                "p90_abs_cc_ret": float(vals.quantile(0.90)) if len(vals) else np.nan,
            }
        )
    return pd.DataFrame(rows)


# --- statistic (iii): >2sigma idiosyncratic moves -----------------------

def idiosyncratic_moves(daily: pd.DataFrame, universe: set[str]) -> pd.DataFrame:
    """Per (symbol, date) flag for |residual| > 2 x trailing-63d sigma (shifted).

    Vectorized: pivot cc_ret to a (date x symbol) wide frame, compute rolling
    beta vs SPY via rolling covariance/variance, build the residual series,
    then its rolling std -- each ending at day t (inclusive) -- and shift by
    one day so the sigma used to classify day t comes from data through
    t-1 only (no lookahead), matching the house convention in
    q1_q3_macro.py's index-level "trailing 63-day sigma (shifted)".
    """
    wide = daily.pivot(index="date", columns="symbol", values="cc_ret").sort_index()
    if "SPY" not in wide.columns:
        raise ValueError("SPY not found in daily panel; cannot compute idiosyncratic beta")
    mkt = wide["SPY"]

    cov = wide.rolling(BETA_WINDOW).cov(mkt)
    var_mkt = mkt.rolling(BETA_WINDOW).var()
    beta = cov.div(var_mkt, axis=0)

    resid = wide.sub(beta.mul(mkt, axis=0))
    sigma_raw = resid.rolling(BETA_WINDOW).std()
    sigma_used = sigma_raw.shift(1)

    large = (resid.abs() > LARGE_Z * sigma_used) & sigma_used.notna()

    cols = [c for c in wide.columns if c in universe]
    large_long = large[cols].stack().rename("is_large_move").reset_index()
    large_long.columns = ["date", "symbol", "is_large_move"]
    valid_long = sigma_used[cols].notna().stack().rename("valid").reset_index()
    valid_long.columns = ["date", "symbol", "valid"]
    out = large_long.merge(valid_long, on=["date", "symbol"])
    return out[out["valid"]].drop(columns="valid")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--mapping",
        choices=["session", "date-only"],
        required=True,
        help="Reaction-day mapping mode; the §3 spot-check gate decides which is allowed.",
    )
    parser.add_argument("--daily-dir", type=Path, default=DEFAULT_DAILY_DIR)
    parser.add_argument("--calendar", type=Path, default=DEFAULT_CALENDAR)
    args = parser.parse_args()

    daily = load_daily(args.daily_dir)
    trading_days = load_calendar_index(args.daily_dir)
    earnings = load_earnings_calendar(args.calendar)
    universe = eligible_universe(args.daily_dir, daily)
    print(
        f"daily panel: {daily['symbol'].nunique()} symbols, "
        f"{daily['date'].min().date()} -> {daily['date'].max().date()}"
    )
    print(f"earnings calendar: {len(earnings)} rows, {earnings['symbol'].nunique()} symbols")
    print(f"universe (eligible & >={MIN_ROWS} rows): {len(universe)} names")
    print(f"mapping mode: {args.mapping}")

    reactions = build_reaction_days(earnings, trading_days, args.mapping)
    panel = daily.merge(reactions, on=["symbol", "date"], how="left")
    panel["is_reaction"] = panel["is_reaction"].fillna(False).astype(bool)
    n_reaction_rows = int(panel["is_reaction"].sum())
    print(f"reaction-day rows tagged in panel: {n_reaction_rows}")

    # (i) per-name top-5 share
    pername = top5_reaction_share(panel, universe)
    dist = pername["share_reaction_top5"].describe(percentiles=[0.25, 0.5, 0.75, 0.9])
    print("\nQ4(i) per-name top-5 |cc_ret| reaction-day share, cross-name distribution:")
    print(
        f"  mean={pername['share_reaction_top5'].mean():.3f} "
        f"median={dist['50%']:.3f} p25={dist['25%']:.3f} "
        f"p75={dist['75%']:.3f} p90={dist['90%']:.3f}  (n_names={len(pername)})"
    )

    # (ii) panel median/p90 |cc_ret| reaction vs other
    panel_stats = panel_abs_ret_stats(panel, universe)
    print("\nQ4(ii) panel |cc_ret|, reaction vs other days:")
    print(panel_stats.to_string(index=False))

    # (iii) >2sigma idiosyncratic moves share landing on reaction days
    idio = idiosyncratic_moves(daily, universe)
    idio = idio.merge(reactions.rename(columns={"is_reaction": "is_reaction_flag"}), on=["symbol", "date"], how="left")
    idio["is_reaction_flag"] = idio["is_reaction_flag"].fillna(False).astype(bool)
    n_obs = len(idio)
    n_large = int(idio["is_large_move"].sum())
    base_rate = float(idio["is_reaction_flag"].mean()) if n_obs else np.nan
    share_large_reaction = (
        float(idio.loc[idio["is_large_move"], "is_reaction_flag"].mean()) if n_large else np.nan
    )
    print("\nQ4(iii) >2sigma idiosyncratic moves vs earnings-reaction days:")
    print(
        f"  n_obs={n_obs}, n_large_moves={n_large}, "
        f"share_of_large_moves_on_reaction_days={share_large_reaction:.4f}, "
        f"base_rate_reaction_days={base_rate:.4f}"
    )

    # --- write outputs ---
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pername.to_csv(OUT_DIR / "q4_pername.csv", index=False)

    summary_rows = [
        {"mapping": args.mapping, "statistic": "top5_reaction_share", "group": "all",
         "metric": "mean", "value": pername["share_reaction_top5"].mean(), "n": len(pername)},
        {"mapping": args.mapping, "statistic": "top5_reaction_share", "group": "all",
         "metric": "median", "value": dist["50%"], "n": len(pername)},
        {"mapping": args.mapping, "statistic": "top5_reaction_share", "group": "all",
         "metric": "p25", "value": dist["25%"], "n": len(pername)},
        {"mapping": args.mapping, "statistic": "top5_reaction_share", "group": "all",
         "metric": "p75", "value": dist["75%"], "n": len(pername)},
        {"mapping": args.mapping, "statistic": "top5_reaction_share", "group": "all",
         "metric": "p90", "value": dist["90%"], "n": len(pername)},
    ]
    for _, r in panel_stats.iterrows():
        summary_rows.append({"mapping": args.mapping, "statistic": "panel_abs_cc_ret", "group": r["group"],
                              "metric": "median", "value": r["median_abs_cc_ret"], "n": r["n"]})
        summary_rows.append({"mapping": args.mapping, "statistic": "panel_abs_cc_ret", "group": r["group"],
                              "metric": "p90", "value": r["p90_abs_cc_ret"], "n": r["n"]})
    summary_rows.append({"mapping": args.mapping, "statistic": "idio_2sigma_moves", "group": "large_moves",
                          "metric": "share_reaction", "value": share_large_reaction, "n": n_large})
    summary_rows.append({"mapping": args.mapping, "statistic": "idio_2sigma_moves", "group": "all_obs",
                          "metric": "base_rate_reaction", "value": base_rate, "n": n_obs})

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(OUT_DIR / "q4_summary.csv", index=False)

    print(f"\nWrote {OUT_DIR / 'q4_pername.csv'} ({len(pername)} rows)")
    print(f"Wrote {OUT_DIR / 'q4_summary.csv'} ({len(summary)} rows)")


if __name__ == "__main__":
    main()
