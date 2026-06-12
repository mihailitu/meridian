"""Overnight reversal strategy: buy intraday losers at the close, exit at the open."""

from datetime import date, time
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from axtrade.oms import Order, OrderSide, OrderType

from .base import BarWithIndicators, BaseStrategy

_ET = ZoneInfo("America/New_York")


class OvernightReversalStrategy(BaseStrategy):
    """Buy the day's large intraday losers near the close, sell at the next open.

    The close-to-open reversal effect: stocks that fell hard intraday tend to
    bounce overnight, an effect that persists because capturing it requires
    holding overnight risk that intraday players won't take. One decision per
    symbol per day, ~17 hours holding — round-trip costs amortize over a much
    larger expected move than any 1-minute signal.

    Mechanics (all times US/Eastern, DST-aware):
    - Track each symbol's regular-session open (first bar at/after 09:30).
    - In the entry window (default 15:50-16:00), buy a symbol whose intraday
      return (close vs session open) is at or below -loss_threshold_pct.
      One entry attempt window per day; capacity-capped.
    - Exit: holding overnight, sell on the first regular-session bar of a
      later day.

    Config:
        loss_threshold_pct: intraday drop (percent) required to enter (default 1.0)
        entry_window_start: "HH:MM" ET, start of the entry window (default "15:50")
        position_size: shares per entry (default 100)
        allowed_symbols: optional symbol whitelist
        max_positions: BaseStrategy capacity cap
    """

    def __init__(self, strategy_id: str, config: dict):
        super().__init__(strategy_id, config)
        self.loss_threshold = float(config.get("loss_threshold_pct", 1.0)) / 100.0
        self.position_size = Decimal(str(config.get("position_size", 100)))

        entry = str(config.get("entry_window_start", "15:50"))
        hour, minute = entry.split(":")
        self.entry_start = time(int(hour), int(minute))
        self.session_open_time = time(9, 30)
        self.session_close_time = time(16, 0)

        syms = config.get("allowed_symbols")
        self.allowed_symbols: Optional[set[str]] = set(syms) if syms else None

        # Per-symbol session state, keyed by ET calendar day.
        self._session_date: dict[str, date] = {}
        self._session_open: dict[str, float] = {}
        self._entered_on: dict[str, date] = {}

    @property
    def name(self) -> str:
        return "OvernightReversal"

    def on_bar(self, data: BarWithIndicators) -> Optional[Order]:
        if self.allowed_symbols is not None and data.symbol not in self.allowed_symbols:
            return None

        ts = data.bar.timestamp
        if ts.tzinfo is None:
            from datetime import timezone

            ts = ts.replace(tzinfo=timezone.utc)
        ts_et = ts.astimezone(_ET)
        day, tod = ts_et.date(), ts_et.time()
        sym = data.symbol

        position = self.get_position(sym)
        if position and position.quantity > 0:
            return self._check_exit(sym, position, day, tod)

        # Record the session open: first regular-session bar of a new ET day.
        if tod >= self.session_open_time and self._session_date.get(sym) != day:
            self._session_date[sym] = day
            self._session_open[sym] = data.bar.open

        return self._check_entry(data, sym, day, tod)

    def _check_exit(self, sym: str, position, day: date, tod: time) -> Optional[Order]:
        entered = self._entered_on.get(sym)
        if entered is None and position.opened_at is not None:
            # State lost (e.g. restart): fall back to the position's own
            # open time so the exit still fires on the next session.
            entered = position.opened_at.astimezone(_ET).date()
        if entered is None:
            return None
        if day > entered and tod >= self.session_open_time:
            self._entered_on.pop(sym, None)
            return Order(
                strategy_id=self.strategy_id,
                symbol=sym,
                side=OrderSide.SELL,
                quantity=position.quantity,
                order_type=OrderType.MARKET,
            )
        return None

    def _check_entry(
        self, data: BarWithIndicators, sym: str, day: date, tod: time
    ) -> Optional[Order]:
        if not (self.entry_start <= tod < self.session_close_time):
            return None
        if self._session_date.get(sym) != day:
            return None  # no regular-session open recorded today (data gap)
        if self._entered_on.get(sym) == day:
            return None  # one entry per symbol per day
        if self.at_capacity():
            return None

        session_open = self._session_open[sym]
        if session_open <= 0:
            return None
        intraday_return = data.close / session_open - 1.0
        if intraday_return > -self.loss_threshold:
            return None

        self._entered_on[sym] = day
        return Order(
            strategy_id=self.strategy_id,
            symbol=sym,
            side=OrderSide.BUY,
            quantity=self.position_size,
            order_type=OrderType.MARKET,
        )
