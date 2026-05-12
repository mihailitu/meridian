"""Tests for IS/OOS comparison: verdict heuristic and report formatters."""

import json
from datetime import date, datetime, timezone

import pytest

from axtrade.fulltest.comparison import (
    OOSComparison,
    VERDICT_BROKEN,
    VERDICT_DEGRADED,
    VERDICT_HOLDS_UP,
    VERDICT_IS_UNPROFITABLE,
    build_comparison,
    format_comparison_json,
    format_comparison_text,
)
from axtrade.fulltest.types import (
    FullBacktestConfig,
    FullBacktestResult,
    StrategyResult,
)


def _result(
    strategies: list[StrategyResult],
    start: date,
    end: date,
    symbols: list[str] | None = None,
    overall_pf: float | None = 1.0,
    overall_sharpe: float | None = 0.5,
) -> FullBacktestResult:
    cfg = FullBacktestConfig(
        start=start,
        end=end,
        symbols=symbols or ["AAPL", "MSFT"],
        initial_capital=100_000,
        strategy_overrides={},
    )
    res = FullBacktestResult(
        config=cfg,
        start_time=datetime(2025, 8, 1, tzinfo=timezone.utc),
        end_time=datetime(2025, 8, 1, 1, tzinfo=timezone.utc),
        strategy_results=strategies,
        overall_profit_factor=overall_pf,
        overall_sharpe=overall_sharpe,
        overall_total_trades=sum(s.trade_count for s in strategies),
    )
    return res


def _strategy(
    strategy_id: str = "test-bt",
    strategy_type: str = "test",
    pnl: float = 0.0,
    pf: float | None = None,
    trades: int = 0,
    wins: int = 0,
    losses: int = 0,
    sharpe: float | None = None,
    max_dd: float = 0.0,
) -> StrategyResult:
    return StrategyResult(
        strategy_id=strategy_id,
        strategy_type=strategy_type,
        trade_count=trades,
        win_count=wins,
        loss_count=losses,
        total_pnl=pnl,
        profit_factor=pf,
        sharpe_ratio=sharpe,
        max_drawdown=max_dd,
    )


class TestVerdictMatrix:
    def test_is_unprofitable_when_is_pf_below_one(self) -> None:
        is_r = _result([_strategy(pnl=100, pf=0.5, trades=10, wins=4, losses=6)],
                       date(2024, 8, 1), date(2025, 8, 1))
        oos_r = _result([_strategy(pnl=1000, pf=3.0, trades=10, wins=9, losses=1)],
                        date(2025, 8, 1), date(2026, 2, 1))
        cmp = build_comparison(is_r, oos_r)
        assert cmp.per_strategy[0].verdict == VERDICT_IS_UNPROFITABLE

    def test_is_unprofitable_when_is_pnl_zero_or_negative(self) -> None:
        is_r = _result([_strategy(pnl=-50, pf=2.0, trades=10, wins=4, losses=6)],
                       date(2024, 8, 1), date(2025, 8, 1))
        oos_r = _result([_strategy(pnl=1000, pf=3.0, trades=10, wins=9, losses=1)],
                        date(2025, 8, 1), date(2026, 2, 1))
        cmp = build_comparison(is_r, oos_r)
        assert cmp.per_strategy[0].verdict == VERDICT_IS_UNPROFITABLE

    def test_broken_when_oos_pf_below_one(self) -> None:
        is_r = _result([_strategy(pnl=1000, pf=1.5, trades=10, wins=6, losses=4)],
                       date(2024, 8, 1), date(2025, 8, 1))
        oos_r = _result([_strategy(pnl=-200, pf=0.5, trades=10, wins=3, losses=7)],
                        date(2025, 8, 1), date(2026, 2, 1))
        cmp = build_comparison(is_r, oos_r)
        assert cmp.per_strategy[0].verdict == VERDICT_BROKEN

    def test_degraded_when_oos_pf_well_below_is(self) -> None:
        # IS PF 1.5, OOS PF 1.05 (0.7 × IS PF, below the 0.75 threshold)
        is_r = _result([_strategy(pnl=1500, pf=1.5, sharpe=1.0,
                                  trades=20, wins=12, losses=8)],
                       date(2024, 8, 1), date(2025, 8, 1))
        oos_r = _result([_strategy(pnl=100, pf=1.05, sharpe=0.8,
                                   trades=10, wins=6, losses=4)],
                        date(2025, 8, 1), date(2026, 2, 1))
        cmp = build_comparison(is_r, oos_r)
        assert cmp.per_strategy[0].verdict == VERDICT_DEGRADED

    def test_degraded_when_sharpe_halves(self) -> None:
        # PF ratio holds, but Sharpe collapses to less than half.
        is_r = _result([_strategy(pnl=1500, pf=1.4, sharpe=1.0,
                                  trades=20, wins=12, losses=8)],
                       date(2024, 8, 1), date(2025, 8, 1))
        oos_r = _result([_strategy(pnl=300, pf=1.3, sharpe=0.4,
                                   trades=15, wins=9, losses=6)],
                        date(2025, 8, 1), date(2026, 2, 1))
        cmp = build_comparison(is_r, oos_r)
        assert cmp.per_strategy[0].verdict == VERDICT_DEGRADED

    def test_holds_up_when_both_strong(self) -> None:
        is_r = _result([_strategy(pnl=1500, pf=1.5, sharpe=1.0,
                                  trades=20, wins=12, losses=8)],
                       date(2024, 8, 1), date(2025, 8, 1))
        oos_r = _result([_strategy(pnl=800, pf=1.4, sharpe=0.7,
                                   trades=10, wins=6, losses=4)],
                        date(2025, 8, 1), date(2026, 2, 1))
        cmp = build_comparison(is_r, oos_r)
        assert cmp.per_strategy[0].verdict == VERDICT_HOLDS_UP


