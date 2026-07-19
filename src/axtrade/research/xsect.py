"""Phase 6 Phase C: cross-sectional rank-portfolio research engine.

Implements docs/phase6-preregistration.md (BINDING) exactly. Every constant
that looks arbitrary here (0.25 gap guard, $5 floor, 5-day exit search,
decile count, cost sweep, quarter spans, advance thresholds) is frozen in
that document; do not change without an amendment there.

Offline pandas/numpy pipeline over the Phase A artifacts in data/daily/.

Usage:
    python -m axtrade.research.xsect --daily-dir data/daily --out data/research
"""

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

# --- Pre-registered constants (docs/phase6-preregistration.md) ---
GAP_GUARD = 0.25          # section 5
MIN_PRICE = 5.0           # section 2
N_DECILES = 10            # section 4
COST_BPS = (0, 2, 5, 10)  # section 4; 5bp is the binding point
BINDING_BP = 5
EXIT_SEARCH_DAYS = 5      # section 4
MIN_POOL = 2 * N_DECILES  # degenerate-date floor: need >=2 names/decile

IS_START = pd.Timestamp("2024-08-01")
IS_END = pd.Timestamp("2025-08-01")
IS_QUARTERS = [           # section 7: four consecutive 3-month spans
    (pd.Timestamp("2024-08-01"), pd.Timestamp("2024-11-01")),
    (pd.Timestamp("2024-11-01"), pd.Timestamp("2025-02-01")),
    (pd.Timestamp("2025-02-01"), pd.Timestamp("2025-05-01")),
    (pd.Timestamp("2025-05-01"), pd.Timestamp("2025-08-01")),
]
QUARTER_AVAIL_FRAC = 2.0 / 3.0


@dataclass(frozen=True)
class CellSpec:
    """One grid cell: family + formation/holding parameters (section 3)."""

    family: str  # "F1" | "F2" | "F3"
    j: int       # formation lookback in trading days (0 for F1)
    hold: int    # holding period in trading days (1 for F1 = overnight)
    skip: int = 0
    primary: bool = False

    @property
    def cell_id(self) -> str:
        if self.family == "F1":
            return "F1"
        if self.family == "F2":
            return f"F2_J{self.j}_H{self.hold}"
        return f"F3_J{self.j}"

    @property
    def guard_lookback(self) -> int:
        """Gap-guard lookback L: window [D-L, D] (section 5)."""
        return self.j + self.skip


def preregistered_cells() -> list[CellSpec]:
    """The frozen grid: 1 + 9 + 2 cells, one primary per family."""
    cells = [CellSpec("F1", j=0, hold=1, primary=True)]
    for j in (1, 3, 5):
        for h in (1, 3, 5):
            cells.append(
                CellSpec("F2", j=j, hold=h, primary=(j == 5 and h == 5))
            )
    for j in (63, 126):
        cells.append(CellSpec("F3", j=j, hold=21, skip=5, primary=(j == 63)))
    return cells


@dataclass
class Pivots:
    """Wide (calendar x symbol) views of the Phase A daily artifacts."""

    calendar: pd.DatetimeIndex
    open: pd.DataFrame
    close: pd.DataFrame
    bar1600: pd.DataFrame
    gap: pd.DataFrame
    intraday: pd.DataFrame
    eligible: pd.DataFrame  # bool, False where absent


