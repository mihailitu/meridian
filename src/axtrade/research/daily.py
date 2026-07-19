"""Daily bar construction from 1-minute historical parquet data.

Reads `data/historical/{SYMBOL}_1m_*.parquet` files (naive-UTC timestamps,
bar START times) and rolls each symbol's 1-minute bars up into one row per
ET trading date, with explicit regular-trading-hours (RTH) session
definitions. See docs/phase6-cross-sectional.md (Phase A).
"""

from pathlib import Path

import pandas as pd

from axtrade.common import get_logger

logger = get_logger("research.daily")

# RTH window: 09:30:00 <= bar start < 16:00:00 ET, expressed in minutes
# since ET midnight (570 = 09:30, 960 = 16:00).
RTH_START_MIN = 9 * 60 + 30
RTH_END_MIN = 16 * 60

_OUTPUT_COLUMNS = [
    "symbol",
    "date",
    "rth_open",
    "rth_close",
    "rth_high",
    "rth_low",
    "rth_volume",
    "rth_dollar_volume",
    "rth_bar_count",
    "first_bar_min",
    "last_bar_min",
    "bar1600_close",
    "ext_volume",
    "prev_rth_close",
    "intraday_ret",
    "gap_ret",
    "cc_ret",
]


def _empty_daily() -> pd.DataFrame:
    """Empty frame with the build_symbol_daily() output schema."""
    return pd.DataFrame(columns=_OUTPUT_COLUMNS)