class TestPairing:
    def test_strategies_paired_by_id(self) -> None:
        is_r = _result(
            [
                _strategy(strategy_id="a", strategy_type="ta", pnl=10, pf=1.5,
                          trades=5, wins=3, losses=2),
                _strategy(strategy_id="b", strategy_type="tb", pnl=20, pf=2.0,
                          trades=5, wins=4, losses=1),
            ],
            date(2024, 8, 1), date(2025, 8, 1),
        )
        oos_r = _result(
            [
                _strategy(strategy_id="b", strategy_type="tb", pnl=15, pf=1.6,
                          trades=4, wins=3, losses=1),
                _strategy(strategy_id="a", strategy_type="ta", pnl=5, pf=1.2,
                          trades=3, wins=2, losses=1),
            ],
            date(2025, 8, 1), date(2026, 2, 1),
        )
        cmp = build_comparison(is_r, oos_r)
        ids = [s.strategy_id for s in cmp.per_strategy]
        assert ids == ["a", "b"]
        a = cmp.per_strategy[0]
        assert a.is_total_pnl == 10
        assert a.oos_total_pnl == 5

    def test_strategy_only_in_one_run_gets_placeholder(self) -> None:
        is_r = _result(
            [_strategy(strategy_id="a", strategy_type="ta", pnl=10, pf=1.5,
                       trades=5, wins=3, losses=2)],
            date(2024, 8, 1), date(2025, 8, 1),
        )
        oos_r = _result([], date(2025, 8, 1), date(2026, 2, 1))
        cmp = build_comparison(is_r, oos_r)
        assert len(cmp.per_strategy) == 1
        a = cmp.per_strategy[0]
        assert a.is_trades == 5
        assert a.oos_trades == 0


class TestFormatters:
    def _fixture(self) -> OOSComparison:
        is_r = _result(
            [
                _strategy(strategy_id="mr-bt", strategy_type="mean_reversion",
                          pnl=89, pf=1.05, sharpe=0.4,
                          trades=156, wins=69, losses=87),
                _strategy(strategy_id="mtf-bt", strategy_type="multi_timeframe",
                          pnl=-150, pf=0.7, sharpe=-0.3,
                          trades=10, wins=0, losses=10),
            ],
            date(2024, 8, 1), date(2025, 8, 1),
            overall_pf=0.9, overall_sharpe=0.2,
        )
        oos_r = _result(
            [
                _strategy(strategy_id="mr-bt", strategy_type="mean_reversion",
                          pnl=-297, pf=0.41, sharpe=-1.5,
                          trades=72, wins=20, losses=52),
                _strategy(strategy_id="mtf-bt", strategy_type="multi_timeframe",
                          pnl=-5608, pf=0.33, sharpe=-3.7,
                          trades=648, wins=91, losses=557),
            ],
            date(2025, 8, 1), date(2026, 2, 1),
            overall_pf=0.42, overall_sharpe=-37.0,
        )
        return build_comparison(is_r, oos_r, label="baseline")

    def test_text_report_renders(self) -> None:
        cmp = self._fixture()
        text = format_comparison_text(cmp)
        # Header + sections
        assert "IS / OOS COMPARISON" in text
        assert "baseline" in text
        assert "2024-08-01" in text and "2026-02-01" in text
        assert "Overall Portfolio" in text
        assert "Per Strategy" in text
        # Verdicts visible
        assert "MR-BT" in text.upper() or "mr-bt" in text
        assert "BROKEN" in text

    def test_json_report_round_trips(self) -> None:
        cmp = self._fixture()
        js = format_comparison_json(cmp)
        data = json.loads(js)
        assert data["label"] == "baseline"
        assert data["is_period"][0] == "2024-08-01"
        assert data["oos_period"][1] == "2026-02-01"
        assert len(data["per_strategy"]) == 2
        for entry in data["per_strategy"]:
            assert entry["verdict"] in {
                VERDICT_BROKEN, VERDICT_DEGRADED,
                VERDICT_HOLDS_UP, VERDICT_IS_UNPROFITABLE,
            }