def load_pivots(daily_dir: Path) -> Pivots:
    """Load daily_bars/eligibility/calendar and pivot onto the calendar."""
    daily = pd.read_parquet(daily_dir / "daily_bars.parquet")
    elig = pd.read_parquet(daily_dir / "eligibility.parquet")
    with open(daily_dir / "calendar.txt") as f:
        calendar = pd.DatetimeIndex(
            [line.strip() for line in f if line.strip()]
        ).sort_values()

    def pivot(col: str) -> pd.DataFrame:
        return daily.pivot(index="date", columns="symbol", values=col).reindex(
            calendar
        )

    eligible = (
        elig.pivot(index="date", columns="symbol", values="eligible")
        .reindex(calendar)
        .fillna(False)
        .astype(bool)
    )
    close = pivot("rth_close")
    # Align all pivots on the union of symbols; never-eligible extras are
    # harmless (pool mask kills them).
    symbols = close.columns.union(eligible.columns)
    return Pivots(
        calendar=calendar,
        open=pivot("rth_open").reindex(columns=symbols),
        close=close.reindex(columns=symbols),
        bar1600=pivot("bar1600_close").reindex(columns=symbols),
        gap=pivot("gap_ret").reindex(columns=symbols),
        intraday=pivot("intraday_ret").reindex(columns=symbols),
        eligible=eligible.reindex(columns=symbols, fill_value=False),
    )


def compute_signal(cell: CellSpec, piv: Pivots) -> pd.DataFrame:
    """Oriented signal pivot: higher = higher predicted forward return."""
    if cell.family == "F1":
        return -piv.intraday
    if cell.family == "F2":
        return -(piv.close / piv.close.shift(cell.j) - 1)
    shifted = piv.close.shift(cell.skip)
    return shifted / shifted.shift(cell.j) - 1


def guard_exclusions(cell: CellSpec, piv: Pivots) -> pd.DataFrame:
    """Corporate-action gap guard (section 5): bool pivot, True = excluded."""
    bad = (piv.gap.abs() > GAP_GUARD).fillna(False)
    window = cell.guard_lookback + 1
    return bad.rolling(window=window, min_periods=1).sum() > 0


def formation_pool(cell: CellSpec, piv: Pivots, sig: pd.DataFrame) -> pd.DataFrame:
    """Ranking-pool membership per (date, symbol) (section 2)."""
    pool = (
        piv.eligible
        & (piv.close >= MIN_PRICE)
        & sig.notna()
        & ~guard_exclusions(cell, piv)
    )
    if cell.family == "F1":
        pool &= piv.gap.notna()  # section 2.4: row D needs prev_rth_close
    return pool


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    """Spearman rank correlation (average ranks; no scipy dependency)."""
    mask = ~(np.isnan(a) | np.isnan(b))
    a, b = a[mask], b[mask]
    if len(a) < 3:
        return float("nan")
    ra = pd.Series(a).rank().to_numpy(dtype=float, copy=True)
    rb = pd.Series(b).rank().to_numpy(dtype=float, copy=True)
    ra -= ra.mean()
    rb -= rb.mean()
    denom = np.sqrt((ra @ ra) * (rb @ rb))
    if denom == 0:
        return float("nan")
    return float((ra @ rb) / denom)


def nw_tstat(series: pd.Series, lags: int) -> float:
    """t-stat of the mean with Newey-West (Bartlett) standard errors."""
    x = series.dropna().to_numpy(dtype=float)
    n = len(x)
    if n < 2:
        return float("nan")
    e = x - x.mean()
    s = float(e @ e) / n
    for lag in range(1, min(lags, n - 1) + 1):
        w = 1.0 - lag / (lags + 1.0)
        s += 2.0 * w * float(e[lag:] @ e[:-lag]) / n
    if s <= 0:
        return float("nan")
    return float(x.mean() / np.sqrt(s / n))


@dataclass
class CellResult:
    """Everything the report and the advance rule need for one cell."""

    cell: CellSpec
    formation_dates: list[pd.Timestamp] = field(default_factory=list)
    ic_by_date: pd.Series | None = None       # Spearman(signal, gross hold ret)
    decile_means: np.ndarray | None = None    # mean gross hold ret, decile 0..9
    ls_spread: float = float("nan")           # top-minus-bottom, descriptive
    daily_net: dict[int, pd.Series] = field(default_factory=dict)  # bp -> series
    bench_daily: pd.Series | None = None      # matched EW pool, gross
    turnover_daily: float = float("nan")      # mean one-side daily fraction
    pool_sizes: pd.Series | None = None
    guard_excluded: pd.Series | None = None   # per formation date
    counts: dict[str, int] = field(default_factory=dict)


