"""Drawdown tracking and analysis."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal


@dataclass
class DrawdownPeriod:
    """Represents a single drawdown period."""

    start_date: datetime
    end_date: datetime | None  # None if still in drawdown
    peak_value: Decimal
    trough_value: Decimal
    trough_date: datetime
    max_drawdown_pct: float  # As positive percentage
    duration_days: int
    recovery_days: int | None  # Days from trough to recovery

    @property
    def is_recovered(self) -> bool:
        """Check if drawdown has recovered."""
        return self.end_date is not None


@dataclass
class DrawdownInfo:
    """Current drawdown state and statistics."""

    current_drawdown_pct: float  # Current % below peak (positive number)
    max_drawdown_pct: float  # Maximum drawdown ever seen
    current_value: Decimal
    peak_value: Decimal  # High water mark
    trough_value: Decimal  # Lowest point in current DD
    peak_date: datetime
    trough_date: datetime | None
    in_drawdown: bool
    drawdown_duration_days: int  # Days in current drawdown (0 if not in DD)
    avg_drawdown_pct: float  # Average of all drawdown periods
    avg_recovery_days: float | None  # Average recovery time


@dataclass
class EquityPoint:
    """Single point in equity curve."""

    timestamp: datetime
    value: Decimal


class DrawdownTracker:
    """Track drawdowns over time.

    Maintains high water mark and calculates drawdown statistics.
    """

    def __init__(self) -> None:
        """Initialize tracker."""
        self._peak_value: Decimal | None = None
        self._peak_date: datetime | None = None
        self._trough_value: Decimal | None = None
        self._trough_date: datetime | None = None
        self._current_value: Decimal | None = None
        self._current_date: datetime | None = None
        self._max_drawdown_pct: float = 0.0
        self._in_drawdown: bool = False
        self._drawdown_start: datetime | None = None

        self._drawdown_periods: list[DrawdownPeriod] = []
        self._equity_history: list[EquityPoint] = []

    def update(self, value: Decimal, timestamp: datetime) -> DrawdownInfo:
        """Update tracker with new equity value.

        Args:
            value: Current equity value
            timestamp: Timestamp of the value

        Returns:
            Current drawdown information
        """
        self._current_value = value
        self._current_date = timestamp
        self._equity_history.append(EquityPoint(timestamp=timestamp, value=value))

        # First value - set as peak
        if self._peak_value is None:
            self._peak_value = value
            self._peak_date = timestamp
            self._trough_value = value
            self._trough_date = timestamp
            return self.get_info()

        # New high water mark
        if value >= self._peak_value:
            # If we were in drawdown, record the period
            if self._in_drawdown and self._drawdown_start is not None:
                self._record_drawdown_period(recovery_date=timestamp)

            self._peak_value = value
            self._peak_date = timestamp
            self._trough_value = value
            self._trough_date = timestamp
            self._in_drawdown = False
            self._drawdown_start = None
        else:
            # In drawdown
            if not self._in_drawdown:
                self._in_drawdown = True
                self._drawdown_start = timestamp
                self._trough_value = value
                self._trough_date = timestamp

            # New trough?
            if value < self._trough_value:
                self._trough_value = value
                self._trough_date = timestamp

            # Update max drawdown
            current_dd = self._calculate_drawdown_pct(value)
            if current_dd > self._max_drawdown_pct:
                self._max_drawdown_pct = current_dd

        return self.get_info()

    def _calculate_drawdown_pct(self, value: Decimal) -> float:
        """Calculate drawdown percentage from peak.

        Args:
            value: Current value

        Returns:
            Drawdown as positive percentage
        """
        if self._peak_value is None or self._peak_value == 0:
            return 0.0

        return float((self._peak_value - value) / self._peak_value) * 100

    def _record_drawdown_period(self, recovery_date: datetime) -> None:
        """Record a completed drawdown period.

        Args:
            recovery_date: Date when equity recovered to peak
        """
        if self._drawdown_start is None or self._trough_date is None:
            return

        duration = (recovery_date - self._drawdown_start).days
        recovery_days = (recovery_date - self._trough_date).days

        period = DrawdownPeriod(
            start_date=self._drawdown_start,
            end_date=recovery_date,
            peak_value=self._peak_value,
            trough_value=self._trough_value,
            trough_date=self._trough_date,
            max_drawdown_pct=self._calculate_drawdown_pct(self._trough_value),
            duration_days=duration,
            recovery_days=recovery_days,
        )
        self._drawdown_periods.append(period)

    def get_info(self) -> DrawdownInfo:
        """Get current drawdown information.

        Returns:
            DrawdownInfo with current state
        """
        if self._current_value is None:
            return DrawdownInfo(
                current_drawdown_pct=0.0,
                max_drawdown_pct=0.0,
                current_value=Decimal("0"),
                peak_value=Decimal("0"),
                trough_value=Decimal("0"),
                peak_date=datetime.now(timezone.utc),
                trough_date=None,
                in_drawdown=False,
                drawdown_duration_days=0,
                avg_drawdown_pct=0.0,
                avg_recovery_days=None,
            )

        current_dd = self._calculate_drawdown_pct(self._current_value)
        duration = 0
        if self._in_drawdown and self._drawdown_start is not None:
            duration = (self._current_date - self._drawdown_start).days

        # Calculate averages from historical periods
        avg_dd = 0.0
        avg_recovery: float | None = None
        if self._drawdown_periods:
            avg_dd = sum(p.max_drawdown_pct for p in self._drawdown_periods) / len(
                self._drawdown_periods
            )
            recovery_times = [
                p.recovery_days for p in self._drawdown_periods if p.recovery_days
            ]
            if recovery_times:
                avg_recovery = sum(recovery_times) / len(recovery_times)

        return DrawdownInfo(
            current_drawdown_pct=current_dd,
            max_drawdown_pct=self._max_drawdown_pct,
            current_value=self._current_value,
            peak_value=self._peak_value,
            trough_value=self._trough_value,
            peak_date=self._peak_date,
            trough_date=self._trough_date if self._in_drawdown else None,
            in_drawdown=self._in_drawdown,
            drawdown_duration_days=duration,
            avg_drawdown_pct=avg_dd,
            avg_recovery_days=avg_recovery,
        )

    def get_drawdown_periods(self) -> list[DrawdownPeriod]:
        """Get all completed drawdown periods.

        Returns:
            List of DrawdownPeriod objects
        """
        return self._drawdown_periods.copy()

    def get_underwater_curve(self) -> list[tuple[datetime, float]]:
        """Get underwater equity curve (drawdown over time).

        Returns:
            List of (timestamp, drawdown_pct) tuples
        """
        if not self._equity_history:
            return []

        underwater = []
        peak = self._equity_history[0].value

        for point in self._equity_history:
            if point.value > peak:
                peak = point.value

            if peak > 0:
                dd_pct = float((peak - point.value) / peak) * 100
            else:
                dd_pct = 0.0

            underwater.append((point.timestamp, dd_pct))

        return underwater

    def reset(self) -> None:
        """Reset tracker state."""
        self._peak_value = None
        self._peak_date = None
        self._trough_value = None
        self._trough_date = None
        self._current_value = None
        self._current_date = None
        self._max_drawdown_pct = 0.0
        self._in_drawdown = False
        self._drawdown_start = None
        self._drawdown_periods.clear()
        self._equity_history.clear()


def calculate_max_drawdown(equity_values: list[Decimal]) -> float:
    """Calculate maximum drawdown from equity series.

    Args:
        equity_values: List of equity values

    Returns:
        Maximum drawdown as positive percentage
    """
    if len(equity_values) < 2:
        return 0.0

    max_dd = 0.0
    peak = equity_values[0]

    for value in equity_values:
        if value > peak:
            peak = value

        if peak > 0:
            dd = float((peak - value) / peak) * 100
            if dd > max_dd:
                max_dd = dd

    return max_dd
