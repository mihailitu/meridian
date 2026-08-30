"""Tests for the T1 A-lite continuous-futures builder (research/futures.py).

Synthetic two-contract fixture with a known contango basis: the front
contract A and the next contract B trade B = A + 5 throughout, so any splice
return would show up as a fake ~+5 jump. The suite asserts the roll-gap bug
class is structurally excluded.
"""

import pandas as pd
import pytest

from axtrade.research.futures import (
    ContractBars,
    build_continuous,
    build_roll_schedule,
)


def _bars(dates, closes, volumes):
    return pd.DataFrame(
        {"close": closes, "volume": volumes},
        index=pd.DatetimeIndex(pd.to_datetime(dates)),
    )


@pytest.fixture
def two_contracts():
    days = pd.bdate_range("2026-01-05", periods=8)
    # A trades the first 6 days, B all 8; B = A + 5 (constant contango basis)
    a_close = [100.0, 101.0, 102.0, 101.5, 103.0, 104.0]
    b_close = [c + 5.0 for c in a_close] + [110.0, 111.0]
    # volume crossover on day index 3 -> roll effective day index 4
    a_vol = [1000, 1000, 900, 400, 200, 100]
    b_vol = [10, 50, 300, 800, 1200, 1500, 1600, 1700]
    a = ContractBars("FUTA", pd.Timestamp("2026-01-14"), _bars(days[:6], a_close, a_vol))
    b = ContractBars("FUTB", pd.Timestamp("2026-02-13"), _bars(days, b_close, b_vol))
    return [a, b]


class TestRollSchedule:
    def test_volume_crossover_rolls_next_day(self, two_contracts):
        sched = build_roll_schedule(two_contracts, expiry_buffer_days=1)
        days = sched.index
        # crossover happens on days[3]; switch takes effect from days[4]
        assert (sched.loc[days[:4]] == "FUTA").all()
        assert (sched.loc[days[4]:] == "FUTB").all()

    def test_forced_roll_when_contract_data_ends(self, two_contracts):
        a, b = two_contracts
        # kill the volume crossover: A always dominant while it trades
        a.bars["volume"] = 10_000
        sched = build_roll_schedule([a, b], expiry_buffer_days=0)
        # A's last bar is day index 5 -> B must be active from day 6
        assert sched.iloc[6] == "FUTB"
        assert sched.iloc[5] == "FUTA"

    def test_expiry_buffer_forces_early_roll(self, two_contracts):
        a, b = two_contracts
        a.bars["volume"] = 10_000
        sched = build_roll_schedule([a, b], expiry_buffer_days=3)
        # A has 6 bars; with a 3-day buffer the roll decision fires on
        # A's 4th bar (3 remaining) -> B active from the 5th day at latest
        assert sched.iloc[4] == "FUTB"

    def test_thin_serial_month_is_skipped(self, two_contracts):
        """The roll target is the most liquid later contract, not the
        next-by-expiry one — thin serial months (GC/6E style) are skipped."""
        a, b = two_contracts
        days = b.bars.index
        serial = ContractBars(
            "FUTS",
            a.expiry + pd.Timedelta(days=14),  # expires between A and B
            _bars(days[:7], [102.0 + i for i in range(7)], [5] * 7),
        )
        sched = build_roll_schedule([a, serial, b], expiry_buffer_days=1)
        assert "FUTS" not in set(sched)
        assert sched.iloc[-1] == "FUTB"


class TestContinuous:
    def test_no_splice_return_at_roll(self, two_contracts):
        cont = build_continuous(two_contracts)
        roll_days = cont.index[cont["is_roll"]]
        assert len(roll_days) == 1
        # the +5 basis never appears: every return is small
        assert cont["ret"].abs().max() < 0.02

    def test_roll_day_return_is_within_new_contract(self, two_contracts):
        cont = build_continuous(two_contracts)
        day = cont.index[cont["is_roll"]][0]
        b = two_contracts[1].bars
        prior = b.index[b.index < day][-1]
        expected = b.loc[day, "close"] / b.loc[prior, "close"] - 1.0
        assert cont.loc[day, "ret"] == pytest.approx(expected)

    def test_level_anchored_to_final_raw_close(self, two_contracts):
        cont = build_continuous(two_contracts)
        assert cont["cont_close"].iloc[-1] == pytest.approx(cont["close_raw"].iloc[-1])

    def test_level_returns_match_ret_column(self, two_contracts):
        cont = build_continuous(two_contracts)
        level_ret = cont["cont_close"].pct_change().iloc[1:]
        pd.testing.assert_series_equal(
            level_ret, cont["ret"].iloc[1:], check_names=False, atol=1e-12, rtol=0
        )

    def test_raw_close_tracks_active_contract(self, two_contracts):
        cont = build_continuous(two_contracts)
        a, b = two_contracts
        for day, row in cont.iterrows():
            src = a if row["contract"] == "FUTA" else b
            assert row["close_raw"] == pytest.approx(src.bars.loc[day, "close"])