def _search_price(
    values: np.ndarray, start: int, stop: int, col: int
) -> tuple[float, int]:
    """First non-NaN values[pos, col] for pos in [start, stop]; (nan,-1) if none."""
    for pos in range(start, stop + 1):
        v = values[pos, col]
        if not np.isnan(v):
            return float(v), pos
    return float("nan"), -1


def _last_close(close_vals: np.ndarray, upto: int, col: int) -> float:
    """Last observed rth_close at position <= upto (section 4 fallback)."""
    for pos in range(upto, -1, -1):
        v = close_vals[pos, col]
        if not np.isnan(v):
            return float(v)
    return float("nan")


def _tranche_paths(
    open_vals: np.ndarray,
    close_vals: np.ndarray,
    cols: np.ndarray,
    entry_pos: int,
    exit_pos: int,
    entries: np.ndarray,
    end_pos: int,
    counts: dict[str, int],
) -> tuple[np.ndarray, np.ndarray]:
    """Daily relatives for one open-to-open tranche (F2/F3).

    Returns (rels, gross): rels is (hold, n_names) daily price relatives for
    dates entry_pos+1..exit_pos; gross is per-name total hold return.
    Interior missing days forward-fill (0 return); a missing scheduled exit
    uses the next open within EXIT_SEARCH_DAYS (clipped to end_pos), else the
    last observed close, with the final leg attributed to the exit date.
    """
    hold = exit_pos - entry_pos
    block = open_vals[entry_pos : exit_pos + 1, cols].astype(float).copy()
    block[0] = entries
    # Exit price with fallback search, replacing the last row.
    for k, col in enumerate(cols):
        if np.isnan(block[-1, k]):
            stop = min(exit_pos + EXIT_SEARCH_DAYS, end_pos)
            price, pos = _search_price(open_vals, exit_pos + 1, stop, col)
            if pos >= 0:
                counts["exit_deferred"] += 1
            else:
                price = _last_close(close_vals, stop, col)
                counts["exit_last_close"] += 1
            block[-1, k] = price
    # Interior forward-fill (row 0 is always set).
    for row in range(1, hold):
        nan = np.isnan(block[row])
        block[row, nan] = block[row - 1, nan]
    rels = block[1:] / block[:-1]
    cum = np.cumprod(rels, axis=0)
    gross = cum[-1] - 1.0
    return rels, gross


