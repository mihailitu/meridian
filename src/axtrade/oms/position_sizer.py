"""Position sizing calculations for risk management."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class SizingMethod(Enum):
    """Position sizing methods."""

    FIXED = "fixed"
    RISK_PCT = "risk_pct"
    KELLY = "kelly"
    ATR = "atr"


@dataclass
class SizingResult:
    """Result of position size calculation."""

    shares: int
    dollar_amount: Decimal
    risk_amount: Decimal
    method: SizingMethod
    notes: str = ""


class PositionSizer:
    """Calculate optimal position sizes using various methods.

    Supports multiple sizing approaches:
    - Fixed: Simple fixed share count
    - Risk Percentage: Size based on max dollar risk per trade
    - Kelly Criterion: Optimal sizing based on win rate and reward/risk
    - ATR-Based: Volatility-adjusted sizing using Average True Range
    """

    def __init__(
        self,
        account_equity: Decimal,
        risk_per_trade: float = 0.02,
        max_position_pct: float = 0.10,
        kelly_fraction: float = 0.25,
        atr_multiplier: float = 2.0,
    ):
        """Initialize position sizer.

        Args:
            account_equity: Total account value
            risk_per_trade: Max risk per trade as decimal (0.02 = 2%)
            max_position_pct: Max position size as % of equity (0.10 = 10%)
            kelly_fraction: Fraction of Kelly to use (0.25 = quarter Kelly)
            atr_multiplier: Multiplier for ATR-based stops (2.0 = 2x ATR)
        """
        self.account_equity = account_equity
        self.risk_per_trade = risk_per_trade
        self.max_position_pct = max_position_pct
        self.kelly_fraction = kelly_fraction
        self.atr_multiplier = atr_multiplier

    def update_equity(self, equity: Decimal) -> None:
        """Update account equity for sizing calculations."""
        self.account_equity = equity

    def fixed_size(
        self,
        shares: int,
        price: Decimal,
        stop_loss: Decimal | None = None,
    ) -> SizingResult:
        """Return fixed share count, applying max position limit.

        Args:
            shares: Desired number of shares
            price: Current price per share
            stop_loss: Optional stop loss price for risk calculation

        Returns:
            SizingResult with position details
        """
        # Apply max position limit
        max_shares = self._max_shares(price)
        final_shares = min(shares, max_shares)

        dollar_amount = Decimal(final_shares) * price
        risk_amount = Decimal("0")
        if stop_loss is not None and final_shares > 0:
            risk_amount = Decimal(final_shares) * abs(price - stop_loss)

        return SizingResult(
            shares=final_shares,
            dollar_amount=dollar_amount,
            risk_amount=risk_amount,
            method=SizingMethod.FIXED,
            notes=f"Fixed size, max applied: {final_shares < shares}",
        )

    def risk_pct_size(
        self,
        price: Decimal,
        stop_loss: Decimal,
    ) -> SizingResult:
        """Size position based on risk percentage.

        Calculates shares such that if stop loss is hit, the loss equals
        the specified risk percentage of account equity.

        Formula: shares = (equity * risk_pct) / |price - stop_loss|

        Args:
            price: Entry price per share
            stop_loss: Stop loss price

        Returns:
            SizingResult with position details
        """
        stop_distance = abs(price - stop_loss)
        if stop_distance == 0:
            return SizingResult(
                shares=0,
                dollar_amount=Decimal("0"),
                risk_amount=Decimal("0"),
                method=SizingMethod.RISK_PCT,
                notes="Stop distance is zero",
            )

        risk_amount = self.account_equity * Decimal(str(self.risk_per_trade))
        shares = int(risk_amount / stop_distance)

        # Apply max position limit
        max_shares = self._max_shares(price)
        final_shares = min(shares, max_shares)

        dollar_amount = Decimal(final_shares) * price
        actual_risk = Decimal(final_shares) * stop_distance

        return SizingResult(
            shares=final_shares,
            dollar_amount=dollar_amount,
            risk_amount=actual_risk,
            method=SizingMethod.RISK_PCT,
            notes=f"Risk {self.risk_per_trade:.1%}, stop ${stop_distance:.2f}",
        )

    def kelly_size(
        self,
        price: Decimal,
        win_rate: float,
        avg_win: Decimal,
        avg_loss: Decimal,
    ) -> SizingResult:
        """Size position using Kelly Criterion.

        Kelly formula: f* = W - (1-W)/R
        Where:
            W = win rate
            R = reward/risk ratio (avg_win / avg_loss)

        Uses fractional Kelly (kelly_fraction) to reduce variance.

        Args:
            price: Entry price per share
            win_rate: Historical win rate (0-1)
            avg_win: Average winning trade amount
            avg_loss: Average losing trade amount (positive number)

        Returns:
            SizingResult with position details
        """
        if avg_loss == 0 or win_rate <= 0 or win_rate >= 1:
            return SizingResult(
                shares=0,
                dollar_amount=Decimal("0"),
                risk_amount=Decimal("0"),
                method=SizingMethod.KELLY,
                notes="Invalid Kelly inputs",
            )

        reward_risk = float(avg_win / avg_loss)
        kelly_pct = win_rate - ((1 - win_rate) / reward_risk)

        # Kelly can be negative (don't trade) or very high
        if kelly_pct <= 0:
            return SizingResult(
                shares=0,
                dollar_amount=Decimal("0"),
                risk_amount=Decimal("0"),
                method=SizingMethod.KELLY,
                notes=f"Negative Kelly: {kelly_pct:.2%}",
            )

        # Apply fractional Kelly
        adjusted_pct = kelly_pct * self.kelly_fraction
        dollar_amount = self.account_equity * Decimal(str(adjusted_pct))
        shares = int(dollar_amount / price)

        # Apply max position limit
        max_shares = self._max_shares(price)
        final_shares = min(shares, max_shares)

        final_dollar = Decimal(final_shares) * price
        # Estimate risk as avg_loss per share
        risk_per_share = avg_loss / Decimal(str(100))  # Normalize
        risk_amount = Decimal(final_shares) * risk_per_share

        return SizingResult(
            shares=final_shares,
            dollar_amount=final_dollar,
            risk_amount=risk_amount,
            method=SizingMethod.KELLY,
            notes=f"Kelly: {kelly_pct:.1%}, using {adjusted_pct:.1%}",
        )

    def atr_size(
        self,
        price: Decimal,
        atr: float,
    ) -> SizingResult:
        """Size position based on ATR volatility.

        Uses ATR to determine stop distance, then sizes based on risk percentage.

        Stop distance = ATR * atr_multiplier
        Shares = (equity * risk_pct) / stop_distance

        Args:
            price: Entry price per share
            atr: Current Average True Range value

        Returns:
            SizingResult with position details
        """
        if atr <= 0:
            return SizingResult(
                shares=0,
                dollar_amount=Decimal("0"),
                risk_amount=Decimal("0"),
                method=SizingMethod.ATR,
                notes="ATR is zero or negative",
            )

        stop_distance = Decimal(str(atr * self.atr_multiplier))
        risk_amount = self.account_equity * Decimal(str(self.risk_per_trade))
        shares = int(risk_amount / stop_distance)

        # Apply max position limit
        max_shares = self._max_shares(price)
        final_shares = min(shares, max_shares)

        dollar_amount = Decimal(final_shares) * price
        actual_risk = Decimal(final_shares) * stop_distance

        return SizingResult(
            shares=final_shares,
            dollar_amount=dollar_amount,
            risk_amount=actual_risk,
            method=SizingMethod.ATR,
            notes=f"ATR: {atr:.2f}, stop: ${float(stop_distance):.2f}",
        )

    def calculate(
        self,
        method: SizingMethod | str,
        price: Decimal,
        stop_loss: Decimal | None = None,
        atr: float | None = None,
        win_rate: float | None = None,
        avg_win: Decimal | None = None,
        avg_loss: Decimal | None = None,
        fixed_shares: int = 100,
    ) -> SizingResult:
        """Calculate position size using specified method.

        Convenience method that dispatches to the appropriate sizing function.

        Args:
            method: Sizing method to use
            price: Entry price
            stop_loss: Stop loss price (required for risk_pct)
            atr: ATR value (required for atr method)
            win_rate: Win rate (required for kelly)
            avg_win: Average win (required for kelly)
            avg_loss: Average loss (required for kelly)
            fixed_shares: Share count for fixed method

        Returns:
            SizingResult with position details
        """
        if isinstance(method, str):
            method = SizingMethod(method)

        if method == SizingMethod.FIXED:
            return self.fixed_size(fixed_shares, price, stop_loss)

        elif method == SizingMethod.RISK_PCT:
            if stop_loss is None:
                raise ValueError("stop_loss required for risk_pct method")
            return self.risk_pct_size(price, stop_loss)

        elif method == SizingMethod.KELLY:
            if win_rate is None or avg_win is None or avg_loss is None:
                raise ValueError("win_rate, avg_win, avg_loss required for kelly")
            return self.kelly_size(price, win_rate, avg_win, avg_loss)

        elif method == SizingMethod.ATR:
            if atr is None:
                raise ValueError("atr required for atr method")
            return self.atr_size(price, atr)

        else:
            raise ValueError(f"Unknown sizing method: {method}")

    def _max_shares(self, price: Decimal) -> int:
        """Calculate maximum shares based on position limit."""
        max_dollar = self.account_equity * Decimal(str(self.max_position_pct))
        return int(max_dollar / price)
