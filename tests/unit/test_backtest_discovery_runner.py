"""Tests for BacktestDiscoveryRunner and daily_rows_from_minute_df."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from axtrade.common import Config, DiscoveryConfig, GatewayConfig, SymbolConfig
from axtrade.discovery.service import DiscoveryService
from axtrade.discovery.types import DiscoveredSymbol, ScreenerResult, ScreenerType
from axtrade.fulltest.discovery import BacktestDiscoveryRunner
from axtrade.fulltest.orchestrator import daily_rows_from_minute_df


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_config(
    auto_subscribe: bool = True,
    min_score: float = 60.0,
    interval: str = "1d",
    bar_limit: int = 50,
    static_symbols=None,
) -> Config:
    """Create a test Config with discovery settings."""
    if static_symbols is None:
        static_symbols = [
            SymbolConfig(symbol="AAPL", base_price=185.0),
            SymbolConfig(symbol="MSFT", base_price=420.0),
        ]
    return Config(
        gateway=GatewayConfig(symbols=static_symbols),
        discovery=DiscoveryConfig(
            enabled=True,
            scan_interval_seconds=60,
            auto_subscribe=auto_subscribe,
            min_score=min_score,
            interval=interval,
            bar_limit=bar_limit,
        ),
    )


def make_discovery_service(discovered_symbols=None):
    """Create a mock DiscoveryService."""
    svc = MagicMock(spec=DiscoveryService)
    # scan returns a list of ScreenerResult objects; each has match_count
    empty_result = ScreenerResult(
        screener_name="test",
        screener_type=ScreenerType.MOMENTUM,
        symbols=[],
        scan_time_ms=0.0,
        total_scanned=0,
    )
    svc.scan = AsyncMock(return_value=[empty_result])
    svc.get_discovered.return_value = discovered_symbols if discovered_symbols is not None else []
    return svc


def make_symbol_provider(symbols=None):
    """Create a mock SymbolProvider."""
    provider = MagicMock()
    provider.get_symbols = AsyncMock(return_value=symbols or ["AAPL", "MSFT", "TSLA"])
    return provider


def _t(day: int, hour: int = 13, minute: int = 30) -> datetime:
    """Build a UTC datetime in August 2025 for the given day."""
    return datetime(2025, 8, day, hour, minute, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# BacktestDiscoveryRunner tests
# ---------------------------------------------------------------------------

class TestBacktestDiscoveryRunnerScanTrigger:
    """on_bar scan-cadence: once per sim day."""

    async def test_first_bar_triggers_scan(self):
        """A scan fires on the very first bar."""
        config = make_config()
        svc = make_discovery_service()
        runner = BacktestDiscoveryRunner(
            config=config,
            discovery_service=svc,
            symbol_provider=make_symbol_provider(),
        )

        await runner.on_bar(_t(1, 13, 30))

        svc.scan.assert_called_once()

    async def test_same_day_bars_do_not_repeat_scan(self):
        """Multiple bars on the same date produce exactly one scan."""
        config = make_config()
        svc = make_discovery_service()
        runner = BacktestDiscoveryRunner(
            config=config,
            discovery_service=svc,
            symbol_provider=make_symbol_provider(),
        )

        # Four bars all on 2025-08-01
        for minute in [30, 31, 32, 33]:
            await runner.on_bar(_t(1, 13, minute))

        svc.scan.assert_called_once()

    async def test_new_date_triggers_second_scan(self):
        """A bar whose date advances the sim clock triggers exactly one more scan."""
        config = make_config()
        svc = make_discovery_service()
        runner = BacktestDiscoveryRunner(
            config=config,
            discovery_service=svc,
            symbol_provider=make_symbol_provider(),
        )

        # Day 1
        await runner.on_bar(_t(1, 13, 30))
        await runner.on_bar(_t(1, 14, 0))
        # Day 2
        await runner.on_bar(_t(2, 13, 30))
        await runner.on_bar(_t(2, 14, 0))

        assert svc.scan.call_count == 2

    async def test_three_distinct_days_three_scans(self):
        """Each new calendar date triggers exactly one scan."""
        config = make_config()
        svc = make_discovery_service()
        runner = BacktestDiscoveryRunner(
            config=config,
            discovery_service=svc,
            symbol_provider=make_symbol_provider(),
        )

        for day in [1, 2, 3]:
            for minute in [30, 31]:
                await runner.on_bar(_t(day, 13, minute))

        assert svc.scan.call_count == 3


class TestBacktestDiscoveryRunnerScanArgs:
    """Scan is called with correct as_of, interval, bar_limit."""

    async def test_scan_called_with_correct_kwargs(self):
        """scan() receives as_of=latest bar time, interval, and bar_limit from config."""
        config = make_config(interval="1d", bar_limit=75)
        svc = make_discovery_service()
        runner = BacktestDiscoveryRunner(
            config=config,
            discovery_service=svc,
            symbol_provider=make_symbol_provider(),
        )

        bar_time = _t(5, 15, 59)
        await runner.on_bar(bar_time)

        svc.scan.assert_called_once()
        kwargs = svc.scan.call_args.kwargs
        assert kwargs["as_of"] == bar_time
        assert kwargs["interval"] == "1d"
        assert kwargs["bar_limit"] == 75

    async def test_scan_as_of_is_latest_timestamp_of_the_day(self):
        """When multiple bars arrive on the same day, as_of is the latest seen."""
        config = make_config()
        svc = make_discovery_service()
        runner = BacktestDiscoveryRunner(
            config=config,
            discovery_service=svc,
            symbol_provider=make_symbol_provider(),
        )

        t1 = _t(10, 13, 30)
        t2 = _t(10, 14, 45)
        t3 = _t(10, 15, 59)
        await runner.on_bar(t1)
        await runner.on_bar(t2)
        await runner.on_bar(t3)

        # Day 2 bar to trigger second scan; the first scan already captured the
        # max of t1/t2/t3 for day 10 as the sim_time.
        await runner.on_bar(_t(11, 13, 30))

        # Second scan's as_of must equal the latest bar on day 11 so far
        second_call_kwargs = svc.scan.call_args_list[1].kwargs
        assert second_call_kwargs["as_of"] == _t(11, 13, 30)

        # First scan was triggered by t1 (first bar of day 10)
        first_call_kwargs = svc.scan.call_args_list[0].kwargs
        assert first_call_kwargs["as_of"] == t1


class TestBacktestDiscoveryRunnerMonotonicClock:
    """Sim clock must be monotonic; out-of-order bars must not roll it back."""

    async def test_out_of_order_bar_does_not_rewind_sim_time(self):
        """on_bar with t < current sim_time must not decrease sim_time."""
        config = make_config()
        svc = make_discovery_service()
        runner = BacktestDiscoveryRunner(
            config=config,
            discovery_service=svc,
            symbol_provider=make_symbol_provider(),
        )

        t_later = _t(5, 15, 0)
        t_earlier = _t(5, 13, 30)

        await runner.on_bar(t_later)
        await runner.on_bar(t_earlier)  # out-of-order; should be ignored for clock

        # sim_time must not have gone backward
        assert runner._sim_time == t_later

    async def test_out_of_order_bar_does_not_trigger_extra_scan(self):
        """Out-of-order bar on same date should not cause a second scan."""
        config = make_config()
        svc = make_discovery_service()
        runner = BacktestDiscoveryRunner(
            config=config,
            discovery_service=svc,
            symbol_provider=make_symbol_provider(),
        )

        await runner.on_bar(_t(3, 15, 0))
        await runner.on_bar(_t(3, 9, 30))  # out-of-order same day

        assert svc.scan.call_count == 1

    async def test_as_of_does_not_go_backwards_after_out_of_order(self):
        """After an out-of-order bar, the next day's scan uses the correct as_of."""
        config = make_config()
        svc = make_discovery_service()
        runner = BacktestDiscoveryRunner(
            config=config,
            discovery_service=svc,
            symbol_provider=make_symbol_provider(),
        )

        t_day1_late = _t(7, 15, 59)
        t_day1_early = _t(7, 9, 30)  # out-of-order
        t_day2 = _t(8, 13, 30)

        await runner.on_bar(t_day1_late)
        await runner.on_bar(t_day1_early)
        await runner.on_bar(t_day2)

        # Day 2 scan's as_of must equal t_day2, not the OOO earlier timestamp
        second_scan_kwargs = svc.scan.call_args_list[1].kwargs
        assert second_scan_kwargs["as_of"] == t_day2