def simulate_cell(
    cell: CellSpec,
    piv: Pivots,
    window_start: pd.Timestamp = IS_START,
    window_end: pd.Timestamp = IS_END,
) -> CellResult:
    """Run one frozen grid cell over [window_start, window_end] (sections 3-4).

    Formation dates D require the FULL holding period (scheduled exit and
    any fallback search) to land on or before window_end.
    """
    sig = compute_signal(cell, piv)
    pool = formation_pool(cell, piv, sig)
    guard = guard_exclusions(cell, piv)

    cal = piv.calendar
    n = len(cal)
    end_candidates = np.nonzero(cal <= window_end)[0]
    if len(end_candidates) == 0:
        return CellResult(cell=cell)
    end_pos = int(end_candidates[-1])

    open_vals = piv.open.to_numpy(dtype=float)
    close_vals = piv.close.to_numpy(dtype=float)
    bar1600_vals = piv.bar1600.to_numpy(dtype=float)
    sig_vals = sig.to_numpy(dtype=float)
    pool_vals = pool.to_numpy(dtype=bool)

    result = CellResult(cell=cell)
    counts = {
        "bar1600_fallback": 0,
        "exit_deferred": 0,
        "exit_last_close": 0,
        "entry_deferred": 0,
        "entry_dropped": 0,
        "thin_dates_skipped": 0,
        "degenerate_dates_skipped": 0,
    }

    # Per-day accumulators: sum/count of active tranche daily net returns.
    day_sum = {bp: np.zeros(n) for bp in COST_BPS}
    day_cnt = np.zeros(n, dtype=np.int64)
    bench_sum = np.zeros(n)
    bench_cnt = np.zeros(n, dtype=np.int64)
    flow_sum = np.zeros(n)  # traded notional per date, units of tranche capital

    ic_dates: list[pd.Timestamp] = []
    ic_values: list[float] = []
    decile_sums = np.zeros(N_DECILES)
    decile_obs = 0
    ls_values: list[float] = []
    pool_sizes: list[int] = []
    guard_counts: list[int] = []

    if cell.family == "F1":
        entry_lag, exit_lag = 0, 1
    else:
        entry_lag, exit_lag = 1, 1 + cell.hold

    start_positions = np.nonzero(cal >= window_start)[0]
    if len(start_positions) == 0:
        return result
    for i in range(int(start_positions[0]), end_pos + 1):
        if i + exit_lag > end_pos:
            break  # holding period would not be realized inside the window
        members = np.nonzero(pool_vals[i])[0]
        if len(members) < MIN_POOL:
            if len(members) > 0:
                counts["thin_dates_skipped"] += 1
            continue

        ranks = pd.Series(sig_vals[i, members]).rank(method="average")
        deciles = pd.qcut(
            ranks, N_DECILES, labels=False, duplicates="drop"
        ).to_numpy(dtype=float)
        if np.all(np.isnan(deciles)):
            # Zero signal dispersion (all tied): no ranking information.
            counts["degenerate_dates_skipped"] += 1
            continue
        top = np.nanmax(deciles)

        date = cal[i]
        result.formation_dates.append(date)
        pool_sizes.append(len(members))
        guard_counts.append(int(guard.iloc[i].sum()))

        # --- Per-name entry/exit prices ---
        if cell.family == "F1":
            entries_all = bar1600_vals[i, members].copy()
            fb = np.isnan(entries_all)
            counts["bar1600_fallback"] += int(fb.sum())
            entries_all[fb] = close_vals[i, members][fb]
            exit_pos = i + 1
            gross_all = np.empty(len(members))
            for k, col in enumerate(members):
                stop = min(exit_pos + EXIT_SEARCH_DAYS, end_pos)
                price, pos = _search_price(open_vals, exit_pos, stop, col)
                if pos > exit_pos:
                    counts["exit_deferred"] += 1
                elif pos < 0:
                    price = _last_close(close_vals, stop, col)
                    counts["exit_last_close"] += 1
                gross_all[k] = price / entries_all[k] - 1.0
            long_mask = deciles == top
            gross_long = gross_all[long_mask]
            # Overnight leg realized on the scheduled exit date.
            for bp in COST_BPS:
                c = bp * 1e-4
                net = (1.0 + gross_long.mean()) * (1.0 - c) ** 2 - 1.0
                day_sum[bp][exit_pos] += net
            day_cnt[exit_pos] += 1
            bench_sum[exit_pos] += gross_all.mean()
            bench_cnt[exit_pos] += 1
            flow_sum[i] += 1.0
            flow_sum[exit_pos] += 1.0 + gross_long.mean()
        else:
            entry_sched = i + entry_lag
            exit_sched = i + exit_lag
            entries_all = open_vals[entry_sched, members].astype(float).copy()
            missing = np.nonzero(np.isnan(entries_all))[0]
            keep = np.ones(len(members), dtype=bool)
            for k in missing:
                stop = min(entry_sched + EXIT_SEARCH_DAYS, exit_sched - 1)
                price, pos = _search_price(
                    open_vals, entry_sched + 1, stop, members[k]
                )
                if pos >= 0:
                    counts["entry_deferred"] += 1
                    entries_all[k] = price
                else:
                    counts["entry_dropped"] += 1
                    keep[k] = False
            members_k = members[keep]
            entries_k = entries_all[keep]
            deciles_k = deciles[keep]
            if len(members_k) < MIN_POOL:
                # Keep bookkeeping consistent: drop the date entirely.
                result.formation_dates.pop()
                pool_sizes.pop()
                guard_counts.pop()
                counts["thin_dates_skipped"] += 1
                continue
            rels, gross_all = _tranche_paths(
                open_vals, close_vals, members_k, entry_sched, exit_sched,
                entries_k, end_pos, counts,
            )
            long_mask = deciles_k == top
            long_rels = rels[:, long_mask]
            cum = np.cumprod(long_rels, axis=0)
            value = cum.mean(axis=1)  # EW at formation, drifting (section 4)
            prev = np.concatenate(([1.0], value[:-1]))
            daily = value / prev - 1.0
            days = np.arange(entry_sched + 1, exit_sched + 1)
            for bp in COST_BPS:
                c = bp * 1e-4
                net = daily.copy()
                net[0] = (1.0 + net[0]) * (1.0 - c) - 1.0
                net[-1] = (1.0 + net[-1]) * (1.0 - c) - 1.0
                day_sum[bp][days] += net
            day_cnt[days] += 1
            bench_cum = np.cumprod(rels, axis=0).mean(axis=1)
            bench_prev = np.concatenate(([1.0], bench_cum[:-1]))
            bench_sum[days] += bench_cum / bench_prev - 1.0
            bench_cnt[days] += 1
            flow_sum[entry_sched] += 1.0
            flow_sum[exit_sched] += float(value[-1])  # exit notional = end value
            members = members_k
            deciles = deciles_k

        # --- Cross-sectional diagnostics (gross hold-period returns) ---
        gross_for_ic = gross_all
        deciles_for_ic = deciles
        sig_row = sig_vals[i, members]
        ic = spearman(np.asarray(sig_row, dtype=float), gross_for_ic)
        ic_dates.append(date)
        ic_values.append(ic)
        if np.nanmax(deciles_for_ic) == N_DECILES - 1:
            for d in range(N_DECILES):
                decile_sums[d] += gross_for_ic[deciles_for_ic == d].mean()
            decile_obs += 1
            ls_values.append(
                float(
                    gross_for_ic[deciles_for_ic == N_DECILES - 1].mean()
                    - gross_for_ic[deciles_for_ic == 0].mean()
                )
            )

    # --- Assemble series ---
    active = day_cnt > 0
    idx = cal[active]
    for bp in COST_BPS:
        result.daily_net[bp] = pd.Series(
            day_sum[bp][active] / day_cnt[active], index=idx
        )
    bench_active = bench_cnt > 0
    result.bench_daily = pd.Series(
        bench_sum[bench_active] / bench_cnt[bench_active], index=cal[bench_active]
    )
    result.ic_by_date = pd.Series(ic_values, index=pd.DatetimeIndex(ic_dates))
    if decile_obs:
        result.decile_means = decile_sums / decile_obs
        result.ls_spread = float(np.mean(ls_values))
    if result.formation_dates:
        result.pool_sizes = pd.Series(
            pool_sizes, index=pd.DatetimeIndex(result.formation_dates)
        )
        result.guard_excluded = pd.Series(
            guard_counts, index=pd.DatetimeIndex(result.formation_dates)
        )
    if active.any():
        # One-side daily turnover: traded notional / (2 x active tranches).
        result.turnover_daily = float(
            (flow_sum[active] / (2.0 * np.maximum(day_cnt[active], 1))).mean()
        )
    result.counts = counts
    return result


