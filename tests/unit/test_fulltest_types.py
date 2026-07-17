"""Tests for fulltest types and report formatting."""

from datetime import date, datetime, timezone

import pytest

from axtrade.fulltest.report import format_json_report, format_text_report
from axtrade.fulltest.types import (
    DiscoveryResultSummary,
    FullBacktestConfig,
    FullBacktestResult,
    StrategyResult,
)


@pytest.fixture
def config():
    return FullBacktestConfig(
        start=date(2025, 8, 1),
        end=date(2026, 2, 1),
        symbols=["AAPL", "MSFT", "GOOGL"],
        interval="1m",
        initial_capital=100000.0,
    )


@pytest.fixture
def result(config):
    return FullBacktestResult(
        config=config,
        start_time=datetime(2026, 2, 15, 10, 0, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 2, 15, 10, 5, 30, tzinfo=timezone.utc),
        total_bars_processed=5000,
        total_ticks_generated=20000,
        total_orders=150,
        total_fills=145,
        final_equity=105000.0,
        strategy_results=[
            StrategyResult(
                strategy_id="momentum-bt",
                strategy_type="momentum",
                trade_count=50,
                win_count=30,
                loss_count=20,
                total_pnl=3000.0,
                profit_factor=1.8,
                symbols_traded=["AAPL", "MSFT"],
            ),
            StrategyResult(
                strategy_id="mean_reversion-bt",
                strategy_type="mean_reversion",
                trade_count=40,
                win_count=22,
                loss_count=18,
                total_pnl=2000.0,
                profit_factor=1.5,
                symbols_traded=["GOOGL"],
            ),
        ],
        discovery=DiscoveryResultSummary(
            total_scans=10,
            symbols_discovered=25,
        ),
    )


def test_config_defaults():
    cfg = FullBacktestConfig(
        start=date(2025, 1, 1),
        end=date(2025, 6, 1),
        symbols=["AAPL"],
    )
    assert cfg.interval == "1m"
    assert cfg.redis_db == 1
    assert cfg.backtest_db_name == "axtrade_backtest"
    assert cfg.initial_capital == 100000.0
    assert cfg.discovery_enabled is True
    assert cfg.ticks_per_bar == 4


def test_strategy_result_win_rate():
    sr = StrategyResult(
        strategy_id="test",
        strategy_type="momentum",
        trade_count=100,
        win_count=60,
        loss_count=40,
    )
    assert sr.win_rate == 0.6


def test_strategy_result_win_rate_zero_trades():
    sr = StrategyResult(
        strategy_id="test",
        strategy_type="momentum",
        trade_count=0,
    )
    assert sr.win_rate == 0.0


def test_result_wall_clock():
    result = FullBacktestResult(
        config=FullBacktestConfig(
            start=date(2025, 1, 1),
            end=date(2025, 6, 1),
            symbols=["AAPL"],
        ),
        start_time=datetime(2026, 2, 15, 10, 0, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 2, 15, 10, 5, 30, tzinfo=timezone.utc),
    )
    assert result.wall_clock_seconds == 330.0


def test_result_total_pnl(result):
    assert result.total_pnl == 5000.0


def test_text_report_contains_key_sections(result):
    report = format_text_report(result)

    assert "FULL SYSTEM BACKTEST REPORT" in report
    assert "PORTFOLIO ANALYTICS" in report
    assert "STRATEGY RESULTS" in report
    assert "DISCOVERY RESULTS" in report
    assert "momentum-bt" in report
    assert "mean_reversion-bt" in report
    assert "$105,000.00" in report
    assert "AAPL" in report
    assert "Sharpe (rf=0):" in report
    assert "Max Drawdown:" in report


def test_text_report_shows_return_percentage(result):
    report = format_text_report(result)
    assert "+5.00%" in report


def test_json_report_valid(result):
    import json
    report_str = format_json_report(result)
    data = json.loads(report_str)

    assert data["config"]["symbols"] == ["AAPL", "MSFT", "GOOGL"]
    assert data["results"]["final_equity"] == 105000.0
    assert data["results"]["total_pnl"] == 5000.0
    assert len(data["strategies"]) == 2
    assert data["strategies"][0]["strategy_id"] == "momentum-bt"
    assert data["discovery"]["total_scans"] == 10
    assert "analytics" in data
    assert "sharpe_ratio" in data["analytics"]
    assert "max_drawdown" in data["analytics"]
    assert "sharpe_ratio" in data["strategies"][0]
    assert "avg_winner" in data["strategies"][0]


def test_json_report_return_pct(result):
    import json
    report_str = format_json_report(result)
    data = json.loads(report_str)
    assert data["results"]["return_pct"] == 5.0


def test_discovery_result_defaults():
    d = DiscoveryResultSummary()
    assert d.total_scans == 0
    assert d.symbols_discovered == 0
    assert d.screener_stats == {}
    assert d.top_symbols == []