class TestBacktestDiscoveryRunnerFeedGateway:
    """_feed_gateway: no removes, adds work, new symbols tracked."""

    async def test_stale_symbols_not_removed_in_backtest(self):
        """Symbols that fall out of discovery must NOT be removed (backtest invariant)."""
        config = make_config(auto_subscribe=True)
        svc = make_discovery_service(discovered_symbols=[])
        gateway_control = AsyncMock()
        gateway_control.add_symbols = AsyncMock(return_value=0)
        gateway_control.remove_symbols = AsyncMock(return_value=0)

        runner = BacktestDiscoveryRunner(
            config=config,
            discovery_service=svc,
            symbol_provider=make_symbol_provider(),
            gateway_control=gateway_control,
        )
        runner._subscribed_symbols = {"TSLA"}  # previously subscribed, now gone

        await runner._feed_gateway()

        gateway_control.remove_symbols.assert_not_called()

    async def test_new_symbol_above_min_score_is_added(self):
        """A newly discovered symbol above min_score must be pushed via add_symbols."""
        config = make_config(auto_subscribe=True, min_score=60.0)
        discovered = [
            DiscoveredSymbol(symbol="NVDA", source="momentum", score=80.0),
        ]
        svc = make_discovery_service(discovered_symbols=discovered)
        gateway_control = AsyncMock()
        gateway_control.add_symbols = AsyncMock(return_value=1)
        gateway_control.remove_symbols = AsyncMock(return_value=0)

        runner = BacktestDiscoveryRunner(
            config=config,
            discovery_service=svc,
            symbol_provider=make_symbol_provider(),
            gateway_control=gateway_control,
        )

        await runner._feed_gateway()

        gateway_control.add_symbols.assert_called_once()
        call_args = gateway_control.add_symbols.call_args[0][0]
        added = {s.symbol for s in call_args}
        assert "NVDA" in added

    async def test_new_symbol_tracked_after_add(self):
        """After adding a symbol it should appear in _subscribed_symbols."""
        config = make_config(auto_subscribe=True, min_score=60.0)
        discovered = [
            DiscoveredSymbol(symbol="NVDA", source="momentum", score=80.0),
        ]
        svc = make_discovery_service(discovered_symbols=discovered)
        gateway_control = AsyncMock()
        gateway_control.add_symbols = AsyncMock(return_value=1)

        runner = BacktestDiscoveryRunner(
            config=config,
            discovery_service=svc,
            symbol_provider=make_symbol_provider(),
            gateway_control=gateway_control,
        )

        assert "NVDA" not in runner._subscribed_symbols
        await runner._feed_gateway()
        assert "NVDA" in runner._subscribed_symbols

    async def test_static_symbol_never_added_again(self):
        """Static gateway symbols (already in config) must not be re-added."""
        config = make_config(
            auto_subscribe=True,
            min_score=60.0,
            static_symbols=[SymbolConfig(symbol="AAPL", base_price=185.0)],
        )
        # AAPL is discovered with a high score
        discovered = [
            DiscoveredSymbol(symbol="AAPL", source="momentum", score=90.0),
        ]
        svc = make_discovery_service(discovered_symbols=discovered)
        gateway_control = AsyncMock()
        gateway_control.add_symbols = AsyncMock(return_value=0)

        runner = BacktestDiscoveryRunner(
            config=config,
            discovery_service=svc,
            symbol_provider=make_symbol_provider(),
            gateway_control=gateway_control,
        )

        await runner._feed_gateway()

        gateway_control.add_symbols.assert_not_called()

    async def test_no_action_when_auto_subscribe_disabled(self):
        """When auto_subscribe is False, _feed_gateway must not call add_symbols."""
        config = make_config(auto_subscribe=False)
        discovered = [
            DiscoveredSymbol(symbol="NVDA", source="momentum", score=90.0),
        ]
        svc = make_discovery_service(discovered_symbols=discovered)
        gateway_control = AsyncMock()
        gateway_control.add_symbols = AsyncMock(return_value=0)

        runner = BacktestDiscoveryRunner(
            config=config,
            discovery_service=svc,
            symbol_provider=make_symbol_provider(),
            gateway_control=gateway_control,
        )

        # Trigger via on_bar (which gates on auto_subscribe inside _run_scan)
        await runner.on_bar(_t(1, 13, 30))

        gateway_control.add_symbols.assert_not_called()

    async def test_no_error_without_gateway_control(self):
        """_feed_gateway should return immediately when gateway_control is None."""
        config = make_config(auto_subscribe=True)
        svc = make_discovery_service(discovered_symbols=[
            DiscoveredSymbol(symbol="NVDA", source="momentum", score=90.0),
        ])
        runner = BacktestDiscoveryRunner(
            config=config,
            discovery_service=svc,
            symbol_provider=make_symbol_provider(),
            gateway_control=None,
        )

        # Should not raise
        await runner._feed_gateway()