def _compound(series: pd.Series) -> float:
    if series is None or len(series) == 0:
        return float("nan")
    return float((1.0 + series).prod() - 1.0)


def _annualized(series: pd.Series) -> float:
    total = _compound(series)
    if np.isnan(total) or len(series) == 0:
        return float("nan")
    return float((1.0 + total) ** (252.0 / len(series)) - 1.0)


def _sharpe(series: pd.Series) -> float:
    if series is None or len(series) < 2 or series.std() == 0:
        return float("nan")
    return float(series.mean() / series.std() * np.sqrt(252.0))


def _max_drawdown(series: pd.Series) -> float:
    if series is None or len(series) == 0:
        return float("nan")
    equity = (1.0 + series).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


@dataclass
class QuarterRow:
    label: str
    trading_days: int
    signal_days: int
    available: bool
    net_return: float


def quarterly_table(result: CellResult, calendar: pd.DatetimeIndex) -> list[QuarterRow]:
    """Section 7/8: per-quarter net (binding bp) returns + availability."""
    rows = []
    net = result.daily_net.get(BINDING_BP)
    formation = pd.DatetimeIndex(result.formation_dates)
    for qs, qe in IS_QUARTERS:
        cal_days = calendar[(calendar >= qs) & (calendar < qe)]
        sig_days = int(((formation >= qs) & (formation < qe)).sum())
        available = (
            len(cal_days) > 0
            and sig_days >= QUARTER_AVAIL_FRAC * len(cal_days)
        )
        if net is not None and len(net) > 0:
            in_q = net[(net.index >= qs) & (net.index < qe)]
            q_ret = _compound(in_q) if len(in_q) else float("nan")
        else:
            q_ret = float("nan")
        rows.append(
            QuarterRow(
                label=f"{qs.date()}..{qe.date()}",
                trading_days=len(cal_days),
                signal_days=sig_days,
                available=available,
                net_return=q_ret,
            )
        )
    return rows


