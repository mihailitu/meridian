"""Market definitions and utilities."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import Enum
from typing import Optional
from zoneinfo import ZoneInfo


class Market(Enum):
    """Supported markets."""

    US = "us"  # US stocks (NYSE, NASDAQ)
    EU = "eu"  # European stocks
    ASIA = "asia"  # Asian stocks (Tokyo, Hong Kong, etc.)
    CRYPTO = "crypto"  # Cryptocurrency (24/7)
    FOREX = "forex"  # Foreign exchange (24/5)


@dataclass
class TradingHours:
    """Trading hours for a market."""

    market: Market
    timezone: str
    open_time: time
    close_time: time
    pre_market_open: Optional[time] = None
    after_hours_close: Optional[time] = None

    def is_open(self, dt: Optional[datetime] = None) -> bool:
        """Check if the market is currently open.

        Args:
            dt: Datetime to check (defaults to now)

        Returns:
            True if market is open during regular hours
        """
        if dt is None:
            dt = datetime.now(ZoneInfo(self.timezone))
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))

        # Convert to market timezone
        market_time = dt.astimezone(ZoneInfo(self.timezone))

        # Check if it's a weekend (for non-crypto markets)
        if self.market != Market.CRYPTO:
            if market_time.weekday() >= 5:  # Saturday = 5, Sunday = 6
                return False

        current_time = market_time.time()
        return self.open_time <= current_time < self.close_time

    def is_extended_hours(self, dt: Optional[datetime] = None) -> bool:
        """Check if the market is in extended hours (pre-market or after-hours).

        Args:
            dt: Datetime to check (defaults to now)

        Returns:
            True if in pre-market or after-hours session
        """
        if dt is None:
            dt = datetime.now(ZoneInfo(self.timezone))
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))

        market_time = dt.astimezone(ZoneInfo(self.timezone))

        # Check if it's a weekend
        if self.market != Market.CRYPTO:
            if market_time.weekday() >= 5:
                return False

        current_time = market_time.time()

        # Check pre-market
        if self.pre_market_open and self.pre_market_open <= current_time < self.open_time:
            return True

        # Check after-hours
        if self.after_hours_close and self.close_time <= current_time < self.after_hours_close:
            return True

        return False

    def time_until_open(self, dt: Optional[datetime] = None) -> Optional[timedelta]:
        """Get time remaining until market opens.

        Args:
            dt: Datetime to check (defaults to now)

        Returns:
            Timedelta until open, or None if already open
        """
        if self.is_open(dt):
            return None

        if dt is None:
            dt = datetime.now(ZoneInfo(self.timezone))
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))

        market_time = dt.astimezone(ZoneInfo(self.timezone))

        # Calculate next open time
        next_open = market_time.replace(
            hour=self.open_time.hour,
            minute=self.open_time.minute,
            second=0,
            microsecond=0,
        )

        # If we're past today's open, look at tomorrow
        if market_time.time() >= self.open_time:
            next_open += timedelta(days=1)

        # Skip weekends for non-crypto markets
        if self.market != Market.CRYPTO:
            while next_open.weekday() >= 5:
                next_open += timedelta(days=1)

        return next_open - market_time

    def time_until_close(self, dt: Optional[datetime] = None) -> Optional[timedelta]:
        """Get time remaining until market closes.

        Args:
            dt: Datetime to check (defaults to now)

        Returns:
            Timedelta until close, or None if already closed
        """
        if not self.is_open(dt):
            return None

        if dt is None:
            dt = datetime.now(ZoneInfo(self.timezone))
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))

        market_time = dt.astimezone(ZoneInfo(self.timezone))

        # Calculate today's close time
        close_dt = market_time.replace(
            hour=self.close_time.hour,
            minute=self.close_time.minute,
            second=0,
            microsecond=0,
        )

        return close_dt - market_time


# Pre-defined trading hours for each market
MARKET_HOURS: dict[Market, TradingHours] = {
    Market.US: TradingHours(
        market=Market.US,
        timezone="America/New_York",
        open_time=time(9, 30),
        close_time=time(16, 0),
        pre_market_open=time(4, 0),
        after_hours_close=time(20, 0),
    ),
    Market.EU: TradingHours(
        market=Market.EU,
        timezone="Europe/London",
        open_time=time(8, 0),
        close_time=time(16, 30),
    ),
    Market.ASIA: TradingHours(
        market=Market.ASIA,
        timezone="Asia/Tokyo",
        open_time=time(9, 0),
        close_time=time(15, 0),
    ),
    Market.CRYPTO: TradingHours(
        market=Market.CRYPTO,
        timezone="UTC",
        open_time=time(0, 0),
        close_time=time(23, 59, 59),
    ),
    Market.FOREX: TradingHours(
        market=Market.FOREX,
        timezone="UTC",
        open_time=time(0, 0),  # Sunday 5pm EST = Monday 0:00 UTC (approx)
        close_time=time(23, 59, 59),  # Friday 5pm EST
    ),
}


def get_market_hours(market: Market) -> TradingHours:
    """Get trading hours for a market.

    Args:
        market: Market enum value

    Returns:
        TradingHours instance for the market
    """
    return MARKET_HOURS[market]


def is_market_open(market: Market, dt: Optional[datetime] = None) -> bool:
    """Check if a market is currently open.

    Args:
        market: Market to check
        dt: Datetime to check (defaults to now)

    Returns:
        True if market is open
    """
    return MARKET_HOURS[market].is_open(dt)


def get_all_market_status(dt: Optional[datetime] = None) -> dict[Market, bool]:
    """Get open/closed status for all markets.

    Args:
        dt: Datetime to check (defaults to now)

    Returns:
        Dict mapping market to open status
    """
    return {market: is_market_open(market, dt) for market in Market}


@dataclass
class MarketStatus:
    """Current status of a market."""

    market: Market
    is_open: bool
    is_extended_hours: bool
    time_until_open: Optional[timedelta]
    time_until_close: Optional[timedelta]
    timezone: str
    local_time: str

    @classmethod
    def from_market(cls, market: Market, dt: Optional[datetime] = None) -> "MarketStatus":
        """Create MarketStatus from a market at a given time."""
        hours = MARKET_HOURS[market]

        if dt is None:
            dt = datetime.now(ZoneInfo(hours.timezone))
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))

        local_time = dt.astimezone(ZoneInfo(hours.timezone))

        return cls(
            market=market,
            is_open=hours.is_open(dt),
            is_extended_hours=hours.is_extended_hours(dt),
            time_until_open=hours.time_until_open(dt),
            time_until_close=hours.time_until_close(dt),
            timezone=hours.timezone,
            local_time=local_time.strftime("%H:%M:%S"),
        )