# ---------------------------------------------------------------------------
# daily_rows_from_minute_df tests
# ---------------------------------------------------------------------------

def _make_minute_df(days_data: list[tuple[int, list[tuple]]]) -> pd.DataFrame:
    """Build a 1m OHLCV DataFrame.

    days_data: list of (day_of_month, [(hour, minute, open, high, low, close, vol), ...])
    All timestamps in August 2025, UTC.
    """
    rows = []
    for day, bars in days_data:
        for hour, minute, o, h, l, c, v in bars:
            rows.append({
                "timestamp": pd.Timestamp(2025, 8, day, hour, minute, 0, tz="UTC"),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": int(v),
            })
    return pd.DataFrame(rows)


class TestDailyRowsFromMinuteDf:
    """Tests for daily_rows_from_minute_df."""

    def test_one_row_per_day(self):
        """Output contains exactly one tuple per calendar day."""
        df = _make_minute_df([
            (1, [(13, 30, 100, 101, 99, 100, 1000),
                 (13, 31, 100, 102, 98, 101, 1100),
                 (13, 32, 101, 103, 100, 102, 900)]),
            (2, [(13, 30, 103, 105, 102, 104, 800),
                 (13, 31, 104, 106, 103, 105, 700)]),
            (3, [(13, 30, 105, 107, 104, 106, 600),
                 (13, 31, 106, 108, 105, 107, 500),
                 (13, 32, 107, 109, 106, 108, 400)]),
        ])
        rows = daily_rows_from_minute_df(df, "TEST")
        assert len(rows) == 3

    def test_timestamp_is_last_bar_of_day(self):
        """Each daily row's timestamp equals the last minute bar of that day."""
        df = _make_minute_df([
            (1, [(13, 30, 100, 101, 99, 100, 1000),
                 (13, 31, 100, 102, 98, 101, 1100),
                 (13, 32, 101, 103, 100, 102, 900)]),
            (2, [(13, 30, 103, 105, 102, 104, 800),
                 (14, 55, 104, 106, 103, 105, 700)]),
        ])
        rows = daily_rows_from_minute_df(df, "TEST")

        # Day 1 last bar: 13:32
        assert rows[0][0] == datetime(2025, 8, 1, 13, 32, tzinfo=timezone.utc)
        # Day 2 last bar: 14:55
        assert rows[1][0] == datetime(2025, 8, 2, 14, 55, tzinfo=timezone.utc)

    def test_ohlcv_aggregation(self):
        """open=first, high=max, low=min, close=last, volume=sum."""
        df = _make_minute_df([
            (1, [
                (13, 30, 100, 101, 98, 100, 1000),
                (13, 31, 100, 105, 95, 103, 2000),
                (13, 32, 103, 108, 97, 107, 500),
            ]),
        ])
        rows = daily_rows_from_minute_df(df, "OHLCV")
        assert len(rows) == 1
        _time, sym, o, h, l, c, v, sma, rsi = rows[0]

        assert sym == "OHLCV"
        assert float(o) == pytest.approx(100.0)  # first bar's open
        assert float(h) == pytest.approx(108.0)  # max high
        assert float(l) == pytest.approx(95.0)   # min low
        assert float(c) == pytest.approx(107.0)  # last bar's close
        assert v == 3500                          # sum of volumes

    def test_ohlcv_values_are_decimal(self):
        """OHLCV values in the output tuple must be Decimal instances."""
        df = _make_minute_df([
            (1, [(13, 30, 100, 101, 99, 100, 1000)]),
        ])
        rows = daily_rows_from_minute_df(df, "DEC")
        _time, sym, o, h, l, c, v, sma, rsi = rows[0]
        assert isinstance(o, Decimal)
        assert isinstance(h, Decimal)
        assert isinstance(l, Decimal)
        assert isinstance(c, Decimal)

    def test_sma_none_with_fewer_than_20_days(self):
        """With fewer than 20 daily bars, sma_20 (index 7) must be None."""
        # 3 days → only 3 closes → can't compute SMA-20
        df = _make_minute_df([
            (day, [(13, 30, 100 + day, 102 + day, 99 + day, 101 + day, 1000)])
            for day in range(1, 4)
        ])
        rows = daily_rows_from_minute_df(df, "SMA")
        for row in rows:
            assert row[7] is None, f"Expected sma_20=None, got {row[7]}"

    def test_rsi_none_with_fewer_than_15_days(self):
        """With fewer than 15 daily bars, rsi_14 (index 8) must be None."""
        # 10 days → only 10 closes → can't compute RSI-14
        df = _make_minute_df([
            (day, [(13, 30, 100 + day, 102 + day, 99 + day, 101 + day, 1000)])
            for day in range(1, 11)
        ])
        rows = daily_rows_from_minute_df(df, "RSI")
        for row in rows:
            assert row[8] is None, f"Expected rsi_14=None, got {row[8]}"

    def test_sma_and_rsi_non_none_with_25_plus_days(self):
        """With 25+ daily bars both sma_20 and rsi_14 must be non-None Decimals."""
        # Build 25 days across August 2025 (use days 1..25, 1 bar each)
        days_data = [
            (day, [(13, 30, 100 + day * 0.5, 102 + day * 0.5, 99 + day * 0.5, 101 + day * 0.5, 1000)])
            for day in range(1, 26)
        ]
        # Use separate months to get 25 unique dates (Aug has 31 days, so 1-25 works)
        df = _make_minute_df(days_data)
        rows = daily_rows_from_minute_df(df, "FULL")
        assert len(rows) == 25

        # The last row (index 24) has seen all 25 closes
        last_row = rows[24]
        sma = last_row[7]
        rsi = last_row[8]
        assert sma is not None, "Expected non-None sma_20 with 25 days"
        assert rsi is not None, "Expected non-None rsi_14 with 25 days"
        assert isinstance(sma, Decimal), f"sma_20 should be Decimal, got {type(sma)}"
        assert isinstance(rsi, Decimal), f"rsi_14 should be Decimal, got {type(rsi)}"

    def test_naive_timestamps_localized_to_utc(self):
        """Naive (tz-unaware) timestamps in the DataFrame are localized to UTC."""
        rows_data = []
        for minute in range(3):
            rows_data.append({
                "timestamp": pd.Timestamp(2025, 8, 1, 13, 30 + minute, 0),  # naive
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000,
            })
        df = pd.DataFrame(rows_data)

        # Should not raise
        rows = daily_rows_from_minute_df(df, "NAIVE")
        assert len(rows) == 1

        # Output timestamp must be tz-aware
        out_ts = rows[0][0]
        assert out_ts.tzinfo is not None, "Expected tz-aware output timestamp"

    def test_row_tuple_length_and_symbol(self):
        """Each row tuple has 9 elements and the correct symbol."""
        df = _make_minute_df([
            (1, [(13, 30, 100, 101, 99, 100, 1000)]),
        ])
        rows = daily_rows_from_minute_df(df, "SYMTEST")
        assert len(rows) == 1
        assert len(rows[0]) == 9
        assert rows[0][1] == "SYMTEST"