@dataclass
class AdvanceVerdict:
    net_viability: bool
    selection: bool
    consistency: bool
    signal_sanity: bool
    n_quarters_available: int
    advance: bool
    detail: dict


def evaluate_advance(result: CellResult, calendar: pd.DatetimeIndex) -> AdvanceVerdict:
    """Section 8 advance/kill rule, evaluated on one (primary) cell."""
    net5 = result.daily_net.get(BINDING_BP)
    gross = result.daily_net.get(0)
    net_total = _compound(net5)
    gross_total = _compound(gross)
    bench_total = _compound(result.bench_daily)

    net_viability = bool(net_total > 0)
    selection = bool(gross_total > bench_total)

    quarters = quarterly_table(result, calendar)
    avail = [q for q in quarters if q.available]
    n_avail = len(avail)
    positives = sum(1 for q in avail if q.net_return > 0)
    consistency = bool(n_avail >= 2 and positives >= n_avail - 1)

    lags = max(result.cell.hold - 1, 0)
    ic_mean = float(result.ic_by_date.mean()) if result.ic_by_date is not None else float("nan")
    ic_t = nw_tstat(result.ic_by_date, lags) if result.ic_by_date is not None else float("nan")
    signal_sanity = bool(ic_mean > 0 and abs(ic_t) >= 2.0)

    return AdvanceVerdict(
        net_viability=net_viability,
        selection=selection,
        consistency=consistency,
        signal_sanity=signal_sanity,
        n_quarters_available=n_avail,
        advance=net_viability and selection and consistency and signal_sanity,
        detail={
            "net_total_5bp": net_total,
            "gross_total": gross_total,
            "bench_gross_total": bench_total,
            "quarters_positive": positives,
            "ic_mean": ic_mean,
            "ic_nw_tstat": ic_t,
        },
    )


