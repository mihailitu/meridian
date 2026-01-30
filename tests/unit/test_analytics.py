"""Unit tests for analytics module."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from axtrade.analytics import (
    DrawdownTracker,
    TradeRecord,
    calculate_max_drawdown,
    calculate_rolling_metrics,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_trade_stats,
    calculate_volatility,
    calculate_annualized_return,
    calculate_strategy_performance,
    calculate_correlation_matrix,
    calculate_portfolio_summary,
    analyze_time_performance,
    returns_from_equity,
)


class TestSharpeRatio:
    """Tests for Sharpe ratio calculation."""

    def test_positive_returns(self) -> None:
        # Consistent positive returns
        returns = [0.01, 0.02, 0.015, 0.01, 0.02]
        sharpe = calculate_sharpe_ratio(returns)
        assert sharpe is not None
        assert sharpe > 0

    def test_negative_returns(self) -> None:
        # Consistent negative returns
        returns = [-0.01, -0.02, -0.015, -0.01, -0.02]
        sharpe = calculate_sharpe_ratio(returns)
        assert sharpe is not None
        assert sharpe < 0

    def test_zero_volatility(self) -> None:
        # All same returns - zero std dev
        returns = [0.01, 0.01, 0.01, 0.01]
        sharpe = calculate_sharpe_ratio(returns)
        assert sharpe is None

    def test_insufficient_data(self) -> None:
        returns = [0.01]
        sharpe = calculate_sharpe_ratio(returns)
        assert sharpe is None

    def test_with_risk_free_rate(self) -> None:
        returns = [0.01, 0.02, 0.015, 0.01, 0.02]
        sharpe_no_rf = calculate_sharpe_ratio(returns, risk_free_rate=0.0)
        sharpe_with_rf = calculate_sharpe_ratio(returns, risk_free_rate=0.001)
        assert sharpe_no_rf is not None
        assert sharpe_with_rf is not None
        assert sharpe_with_rf < sharpe_no_rf


class TestSortinoRatio:
    """Tests for Sortino ratio calculation."""

    def test_positive_returns(self) -> None:
        returns = [0.01, 0.02, 0.015, 0.01, 0.02]
        sortino = calculate_sortino_ratio(returns)
        assert sortino is not None
        # With all positive returns, sortino should be high or inf

    def test_mixed_returns(self) -> None:
        returns = [0.02, -0.01, 0.03, -0.02, 0.01]
        sortino = calculate_sortino_ratio(returns)
        assert sortino is not None

    def test_all_negative(self) -> None:
        returns = [-0.01, -0.02, -0.015]
        sortino = calculate_sortino_ratio(returns)
        assert sortino is not None
        assert sortino < 0

    def test_insufficient_data(self) -> None:
        returns = [0.01]
        sortino = calculate_sortino_ratio(returns)
        assert sortino is None


class TestVolatility:
    """Tests for volatility calculation."""

    def test_normal_volatility(self) -> None:
        returns = [0.01, -0.02, 0.015, -0.01, 0.02]
        vol = calculate_volatility(returns)
        assert vol is not None
        assert vol > 0

    def test_zero_volatility(self) -> None:
        returns = [0.01, 0.01, 0.01]
        vol = calculate_volatility(returns)
        assert vol == 0.0

    def test_insufficient_data(self) -> None:
        returns = [0.01]
        vol = calculate_volatility(returns)
        assert vol is None


class TestAnnualizedReturn:
    """Tests for annualized return calculation."""

    def test_positive_returns(self) -> None:
        # 252 days of 0.1% daily return
        returns = [0.001] * 252
        ann_ret = calculate_annualized_return(returns)
        assert ann_ret is not None
        # Should be approximately 28.5% (compounded)
        assert 0.25 < ann_ret < 0.35

    def test_negative_returns(self) -> None:
        returns = [-0.001] * 252
        ann_ret = calculate_annualized_return(returns)
        assert ann_ret is not None
        assert ann_ret < 0

    def test_partial_year(self) -> None:
        # Only 30 days of data
        returns = [0.001] * 30
        ann_ret = calculate_annualized_return(returns)
        assert ann_ret is not None


class TestRollingMetrics:
    """Tests for rolling metrics calculation."""

    def test_rolling_metrics(self) -> None:
        returns = [0.01, -0.005, 0.02, 0.01, -0.01, 0.015, 0.01, -0.005]
        metrics = calculate_rolling_metrics(returns, window_days=5)

        assert metrics.data_points == 5
        assert metrics.sharpe_ratio is not None
        assert metrics.sortino_ratio is not None
        assert metrics.volatility is not None
        assert metrics.calculated_at is not None

    def test_window_larger_than_data(self) -> None:
        returns = [0.01, 0.02, 0.01]
        metrics = calculate_rolling_metrics(returns, window_days=30)

        assert metrics.data_points == 3


class TestReturnsFromEquity:
    """Tests for returns_from_equity function."""

    def test_simple_returns(self) -> None:
        equity = [100.0, 110.0, 105.0, 115.0]
        returns = returns_from_equity(equity)

        assert len(returns) == 3
        assert returns[0] == pytest.approx(0.10, rel=0.01)  # 100 -> 110
        assert returns[1] == pytest.approx(-0.0455, rel=0.01)  # 110 -> 105
        assert returns[2] == pytest.approx(0.0952, rel=0.01)  # 105 -> 115

    def test_insufficient_data(self) -> None:
        equity = [100.0]
        returns = returns_from_equity(equity)
        assert returns == []


class TestDrawdownTracker:
    """Tests for DrawdownTracker."""

    def test_no_drawdown(self) -> None:
        tracker = DrawdownTracker()
        now = datetime.now(timezone.utc)

        tracker.update(Decimal("100"), now)
        tracker.update(Decimal("110"), now + timedelta(days=1))
        tracker.update(Decimal("120"), now + timedelta(days=2))

        info = tracker.get_info()
        assert info.current_drawdown_pct == 0.0
        assert info.in_drawdown is False

    def test_drawdown_and_recovery(self) -> None:
        tracker = DrawdownTracker()
        now = datetime.now(timezone.utc)

        tracker.update(Decimal("100"), now)
        tracker.update(Decimal("90"), now + timedelta(days=1))  # 10% drawdown
        tracker.update(Decimal("100"), now + timedelta(days=2))  # Recovery

        info = tracker.get_info()
        assert info.max_drawdown_pct == pytest.approx(10.0, rel=0.01)
        assert info.in_drawdown is False

        periods = tracker.get_drawdown_periods()
        assert len(periods) == 1
        assert periods[0].is_recovered

    def test_ongoing_drawdown(self) -> None:
        tracker = DrawdownTracker()
        now = datetime.now(timezone.utc)

        tracker.update(Decimal("100"), now)
        tracker.update(Decimal("80"), now + timedelta(days=1))  # 20% drawdown

        info = tracker.get_info()
        assert info.current_drawdown_pct == pytest.approx(20.0, rel=0.01)
        assert info.in_drawdown is True

    def test_underwater_curve(self) -> None:
        tracker = DrawdownTracker()
        now = datetime.now(timezone.utc)

        tracker.update(Decimal("100"), now)
        tracker.update(Decimal("90"), now + timedelta(days=1))
        tracker.update(Decimal("95"), now + timedelta(days=2))

        curve = tracker.get_underwater_curve()
        assert len(curve) == 3
        assert curve[0][1] == 0.0  # No drawdown at start
        assert curve[1][1] == pytest.approx(10.0, rel=0.01)  # 10% DD
        assert curve[2][1] == pytest.approx(5.0, rel=0.01)  # 5% DD


class TestMaxDrawdown:
    """Tests for calculate_max_drawdown function."""

    def test_simple_drawdown(self) -> None:
        equity = [Decimal("100"), Decimal("90"), Decimal("85"), Decimal("95")]
        max_dd = calculate_max_drawdown(equity)
        assert max_dd == pytest.approx(15.0, rel=0.01)  # 100 -> 85 = 15%

    def test_no_drawdown(self) -> None:
        equity = [Decimal("100"), Decimal("110"), Decimal("120")]
        max_dd = calculate_max_drawdown(equity)
        assert max_dd == 0.0


class TestTradeStats:
    """Tests for trade statistics."""

    @pytest.fixture
    def sample_trades(self) -> list[TradeRecord]:
        now = datetime.now(timezone.utc)
        return [
            TradeRecord(
                trade_id="1",
                symbol="AAPL",
                strategy_id="momentum",
                side="buy",
                entry_time=now - timedelta(hours=4),
                exit_time=now - timedelta(hours=3),
                entry_price=Decimal("100"),
                exit_price=Decimal("105"),
                quantity=Decimal("10"),
                pnl=Decimal("50"),
            ),
            TradeRecord(
                trade_id="2",
                symbol="AAPL",
                strategy_id="momentum",
                side="buy",
                entry_time=now - timedelta(hours=2),
                exit_time=now - timedelta(hours=1),
                entry_price=Decimal("105"),
                exit_price=Decimal("100"),
                quantity=Decimal("10"),
                pnl=Decimal("-50"),
            ),
            TradeRecord(
                trade_id="3",
                symbol="MSFT",
                strategy_id="mean_reversion",
                side="buy",
                entry_time=now - timedelta(minutes=30),
                exit_time=now,
                entry_price=Decimal("200"),
                exit_price=Decimal("210"),
                quantity=Decimal("5"),
                pnl=Decimal("50"),
            ),
        ]

    def test_trade_stats(self, sample_trades: list[TradeRecord]) -> None:
        stats = calculate_trade_stats(sample_trades)

        assert stats.total_trades == 3
        assert stats.winning_trades == 2
        assert stats.losing_trades == 1
        assert stats.win_rate == pytest.approx(66.67, rel=0.1)
        assert stats.total_pnl == Decimal("50")
        assert stats.avg_win == Decimal("50")
        assert stats.avg_loss == Decimal("50")
        assert stats.profit_factor == pytest.approx(2.0, rel=0.01)

    def test_empty_trades(self) -> None:
        stats = calculate_trade_stats([])

        assert stats.total_trades == 0
        assert stats.win_rate == 0.0
        assert stats.profit_factor == 0.0

    def test_consecutive_streaks(self, sample_trades: list[TradeRecord]) -> None:
        stats = calculate_trade_stats(sample_trades)

        # With 2 wins followed by loss
        assert stats.max_consecutive_wins >= 1
        assert stats.max_consecutive_losses >= 1


class TestTimeAnalysis:
    """Tests for time-based analysis."""

    def test_time_analysis(self) -> None:
        now = datetime.now(timezone.utc)
        trades = [
            TradeRecord(
                trade_id="1",
                symbol="AAPL",
                strategy_id="test",
                side="buy",
                entry_time=now.replace(hour=10),
                exit_time=now.replace(hour=11),
                entry_price=Decimal("100"),
                exit_price=Decimal("100"),
                quantity=Decimal("10"),
                pnl=Decimal("100"),
            ),
            TradeRecord(
                trade_id="2",
                symbol="AAPL",
                strategy_id="test",
                side="buy",
                entry_time=now.replace(hour=10),
                exit_time=now.replace(hour=12),
                entry_price=Decimal("100"),
                exit_price=Decimal("100"),
                quantity=Decimal("10"),
                pnl=Decimal("50"),
            ),
        ]

        analysis = analyze_time_performance(trades)

        assert analysis.hourly_pnl[10] == Decimal("150")  # Both trades at 10am
        assert analysis.hourly_trades[10] == 2


class TestStrategyPerformance:
    """Tests for strategy-level analytics."""

    def test_strategy_performance(self) -> None:
        now = datetime.now(timezone.utc)
        trades = [
            TradeRecord(
                trade_id="1",
                symbol="AAPL",
                strategy_id="momentum",
                side="buy",
                entry_time=now - timedelta(hours=2),
                exit_time=now - timedelta(hours=1),
                entry_price=Decimal("100"),
                exit_price=Decimal("110"),
                quantity=Decimal("10"),
                pnl=Decimal("100"),
            ),
            TradeRecord(
                trade_id="2",
                symbol="AAPL",
                strategy_id="mean_reversion",
                side="buy",
                entry_time=now - timedelta(hours=1),
                exit_time=now,
                entry_price=Decimal("110"),
                exit_price=Decimal("105"),
                quantity=Decimal("10"),
                pnl=Decimal("-50"),
            ),
        ]

        perf = calculate_strategy_performance(trades)

        assert "momentum" in perf
        assert "mean_reversion" in perf
        assert perf["momentum"].total_pnl == Decimal("100")
        assert perf["mean_reversion"].total_pnl == Decimal("-50")


class TestCorrelationMatrix:
    """Tests for correlation matrix calculation."""

    def test_perfect_correlation(self) -> None:
        returns = {
            "strat_a": [0.01, 0.02, -0.01, 0.03],
            "strat_b": [0.01, 0.02, -0.01, 0.03],  # Same as A
        }

        corr = calculate_correlation_matrix(returns)

        assert corr[("strat_a", "strat_b")] == pytest.approx(1.0, rel=0.01)
        assert corr[("strat_a", "strat_a")] == 1.0

    def test_negative_correlation(self) -> None:
        returns = {
            "strat_a": [0.01, 0.02, -0.01, 0.03],
            "strat_b": [-0.01, -0.02, 0.01, -0.03],  # Opposite of A
        }

        corr = calculate_correlation_matrix(returns)

        assert corr[("strat_a", "strat_b")] == pytest.approx(-1.0, rel=0.01)

    def test_low_correlation(self) -> None:
        # Data with low correlation
        returns = {
            "strat_a": [0.01, 0.02, -0.01, 0.03, 0.005, -0.02],
            "strat_b": [0.02, 0.01, 0.01, -0.01, 0.015, 0.01],
        }

        corr = calculate_correlation_matrix(returns)

        # Should calculate a correlation value
        assert -1.0 <= corr[("strat_a", "strat_b")] <= 1.0


class TestPortfolioSummary:
    """Tests for portfolio summary."""

    def test_portfolio_summary(self) -> None:
        now = datetime.now(timezone.utc)
        trades = [
            TradeRecord(
                trade_id="1",
                symbol="AAPL",
                strategy_id="momentum",
                side="buy",
                entry_time=now - timedelta(hours=2),
                exit_time=now - timedelta(hours=1),
                entry_price=Decimal("100"),
                exit_price=Decimal("110"),
                quantity=Decimal("10"),
                pnl=Decimal("100"),
            ),
            TradeRecord(
                trade_id="2",
                symbol="MSFT",
                strategy_id="mean_reversion",
                side="buy",
                entry_time=now - timedelta(hours=1),
                exit_time=now,
                entry_price=Decimal("200"),
                exit_price=Decimal("190"),
                quantity=Decimal("5"),
                pnl=Decimal("-50"),
            ),
        ]

        summary = calculate_portfolio_summary(trades)

        assert summary.total_pnl == Decimal("50")
        assert summary.total_trades == 2
        assert summary.overall_win_rate == pytest.approx(50.0, rel=0.1)
        assert summary.strategy_count == 2
        assert summary.best_strategy == "momentum"
        assert summary.worst_strategy == "mean_reversion"

    def test_empty_portfolio(self) -> None:
        summary = calculate_portfolio_summary([])

        assert summary.total_trades == 0
        assert summary.total_pnl == Decimal("0")
