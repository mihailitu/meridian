"""Tests for the `allowed_symbols` universe filter added to non-discovery
strategies. Regression guard for the bug where multi_timeframe / mean_reversion
/ momentum traded discovery-fed symbols they were never designed for.
"""

from datetime import datetime, timezone

import pytest

from axtrade.common import Bar
from axtrade.indicators import MarketRegime
from axtrade.strategies import (
    BarWithIndicators,
    MeanReversionStrategy,
    MomentumBreakout,
    MultiTimeframeStrategy,
)


def _bar(symbol: str = "AAPL", close: float = 100.0,
         minute: int = 0) -> BarWithIndicators:
    ts = datetime(2025, 8, 1, 14, minute, tzinfo=timezone.utc)
    return BarWithIndicators(
        bar=Bar(
            symbol=symbol,
            timestamp=ts,
            open=close,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=10_000,
        ),
        sma_20=close,
        rsi_14=50.0,
        bb_upper=close + 2,
        bb_middle=close,
        bb_lower=close - 2,
        atr=1.0,
        regime=MarketRegime.TRENDING_UP,
        trend_strength=50.0,
    )


# --- MultiTimeframeStrategy ---

class TestMultiTimeframeAllowedSymbols:
    def test_blocked_symbol_returns_none_and_doesnt_populate_htf(self) -> None:
        strat = MultiTimeframeStrategy(
            strategy_id="mtf_test",
            config={"allowed_symbols": ["AAPL"], "position_size": 10},
        )
        order = strat.on_bar(_bar(symbol="MSFT"))
        assert order is None
        # Filter must precede HTF aggregation: out-of-universe state would
        # otherwise pollute _trend_closes / _current_htf_candle.
        assert "MSFT" not in strat._current_htf_candle
        assert "MSFT" not in strat._trend_closes

    def test_allowed_symbol_runs_through_filter(self) -> None:
        strat = MultiTimeframeStrategy(
            strategy_id="mtf_test",
            config={"allowed_symbols": ["AAPL"], "position_size": 10},
        )
        # No order expected (not enough HTF data yet) but the symbol must
        # at least progress past the filter and populate HTF state.
        strat.on_bar(_bar(symbol="AAPL"))
        assert "AAPL" in strat._current_htf_candle

    def test_no_filter_when_unset(self) -> None:
        strat = MultiTimeframeStrategy(
            strategy_id="mtf_test", config={"position_size": 10}
        )
        assert strat.allowed_symbols is None
        strat.on_bar(_bar(symbol="ZBH"))
        # Without a filter, any symbol populates HTF state.
        assert "ZBH" in strat._current_htf_candle

    def test_empty_list_means_no_filter(self) -> None:
        strat = MultiTimeframeStrategy(
            strategy_id="mtf_test",
            config={"allowed_symbols": [], "position_size": 10},
        )
        assert strat.allowed_symbols is None
        strat.on_bar(_bar(symbol="ZBH"))
        assert "ZBH" in strat._current_htf_candle


# --- MeanReversionStrategy ---

class TestMeanReversionAllowedSymbols:
    def test_blocked_symbol_returns_none(self) -> None:
        strat = MeanReversionStrategy(
            strategy_id="mr_test",
            config={"allowed_symbols": ["AAPL"], "position_size": 10},
        )
        # Build a bar that would normally satisfy entry conditions.
        ts = datetime(2025, 8, 1, 14, 0, tzinfo=timezone.utc)
        bar = BarWithIndicators(
            bar=Bar(
                symbol="MSFT", timestamp=ts,
                open=100.0, high=101.0, low=99.0, close=100.0,
                volume=10_000,
            ),
            sma_20=100.0, rsi_14=20.0,       # oversold
            bb_upper=110.0, bb_middle=100.0, bb_lower=100.0,  # at lower band
            atr=1.0,
            regime=MarketRegime.RANGING_QUIET,
            trend_strength=10.0,
        )
        assert strat.on_bar(bar) is None

    def test_no_filter_when_unset(self) -> None:
        strat = MeanReversionStrategy(
            strategy_id="mr_test", config={"position_size": 10}
        )
        assert strat.allowed_symbols is None

    def test_empty_list_means_no_filter(self) -> None:
        strat = MeanReversionStrategy(
            strategy_id="mr_test",
            config={"allowed_symbols": [], "position_size": 10},
        )
        assert strat.allowed_symbols is None


# --- MomentumBreakout ---

class TestMomentumAllowedSymbols:
    def test_blocked_symbol_returns_none_and_doesnt_track_rsi(self) -> None:
        strat = MomentumBreakout(
            strategy_id="mom_test",
            config={
                "allowed_symbols": ["AAPL"],
                "rsi_cross_level": 50,
                "rsi_overbought": 70,
                "trend_strength_min": 30.0,
                "position_size": 10,
            },
        )
        order = strat.on_bar(_bar(symbol="MSFT"))
        assert order is None
        # Filter must precede _prev_rsi write — otherwise we leak RSI history
        # for out-of-universe symbols.
        assert "MSFT" not in strat._prev_rsi

    def test_allowed_symbol_tracks_rsi(self) -> None:
        strat = MomentumBreakout(
            strategy_id="mom_test",
            config={
                "allowed_symbols": ["AAPL"],
                "rsi_cross_level": 50,
                "rsi_overbought": 70,
                "trend_strength_min": 30.0,
                "position_size": 10,
            },
        )
        strat.on_bar(_bar(symbol="AAPL"))
        assert "AAPL" in strat._prev_rsi

    def test_no_filter_when_unset(self) -> None:
        strat = MomentumBreakout(
            strategy_id="mom_test",
            config={
                "rsi_cross_level": 50, "rsi_overbought": 70,
                "trend_strength_min": 30.0, "position_size": 10,
            },
        )
        assert strat.allowed_symbols is None