def cell_report(result: CellResult, calendar: pd.DatetimeIndex) -> str:
    """Markdown section for one cell."""
    c = result.cell
    lines = [f"### {c.cell_id}" + (" (PRIMARY)" if c.primary else "")]
    if not result.formation_dates:
        lines.append("- No formation dates in window.")
        return "\n".join(lines)
    lines.append(
        f"- Formation dates: {len(result.formation_dates)} "
        f"({result.formation_dates[0].date()} .. {result.formation_dates[-1].date()}); "
        f"median pool {int(result.pool_sizes.median())}"
    )
    lags = max(c.hold - 1, 0)
    ic_mean = float(result.ic_by_date.mean())
    ic_t = nw_tstat(result.ic_by_date, lags)
    lines.append(f"- Rank IC: mean {ic_mean:+.4f}, NW t-stat {ic_t:+.2f} (lags={lags})")
    if result.decile_means is not None:
        dec = " ".join(f"{x * 1e4:+.1f}" for x in result.decile_means)
        lines.append(f"- Decile mean gross hold ret (bp, D1..D10): {dec}")
        lines.append(
            f"- Long-short spread (descriptive only): "
            f"{result.ls_spread * 1e4:+.1f} bp/hold"
        )
    sweep = ", ".join(
        f"{bp}bp: {_compound(result.daily_net[bp]) * 100:+.2f}%" for bp in COST_BPS
    )
    lines.append(f"- Long-side total return by cost: {sweep}")
    net5 = result.daily_net[BINDING_BP]
    lines.append(
        f"- At {BINDING_BP}bp/side: annualized {_annualized(net5) * 100:+.2f}%, "
        f"Sharpe {_sharpe(net5):+.2f}, max drawdown {_max_drawdown(net5) * 100:.2f}%"
    )
    lines.append(
        f"- Matched EW benchmark gross total: {_compound(result.bench_daily) * 100:+.2f}% "
        f"(long-side gross {_compound(result.daily_net[0]) * 100:+.2f}%)"
    )
    lines.append(f"- Mean one-side daily turnover: {result.turnover_daily:.3f}")
    lines.append(
        f"- Guard exclusions (mean per formation date): "
        f"{float(result.guard_excluded.mean()):.1f}"
    )
    nz = {k: v for k, v in result.counts.items() if v}
    lines.append(f"- Event counts: {nz if nz else 'none'}")

    quarters = quarterly_table(result, calendar)
    lines.append("- Quarters (net at 5bp; * = available for consistency):")
    for q in quarters:
        mark = "*" if q.available else " "
        lines.append(
            f"    {mark} {q.label}: net {q.net_return * 100:+.2f}% "
            f"(signal days {q.signal_days}/{q.trading_days})"
        )

    if c.primary:
        verdict = evaluate_advance(result, calendar)
        checks = [
            ("net>0 @5bp", verdict.net_viability),
            ("gross > EW benchmark", verdict.selection),
            (
                f"quarters {verdict.detail['quarters_positive']}/"
                f"{verdict.n_quarters_available} (need n-1, n>=2)",
                verdict.consistency,
            ),
            ("IC mean>0 & |t|>=2", verdict.signal_sanity),
        ]
        for label, ok in checks:
            lines.append(f"- [{'PASS' if ok else 'FAIL'}] {label}")
        lines.append(
            f"- **VERDICT: {'ADVANCE to OOS' if verdict.advance else 'KILL'}**"
        )
    return "\n".join(lines)


def run_is_research(daily_dir: Path, out_dir: Path) -> str:
    """Run the full frozen grid on IS and write the report. Returns report text."""
    piv = load_pivots(daily_dir)
    cells = preregistered_cells()
    sections = [
        "# Phase 6 Phase C: IS research report",
        "",
        f"Window: {IS_START.date()} .. {IS_END.date()} (holding fully realized "
        "inside the window). Spec: docs/phase6-preregistration.md (binding).",
        "Survivorship note (Phase A): EW eligible universe -13.4% vs SPY over "
        "the full period; dividends excluded on both legs. Cite with every result.",
        "",
    ]
    for family in ("F1", "F2", "F3"):
        sections.append(f"## {family}")
        for cell in cells:
            if cell.family != family:
                continue
            result = simulate_cell(cell, piv)
            sections.append(cell_report(result, piv.calendar))
            sections.append("")
    report = "\n".join(sections)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "is_report.md"
    path.write_text(report)
    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="axtrade.research.xsect",
        description="Phase 6 Phase C: run the pre-registered IS grid",
    )
    parser.add_argument("--daily-dir", default="data/daily")
    parser.add_argument("--out", default="data/research")
    args = parser.parse_args()
    report = run_is_research(Path(args.daily_dir), Path(args.out))
    print(report)


if __name__ == "__main__":
    main()
