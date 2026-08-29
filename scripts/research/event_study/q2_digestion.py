"""E4 Phase 2 analysis: Q2 (minute-level digestion curves).

Tier-2 scratch script. Definitions are FROZEN in docs/event-study-plan.md §4
and the Phase 2 amendments in §4a:
  - instrument: SPY 1m from the archive (index proxy)
  - window: [-30, +120] minutes around the official event minute
    (FOMC 14:00 ET, presser 14:30 marked on plots; CPI/NFP 08:30 ET)
  - per-day curve: complete 1-minute ET grid, prices forward-filled onto the
    grid (seeded from up to 60 minutes before the window so offset -30 has a
    defined 1-minute return); per-offset vol = cross-event mean |1m log
    return|; drift = cross-event mean cumulative log return from offset -1
  - baseline: same weekday as an event day of that type, no fomc/cpi/nfp
    event at all (scheduled_only=False), same event-minute anchor
  - minutes-to-baseline: trailing 5-minute mean on both vol curves; first
    offset m >= 0 where smoothed_event <= 1.25 x smoothed_baseline for 10
    consecutive minutes; None if never reached

Data: data/historical/SPY_1m_2024-08-01_2026-02-01.parquet. Timestamps are
naive-UTC bar START times; converted to ET exactly as research/daily.py
does (tz_localize("UTC").tz_convert("America/New_York")).

Outputs: data/research/event_study/{q2_curves.csv,q2_summary.csv,
q2_{event}.png} + stdout.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, "src")
from axtrade.research.events import EVENT_TIMES_ET, event_dates, load_event_calendar  # noqa: E402

OUT_DIR = Path("data/research/event_study")
SPY_PATH = Path("data/historical/SPY_1m_2024-08-01_2026-02-01.parquet")

OFFSET_LO = -30
OFFSET_HI = 120
LOOKBACK_MIN = 60  # minutes before the window start (-30) to seed the ffill
SMOOTH_WIN = 5
RATIO_THRESHOLD = 1.25
CONSECUTIVE_MIN = 10
RTH_START_MIN = 9 * 60 + 30
RTH_END_MIN = 16 * 60

EVENTS = ("fomc", "cpi", "nfp")


def _anchor_minute(event: str) -> int:
    h, m = EVENT_TIMES_ET[event].split(":")
    return int(h) * 60 + int(m)


def load_spy() -> pd.Series:
    """SPY 1-minute closes indexed by naive ET timestamp (bar start)."""
    df = pd.read_parquet(SPY_PATH)
    ts_et = df["timestamp"].dt.tz_localize("UTC").dt.tz_convert("America/New_York").dt.tz_localize(None)
    close = pd.Series(df["close"].to_numpy(), index=ts_et).sort_index()
    close = close[~close.index.duplicated(keep="last")]
    return close


def day_curve(close: pd.Series, date: pd.Timestamp, anchor_minute: int) -> pd.DataFrame:
    """Per-day return/cumret curve over offsets [-30, 120], plus raw non-NaN mask.

    Grid spans [anchor - 90, anchor + 120] minutes so that offset -30 has a
    defined 1-minute return (its predecessor at offset -31 is inside the
    60-minute seed lookback) and so the ffill seed can reach back further
    still if the immediate predecessor is itself missing.
    """
    grid_start = anchor_minute - (OFFSET_LO * -1) - LOOKBACK_MIN  # anchor - 30 - 60 = anchor - 90
    grid_end = anchor_minute + OFFSET_HI
    offsets_full = np.arange(grid_start - anchor_minute, grid_end - anchor_minute + 1)
    times = pd.DatetimeIndex([date + pd.Timedelta(minutes=int(m)) for m in offsets_full + anchor_minute])

    raw = close.reindex(times)
    filled = raw.ffill()
    logp = np.log(filled)
    ret_full = logp.diff()

    window_mask = (offsets_full >= OFFSET_LO) & (offsets_full <= OFFSET_HI)
    offsets_win = offsets_full[window_mask]

    minus1_idx = np.where(offsets_full == -1)[0]
    logp_minus1 = logp.iloc[minus1_idx[0]] if len(minus1_idx) else np.nan

    out = pd.DataFrame(
        {
            "ret": ret_full.to_numpy()[window_mask],
            "cumret": logp.to_numpy()[window_mask] - logp_minus1,
            "raw_notnull": raw.notna().to_numpy()[window_mask],
        },
        index=offsets_win,
    )
    out.index.name = "offset_min"
    return out


def stack_curves(close: pd.Series, dates: list[pd.Timestamp], anchor_minute: int) -> pd.DataFrame:
    """One row per day, columns = offset; returns (ret_df, cumret_df, raw_df)."""
    curves = {d: day_curve(close, d, anchor_minute) for d in dates}
    ret_df = pd.DataFrame({d: c["ret"] for d, c in curves.items()}).T
    cumret_df = pd.DataFrame({d: c["cumret"] for d, c in curves.items()}).T
    raw_df = pd.DataFrame({d: c["raw_notnull"] for d, c in curves.items()}).T
    return ret_df, cumret_df, raw_df


def smooth(curve: pd.Series) -> pd.Series:
    return curve.rolling(SMOOTH_WIN, min_periods=1).mean()


def minutes_to_baseline(smoothed_event: pd.Series, smoothed_base: pd.Series) -> int | None:
    ratio = smoothed_event / smoothed_base
    ok = (ratio <= RATIO_THRESHOLD).to_numpy()
    offsets = ratio.index.to_numpy()
    post = offsets >= 0
    idxs = np.where(post)[0]
    for i in idxs:
        if i + CONSECUTIVE_MIN > len(ok):
            break
        if ok[i : i + CONSECUTIVE_MIN].all():
            return int(offsets[i])
    return None


def build_event(
    close: pd.Series, cal: pd.DataFrame, archive_dates: set, event: str
) -> tuple[pd.DataFrame, dict]:
    anchor = _anchor_minute(event)

    ev_dates = [d for d in event_dates(cal, event, scheduled_only=True) if d in archive_dates]
    assert len(ev_dates) >= 10, f"{event}: only {len(ev_dates)} event days in archive window (need >=10)"

    ev_weekdays = {pd.Timestamp(d).weekday() for d in ev_dates}
    any_event_dates = set()
    for e in EVENTS:
        any_event_dates.update(event_dates(cal, e, scheduled_only=False))
    base_dates = sorted(
        d for d in archive_dates if pd.Timestamp(d).weekday() in ev_weekdays and d not in any_event_dates
    )
    assert base_dates, f"{event}: no baseline days found"

    ev_ret, ev_cumret, ev_raw = stack_curves(close, ev_dates, anchor)
    base_ret, base_cumret, _ = stack_curves(close, base_dates, anchor)

    if event == "fomc":
        offsets = ev_raw.columns.to_numpy()
        abs_minute = anchor + offsets
        rth_mask = (abs_minute >= RTH_START_MIN) & (abs_minute < RTH_END_MIN)
        rth_vals = ev_raw.loc[:, ev_raw.columns[rth_mask]].to_numpy()
        frac_notnull = np.nanmean(rth_vals)
        assert frac_notnull >= 0.95, (
            f"fomc: RTH portion of event-day grid only {frac_notnull:.1%} non-NaN before ffill (need >=95%)"
        )

    ev_vol = ev_ret.abs().mean(axis=0, skipna=True)
    base_vol = base_ret.abs().mean(axis=0, skipna=True)
    ev_drift_bp = ev_cumret.mean(axis=0, skipna=True) * 1e4
    base_drift_bp = base_cumret.mean(axis=0, skipna=True) * 1e4

    ev_vol_s = smooth(ev_vol)
    base_vol_s = smooth(base_vol)
    vol_ratio = ev_vol_s / base_vol_s

    curves = pd.DataFrame(
        {
            "offset_min": ev_vol.index,
            "ev_vol": ev_vol.to_numpy(),
            "base_vol": base_vol.to_numpy(),
            "vol_ratio": vol_ratio.to_numpy(),
            "ev_cumret_bp": ev_drift_bp.to_numpy(),
            "base_cumret_bp": base_drift_bp.to_numpy(),
        }
    ).sort_values("offset_min").reset_index(drop=True)
    curves.insert(0, "event", event)

    mtb = minutes_to_baseline(ev_vol_s, base_vol_s)
    peak_idx = vol_ratio.astype(float).idxmax()
    summary = {
        "event": event,
        "n_events": len(ev_dates),
        "n_baseline_days": len(base_dates),
        "minutes_to_baseline": mtb,
        "peak_vol_ratio": round(float(vol_ratio.loc[peak_idx]), 3),
        "peak_offset": int(peak_idx),
        "ev_cumret_bp_30": round(float(ev_drift_bp.loc[30]), 2),
        "ev_cumret_bp_120": round(float(ev_drift_bp.loc[120]), 2),
        "base_cumret_bp_30": round(float(base_drift_bp.loc[30]), 2),
        "base_cumret_bp_120": round(float(base_drift_bp.loc[120]), 2),
    }
    return curves, summary


def plot_event(curves: pd.DataFrame, event: str, anchor: int) -> None:
    fig, (ax_vol, ax_ret) = plt.subplots(2, 1, figsize=(9, 8), sharex=True)

    ax_vol.plot(curves["offset_min"], curves["ev_vol"] * 1e4, label="event", color="tab:red")
    ax_vol.plot(curves["offset_min"], curves["base_vol"] * 1e4, label="baseline", color="tab:blue")
    ax_vol.axvline(0, color="black", linestyle="--", linewidth=1, label="event minute")
    if event == "fomc":
        ax_vol.axvline(30, color="grey", linestyle=":", linewidth=1, label="14:30 presser")
    ax_vol.set_ylabel("mean |1m log return| (bp)")
    ax_vol.set_title(f"Q2 digestion: {event.upper()} — volatility, event vs baseline")
    ax_vol.legend()

    ax_ret.plot(curves["offset_min"], curves["ev_cumret_bp"], label="event", color="tab:red")
    ax_ret.plot(curves["offset_min"], curves["base_cumret_bp"], label="baseline", color="tab:blue")
    ax_ret.axvline(0, color="black", linestyle="--", linewidth=1)
    if event == "fomc":
        ax_ret.axvline(30, color="grey", linestyle=":", linewidth=1)
    ax_ret.axhline(0, color="grey", linewidth=0.5)
    ax_ret.set_xlabel("offset from event minute (min)")
    ax_ret.set_ylabel("cumulative log return vs offset -1 (bp)")
    ax_ret.set_title(f"Q2 digestion: {event.upper()} — cumulative return, event vs baseline")
    ax_ret.legend()

    fig.tight_layout()
    fig.savefig(OUT_DIR / f"q2_{event}.png", dpi=120)
    plt.close(fig)


def main() -> None:
    cal = load_event_calendar()
    close = load_spy()
    archive_dates = set(close.index.normalize().unique())
    print(f"SPY archive: {len(archive_dates)} days ({min(archive_dates).date()} -> {max(archive_dates).date()})")

    all_curves = []
    all_summary = []
    for event in EVENTS:
        curves, summary = build_event(close, cal, archive_dates, event)
        all_curves.append(curves)
        all_summary.append(summary)
        plot_event(curves, event, _anchor_minute(event))
        print(f"{event}: {summary['n_events']} event days, {summary['n_baseline_days']} baseline days")

    curves_df = pd.concat(all_curves, ignore_index=True)
    summary_df = pd.DataFrame(all_summary)

    print("\nQ2 summary:")
    print(summary_df.to_string(index=False))

    curves_df.to_csv(OUT_DIR / "q2_curves.csv", index=False)
    summary_df.to_csv(OUT_DIR / "q2_summary.csv", index=False)


if __name__ == "__main__":
    main()
