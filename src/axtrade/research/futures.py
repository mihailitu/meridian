"""Continuous-futures construction from per-contract daily bars (T1 A-lite).

Builds a roll calendar and a continuous return/level series from the
individual-contract parquet files fetched by
``scripts/research/futures/fetch_ibkr_contracts.py`` into
``data/futures/ibkr/{root}/``. Offline research layer: plain pandas, no
asyncio (phase-6 pattern). See docs/t1-futures-plan.md §A3.

Design decisions (the ones a backtest silently dies on):

- **Roll rule: volume crossover with expiry fallback.** The active contract
  switches to the next-by-expiry contract at the close of the first day the
  next contract's volume exceeds the active one's (the liquidity-following
  rule CTAs approximate), and unconditionally ``expiry_buffer_days`` trading
  days before the active contract's last trade date. Decisions for day t use
  only data from day t — the switch takes effect from the NEXT day's return,
  so there is no look-ahead.
- **Returns first, levels derived.** The continuous daily return for day t is
  computed WITHIN the single contract held into day t (its close at t vs its
  own close at the previous trading day). A splice return between two
  different contracts therefore cannot exist by construction — the roll-gap
  class of bug is structurally excluded rather than patched afterwards.
- **Ratio (geometric) adjustment.** The continuous level is the cumulative
  product of (1 + return), anchored so the final level equals the last raw
  close of the final contract. Additive ("panama") adjustment can go negative
  on long histories; ratio levels cannot, and trend/vol statistics consume
  returns anyway.

The level series is an index for charting and signal math; it is NOT a
tradeable price. Raw active-contract closes stay in the output for cost and
sizing arithmetic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

DEFAULT_DATA_DIR = Path("data/futures/ibkr")
EXPIRY_BUFFER_DAYS = 3


@dataclass(frozen=True)
class ContractBars:
    """Daily bars for one contract, indexed by date, plus its expiry."""

    symbol: str
    expiry: pd.Timestamp
    bars: pd.DataFrame  # columns include close, volume; DatetimeIndex


def load_root(root: str, data_dir: Path = DEFAULT_DATA_DIR) -> list[ContractBars]:
    """Load all contracts for a root, sorted by expiry.

    Expiries come from the fetcher's manifest.json (source of truth written
    at fetch time), not from filename parsing.
    """
    manifest = json.loads((data_dir / "manifest.json").read_text())
    out: list[ContractBars] = []
    for key, meta in manifest["contracts"].items():
        m_root, symbol = key.split("/", 1)
        if m_root != root:
            continue
        path = data_dir / root / f"{symbol}.parquet"
        df = pd.read_parquet(path)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        out.append(ContractBars(symbol, pd.Timestamp(meta["expiry"][:8]), df))
    out.sort(key=lambda c: (c.expiry, c.symbol))
    if not out:
        raise FileNotFoundError(f"no contracts for root {root!r} in {data_dir}")
    return out


def coverage_start(contracts: list[ContractBars], front_days: int = 30) -> pd.Timestamp:
    """First date from which the dataset plausibly contains the true front month.

    The IBKR archive only reaches ~1y of expired contracts, so early dates
    have back months only: a schedule built there locks into deep contracts
    and can never walk back (rolls are forward-only). Front-month coverage
    begins roughly when the earliest-expiry contract enters its own front
    window — approximated as ``front_days`` calendar days before its expiry.
    """
    return min(c.expiry for c in contracts) - pd.Timedelta(days=front_days)


def build_roll_schedule(
    contracts: list[ContractBars],
    expiry_buffer_days: int = EXPIRY_BUFFER_DAYS,
    start: pd.Timestamp | None = None,
) -> pd.Series:
    """Per-day active contract symbol (the contract held INTO that day's close).

    Walks the union calendar forward. The first active contract is the
    earliest-expiry contract with data on the first day. On each day t the
    rule may decide to roll (next contract's volume > active's, or active is
    within ``expiry_buffer_days`` trading days of its last bar); the new
    contract becomes active from the following day.
    """
    by_symbol = {c.symbol: c for c in contracts}
    order = [c.symbol for c in contracts]
    calendar = sorted(set().union(*(c.bars.index for c in contracts)))
    if start is not None:
        calendar = [d for d in calendar if d >= start]

    def successor(sym: str, day: pd.Timestamp) -> str | None:
        """Best later-expiry contract: highest volume on `day`.

        Skips illiquid serial months (GC, 6E) that a naive next-by-expiry
        walk would roll through. Falls back to the next-by-expiry contract
        still holding data at/after `day` when nothing trades on `day`.
        """
        later = order[order.index(sym) + 1:]
        traded = [
            s for s in later
            if day in by_symbol[s].bars.index and by_symbol[s].bars.loc[day, "volume"] > 0
        ]
        if traded:
            return max(traded, key=lambda s: by_symbol[s].bars.loc[day, "volume"])
        alive = [s for s in later if by_symbol[s].bars.index[-1] >= day]
        return alive[0] if alive else None

    # first day: earliest-expiry contract that has data there
    first = calendar[0]
    active = next(s for s in order if first in by_symbol[s].bars.index)

    assignment: dict[pd.Timestamp, str] = {}
    for day in calendar:
        # forced roll: active contract has no more data at/after this day
        while by_symbol[active].bars.index[-1] < day:
            nxt = successor(active, day)
            if nxt is None:
                break
            active = nxt
        assignment[day] = active

        cur = by_symbol[active]
        if day not in cur.bars.index:
            continue
        nxt_sym = successor(active, day)
        if nxt_sym is None:
            continue
        remaining = cur.bars.index[cur.bars.index >= day]
        # The buffer counts bars remaining IN THE DATA, which only means
        # "near expiry" when the data actually runs to expiry (expired
        # contracts). A live contract's archive ends at the fetch date —
        # without this guard, every live contract looks near-expiry at the
        # dataset end and the schedule cascades into deep back months.
        data_ends_at_expiry = cur.bars.index[-1] >= cur.expiry - pd.Timedelta(days=5)
        near_expiry = data_ends_at_expiry and len(remaining) <= expiry_buffer_days
        nxt = by_symbol[nxt_sym]
        vol_cross = (
            day in nxt.bars.index
            and nxt.bars.loc[day, "volume"] > cur.bars.loc[day, "volume"]
        )
        if near_expiry or vol_cross:
            active = nxt_sym  # effective from the next calendar day

    return pd.Series(assignment, name="contract")


def build_continuous(
    contracts: list[ContractBars],
    schedule: pd.Series | None = None,
    start: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Continuous series: within-contract returns + ratio-adjusted level.

    Columns: contract, close_raw (active contract's close), ret (within-
    contract daily return, NaN when the active contract lacks a prior close),
    cont_close (ratio-adjusted level anchored to the final raw close),
    is_roll (True on the first day a new contract is active).
    """
    if schedule is None:
        schedule = build_roll_schedule(contracts, start=start)
    by_symbol = {c.symbol: c for c in contracts}

    rows = []
    for day, sym in schedule.items():
        bars = by_symbol[sym].bars
        if day not in bars.index:
            continue  # active contract did not trade that day
        prior = bars.index[bars.index < day]
        ret = (
            bars.loc[day, "close"] / bars.loc[prior[-1], "close"] - 1.0
            if len(prior)
            else float("nan")
        )
        rows.append((day, sym, float(bars.loc[day, "close"]), ret))

    df = pd.DataFrame(rows, columns=["date", "contract", "close_raw", "ret"])
    df = df.set_index("date").sort_index()
    df["is_roll"] = df["contract"].ne(df["contract"].shift())
    df.iloc[0, df.columns.get_loc("is_roll")] = False

    growth = (1.0 + df["ret"].fillna(0.0)).cumprod()
    df["cont_close"] = growth * (df["close_raw"].iloc[-1] / growth.iloc[-1])
    return df
