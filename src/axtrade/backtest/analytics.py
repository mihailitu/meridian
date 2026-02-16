"""Performance analytics for backtesting."""

import math
from datetime import date
from decimal import Decimal

from .types import EquityPoint, TradeRecord


class PerformanceAnalyzer:
    """Calculates backtest performance metrics."""

    @staticmethod
    def calculate_metrics(
        trades: list[TradeRecord],
        equity_curve: list[EquityPoint],
        initial_capital: Decimal,
        start_date: date,
        end_date: date,
    ) -> dict:
        """Calculate all performance metrics.

        Args:
            trades: List of executed trades
            equity_curve: Equity curve data points
            initial_capital: Starting capital
            start_date: Backtest start date
            end_date: Backtest end date

        Returns:
            Dictionary of performance metrics
        """
        # Count trades (only closing trades have P&L)
        closing_trades = [t for t in trades if t.pnl is not None]
        total_trades = len(closing_trades)

        if total_trades == 0:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "total_return": 0.0,
                "annualized_return": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown": 0.0,
                "profit_factor": 0.0,
                "avg_trade_pnl": Decimal("0"),
                "avg_winner": Decimal("0"),
                "avg_loser": Decimal("0"),
                "total_commission": sum((t.commission for t in trades), Decimal("0")),
            }

        # Win/loss statistics
        winners = [t for t in closing_trades if t.pnl and t.pnl > 0]
        losers = [t for t in closing_trades if t.pnl and t.pnl < 0]

        winning_trades = len(winners)
        losing_trades = len(losers)
        win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0.0

        # P&L calculations
        total_pnl = sum((t.pnl for t in closing_trades if t.pnl), Decimal("0"))
        avg_trade_pnl = total_pnl / total_trades if total_trades > 0 else Decimal("0")

        gross_profit = sum((t.pnl for t in winners if t.pnl), Decimal("0"))
        gross_loss = abs(sum((t.pnl for t in losers if t.pnl), Decimal("0")))

        avg_winner = gross_profit / winning_trades if winning_trades > 0 else Decimal("0")
        avg_loser = (
            Decimal("-1") * gross_loss / losing_trades
            if losing_trades > 0
            else Decimal("0")
        )

        # Returns
        final_equity = equity_curve[-1].equity if equity_curve else initial_capital
        total_return = float((final_equity - initial_capital) / initial_capital * 100)

        # Annualized return
        days = (end_date - start_date).days
        if days > 0 and final_equity > 0 and initial_capital > 0:
            years = days / 365.0
            if years > 0:
                try:
                    annualized_return = (
                        math.pow(float(final_equity / initial_capital), 1 / years) - 1
                    ) * 100
                except OverflowError:
                    annualized_return = float("inf") if final_equity > initial_capital else float("-inf")
            else:
                annualized_return = 0.0
        else:
            annualized_return = 0.0

        # Sharpe ratio
        sharpe_ratio = PerformanceAnalyzer.calculate_sharpe(equity_curve)

        # Max drawdown
        max_drawdown = PerformanceAnalyzer.calculate_max_drawdown(equity_curve)

        # Profit factor
        profit_factor = PerformanceAnalyzer.calculate_profit_factor(closing_trades)

        # Total commission
        total_commission = sum((t.commission for t in trades), Decimal("0"))

        return {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": win_rate,
            "total_return": total_return,
            "annualized_return": annualized_return,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown": max_drawdown,
            "profit_factor": profit_factor,
            "avg_trade_pnl": avg_trade_pnl,
            "avg_winner": avg_winner,
            "avg_loser": avg_loser,
            "total_commission": total_commission,
        }

    @staticmethod
    def calculate_sharpe(
        equity_curve: list[EquityPoint],
        risk_free_rate: float = 0.05,
        periods_per_year: int = 252 * 390,  # Minutes in trading year
    ) -> float:
        """Calculate annualized Sharpe ratio.

        Args:
            equity_curve: Equity curve data points
            risk_free_rate: Annual risk-free rate (default 5%)
            periods_per_year: Number of periods per year for annualization

        Returns:
            Annualized Sharpe ratio
        """
        if len(equity_curve) < 2:
            return 0.0

        # Calculate period returns
        returns = []
        for i in range(1, len(equity_curve)):
            prev_equity = float(equity_curve[i - 1].equity)
            curr_equity = float(equity_curve[i].equity)
            if prev_equity > 0:
                period_return = (curr_equity - prev_equity) / prev_equity
                returns.append(period_return)

        if not returns:
            return 0.0

        # Calculate mean and standard deviation
        mean_return = sum(returns) / len(returns)
        if len(returns) < 2:
            return 0.0

        variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
        std_return = math.sqrt(variance) if variance > 0 else 0.0

        if std_return == 0:
            return 0.0

        # Annualize
        annualized_return = mean_return * periods_per_year
        annualized_std = std_return * math.sqrt(periods_per_year)

        # Sharpe ratio
        sharpe = (annualized_return - risk_free_rate) / annualized_std

        return round(sharpe, 2)

    @staticmethod
    def calculate_max_drawdown(equity_curve: list[EquityPoint]) -> float:
        """Calculate maximum drawdown percentage.

        Args:
            equity_curve: Equity curve data points

        Returns:
            Maximum drawdown as a negative percentage
        """
        if not equity_curve:
            return 0.0

        max_dd = max((float(p.drawdown) for p in equity_curve), default=0.0)
        return -max_dd  # Return as negative percentage

    @staticmethod
    def calculate_profit_factor(trades: list[TradeRecord]) -> float:
        """Calculate ratio of gross profits to gross losses.

        Args:
            trades: List of closing trades (with P&L)

        Returns:
            Profit factor (gross profit / gross loss)
        """
        gross_profit = sum(
            (float(t.pnl) for t in trades if t.pnl and t.pnl > 0),
            0.0,
        )
        gross_loss = abs(
            sum(
                (float(t.pnl) for t in trades if t.pnl and t.pnl < 0),
                0.0,
            )
        )

        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0

        return round(gross_profit / gross_loss, 2)