def build_symbol_daily(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Roll 1-minute bars up into one row per ET trading date.

    Timestamps are bar START times in naive UTC. RTH is defined in ET
    wall-clock time as 09:30:00 <= bar start < 16:00:00; the 16:00:00 bar
    itself (closing-auction proxy) is deliberately OUTSIDE that window and
    only surfaces via `bar1600_close` / `ext_volume`. A date only gets an
    output row if it has at least one RTH bar.

    Args:
        df: 1-minute OHLCV bars for a single symbol. Must have `timestamp`
            (naive UTC datetime64) plus `open, high, low, close, volume`.
            Extra columns (e.g. indicators) are ignored.
        symbol: Symbol name, stamped onto every output row.

    Returns:
        One row per ET date with >=1 RTH bar, sorted by date, columns:
        symbol, date, rth_open/close/high/low/volume/dollar_volume/
        bar_count, first_bar_min, last_bar_min, bar1600_close, ext_volume,
        prev_rth_close, intraday_ret, gap_ret, cc_ret.
    """
    if df.empty:
        return _empty_daily()

    work = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    ts_et = work["timestamp"].dt.tz_localize("UTC").dt.tz_convert("America/New_York")
    work["et_date"] = ts_et.dt.normalize().dt.tz_localize(None)
    work["minute_of_day"] = (ts_et.dt.hour * 60 + ts_et.dt.minute).astype("int64")

    is_rth = (work["minute_of_day"] >= RTH_START_MIN) & (
        work["minute_of_day"] < RTH_END_MIN
    )
    is_1600 = work["minute_of_day"] == RTH_END_MIN

    rth = work.loc[is_rth].sort_values("timestamp").copy()
    if rth.empty:
        return _empty_daily()

    rth["dollar_volume"] = rth["close"] * rth["volume"]
    daily = rth.groupby("et_date", sort=True).agg(
        rth_open=("open", "first"),
        rth_close=("close", "last"),
        rth_high=("high", "max"),
        rth_low=("low", "min"),
        rth_volume=("volume", "sum"),
        rth_dollar_volume=("dollar_volume", "sum"),
        rth_bar_count=("open", "count"),
        first_bar_min=("minute_of_day", "first"),
        last_bar_min=("minute_of_day", "last"),
    )

    bar1600 = (
        work.loc[is_1600].groupby("et_date")["close"].last().reindex(daily.index)
    )
    daily["bar1600_close"] = bar1600

    ext_volume = (
        work.loc[~is_rth]
        .groupby("et_date")["volume"]
        .sum()
        .reindex(daily.index)
        .fillna(0)
        .astype("int64")
    )
    daily["ext_volume"] = ext_volume

    daily = daily.reset_index().rename(columns={"et_date": "date"})
    daily.insert(0, "symbol", symbol)
    daily["date"] = daily["date"].astype("datetime64[ns]")
    daily = daily.sort_values("date").reset_index(drop=True)

    # Derived returns, over rows present -- a missing day means the gap
    # spans it (shift is over present rows, not calendar days); that is
    # intended, hygiene_report() surfaces missing days separately.
    daily["prev_rth_close"] = daily["rth_close"].shift(1)
    daily["intraday_ret"] = daily["rth_close"] / daily["rth_open"] - 1
    daily["gap_ret"] = daily["rth_open"] / daily["prev_rth_close"] - 1
    daily["cc_ret"] = daily["rth_close"] / daily["prev_rth_close"] - 1

    return daily[_OUTPUT_COLUMNS]


def _discover_files(data_dir: Path) -> dict[str, list[Path]]:
    """Group `{SYMBOL}_1m_*.parquet` files in data_dir by symbol."""
    files: dict[str, list[Path]] = {}
    for path in sorted(data_dir.glob("*_1m_*.parquet")):
        symbol = path.name.split("_1m_", 1)[0]
        files.setdefault(symbol, []).append(path)
    return files


def build_all(data_dir: Path, symbols: list[str] | None = None) -> pd.DataFrame:
    """Build combined daily bars for every symbol found under data_dir.

    Discovers `{SYMBOL}_1m_*.parquet` files (symbol = part before `_1m_`).
    If a symbol has multiple matching files (pre-recertification archives),
    they are concatenated and de-duplicated by timestamp (keep first) before
    building. Reads only the columns build_symbol_daily() needs.

    Args:
        data_dir: Directory containing the 1m parquet files.
        symbols: Optional explicit symbol list to limit discovery to (for
            tests / smoke runs). Default: every symbol found.

    Returns:
        Concatenated build_symbol_daily() output, sorted by (symbol, date).
    """
    data_dir = Path(data_dir)
    files_by_symbol = _discover_files(data_dir)
    if symbols is not None:
        wanted = set(symbols)
        files_by_symbol = {
            sym: paths for sym, paths in files_by_symbol.items() if sym in wanted
        }

    columns = ["timestamp", "open", "high", "low", "close", "volume"]
    frames: list[pd.DataFrame] = []
    total = len(files_by_symbol)

    for i, (symbol, paths) in enumerate(sorted(files_by_symbol.items()), start=1):
        parts = [pd.read_parquet(p, columns=columns) for p in paths]
        sym_df = parts[0] if len(parts) == 1 else pd.concat(parts, ignore_index=True)
        if len(parts) > 1:
            sym_df = (
                sym_df.drop_duplicates(subset="timestamp", keep="first")
                .sort_values("timestamp")
                .reset_index(drop=True)
            )

        symbol_daily = build_symbol_daily(sym_df, symbol)
        if not symbol_daily.empty:
            frames.append(symbol_daily)

        if i % 100 == 0:
            logger.info("build_all progress", symbols_done=i, symbols_total=total)

    if not frames:
        return _empty_daily()

    result = pd.concat(frames, ignore_index=True)
    return result.sort_values(["symbol", "date"]).reset_index(drop=True)


def trading_calendar(daily: pd.DataFrame, min_frac: float = 0.5) -> pd.DatetimeIndex:
    """Data-driven trading calendar (no external calendar dependency).

    A date is included when the number of distinct symbols with a row on
    that date is >= min_frac * (total distinct symbols in `daily`).

    Args:
        daily: build_all() output.
        min_frac: Minimum fraction of the full symbol set required to be
            present on a date for it to count as a trading day.

    Returns:
        Sorted DatetimeIndex of qualifying dates.
    """
    if daily.empty:
        return pd.DatetimeIndex([])

    total_symbols = daily["symbol"].nunique()
    counts = daily.groupby("date")["symbol"].nunique()
    threshold = min_frac * total_symbols
    qualifying = counts[counts >= threshold].index
    return pd.DatetimeIndex(sorted(qualifying))
