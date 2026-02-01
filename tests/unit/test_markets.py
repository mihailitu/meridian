"""Unit tests for markets module."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from axtrade.common.markets import (
    Market,
    MarketStatus,
    TradingHours,
    get_all_market_status,
    get_market_hours,
    is_market_open,
    MARKET_HOURS,
)


class TestMarketEnum:
    """Tests for Market enum."""

    def test_all_markets_exist(self):
        """Test all expected markets are defined."""
        assert Market.US.value == "us"
        assert Market.EU.value == "eu"
        assert Market.ASIA.value == "asia"
        assert Market.CRYPTO.value == "crypto"
        assert Market.FOREX.value == "forex"

    def test_market_count(self):
        """Test expected number of markets."""
        assert len(Market) == 5


class TestTradingHours:
    """Tests for TradingHours class."""

    def test_us_market_hours(self):
        """Test US market trading hours."""
        hours = MARKET_HOURS[Market.US]
        assert hours.market == Market.US
        assert hours.timezone == "America/New_York"
        assert hours.open_time == time(9, 30)
        assert hours.close_time == time(16, 0)
        assert hours.pre_market_open == time(4, 0)
        assert hours.after_hours_close == time(20, 0)

    def test_eu_market_hours(self):
        """Test EU market trading hours."""
        hours = MARKET_HOURS[Market.EU]
        assert hours.market == Market.EU
        assert hours.timezone == "Europe/London"
        assert hours.open_time == time(8, 0)
        assert hours.close_time == time(16, 30)

    def test_asia_market_hours(self):
        """Test Asia market trading hours."""
        hours = MARKET_HOURS[Market.ASIA]
        assert hours.market == Market.ASIA
        assert hours.timezone == "Asia/Tokyo"
        assert hours.open_time == time(9, 0)
        assert hours.close_time == time(15, 0)

    def test_crypto_market_hours(self):
        """Test crypto market (24/7)."""
        hours = MARKET_HOURS[Market.CRYPTO]
        assert hours.market == Market.CRYPTO
        assert hours.timezone == "UTC"
        assert hours.open_time == time(0, 0)

    def test_is_open_during_regular_hours(self):
        """Test is_open returns True during regular trading hours."""
        hours = MARKET_HOURS[Market.US]
        # Monday at 10:00 AM ET
        dt = datetime(2024, 1, 8, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert hours.is_open(dt) is True

    def test_is_open_before_market_open(self):
        """Test is_open returns False before market opens."""
        hours = MARKET_HOURS[Market.US]
        # Monday at 8:00 AM ET (before 9:30 AM open)
        dt = datetime(2024, 1, 8, 8, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert hours.is_open(dt) is False

    def test_is_open_after_market_close(self):
        """Test is_open returns False after market closes."""
        hours = MARKET_HOURS[Market.US]
        # Monday at 5:00 PM ET (after 4:00 PM close)
        dt = datetime(2024, 1, 8, 17, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert hours.is_open(dt) is False

    def test_is_open_on_weekend(self):
        """Test is_open returns False on weekends for non-crypto markets."""
        hours = MARKET_HOURS[Market.US]
        # Saturday at 10:00 AM ET
        dt = datetime(2024, 1, 6, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert hours.is_open(dt) is False

    def test_crypto_always_open(self):
        """Test crypto market is always open (24/7)."""
        hours = MARKET_HOURS[Market.CRYPTO]
        # Saturday
        dt_weekend = datetime(2024, 1, 6, 10, 0, 0, tzinfo=ZoneInfo("UTC"))
        assert hours.is_open(dt_weekend) is True
        # Weekday
        dt_weekday = datetime(2024, 1, 8, 3, 0, 0, tzinfo=ZoneInfo("UTC"))
        assert hours.is_open(dt_weekday) is True

    def test_is_extended_hours_premarket(self):
        """Test pre-market detection."""
        hours = MARKET_HOURS[Market.US]
        # Monday at 6:00 AM ET (pre-market hours 4:00-9:30 AM)
        dt = datetime(2024, 1, 8, 6, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert hours.is_open(dt) is False
        assert hours.is_extended_hours(dt) is True

    def test_is_extended_hours_afterhours(self):
        """Test after-hours detection."""
        hours = MARKET_HOURS[Market.US]
        # Monday at 6:00 PM ET (after-hours 4:00-8:00 PM)
        dt = datetime(2024, 1, 8, 18, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert hours.is_open(dt) is False
        assert hours.is_extended_hours(dt) is True

    def test_is_extended_hours_regular_session(self):
        """Test extended hours is False during regular session."""
        hours = MARKET_HOURS[Market.US]
        # Monday at 10:00 AM ET
        dt = datetime(2024, 1, 8, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert hours.is_open(dt) is True
        assert hours.is_extended_hours(dt) is False

    def test_is_extended_hours_weekend(self):
        """Test extended hours is False on weekends."""
        hours = MARKET_HOURS[Market.US]
        # Saturday at 6:00 AM ET
        dt = datetime(2024, 1, 6, 6, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert hours.is_extended_hours(dt) is False

    def test_time_until_open_when_closed(self):
        """Test time_until_open when market is closed."""
        hours = MARKET_HOURS[Market.US]
        # Monday at 8:00 AM ET
        dt = datetime(2024, 1, 8, 8, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        time_until = hours.time_until_open(dt)
        assert time_until is not None
        assert time_until == timedelta(hours=1, minutes=30)

    def test_time_until_open_when_already_open(self):
        """Test time_until_open returns None when market is open."""
        hours = MARKET_HOURS[Market.US]
        # Monday at 10:00 AM ET
        dt = datetime(2024, 1, 8, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert hours.time_until_open(dt) is None

    def test_time_until_open_skips_weekends(self):
        """Test time_until_open skips weekends."""
        hours = MARKET_HOURS[Market.US]
        # Saturday at 10:00 AM ET
        dt = datetime(2024, 1, 6, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        time_until = hours.time_until_open(dt)
        assert time_until is not None
        # Should be Monday 9:30 AM - Saturday 10:00 AM = ~47.5 hours
        assert time_until.days >= 1

    def test_time_until_close_when_open(self):
        """Test time_until_close when market is open."""
        hours = MARKET_HOURS[Market.US]
        # Monday at 10:00 AM ET
        dt = datetime(2024, 1, 8, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        time_until = hours.time_until_close(dt)
        assert time_until is not None
        assert time_until == timedelta(hours=6)  # 10 AM to 4 PM

    def test_time_until_close_when_closed(self):
        """Test time_until_close returns None when market is closed."""
        hours = MARKET_HOURS[Market.US]
        # Monday at 5:00 PM ET
        dt = datetime(2024, 1, 8, 17, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert hours.time_until_close(dt) is None

    def test_utc_timezone_conversion(self):
        """Test timezone conversion from UTC."""
        hours = MARKET_HOURS[Market.US]
        # 3:00 PM UTC = 10:00 AM ET (during regular hours)
        dt = datetime(2024, 1, 8, 15, 0, 0, tzinfo=ZoneInfo("UTC"))
        assert hours.is_open(dt) is True


class TestMarketUtilities:
    """Tests for market utility functions."""

    def test_get_market_hours(self):
        """Test get_market_hours returns correct hours."""
        hours = get_market_hours(Market.US)
        assert hours.market == Market.US
        assert isinstance(hours, TradingHours)

    def test_is_market_open_function(self):
        """Test is_market_open utility function."""
        # Monday at 10:00 AM ET = 3:00 PM UK (EU market open until 4:30 PM)
        dt = datetime(2024, 1, 8, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        assert is_market_open(Market.US, dt) is True
        assert is_market_open(Market.EU, dt) is True  # 3 PM UK, open until 4:30 PM
        # Monday at 12:30 PM ET = 5:30 PM UK (after EU close)
        dt_late = datetime(2024, 1, 8, 12, 30, 0, tzinfo=ZoneInfo("America/New_York"))
        assert is_market_open(Market.EU, dt_late) is False

    def test_get_all_market_status(self):
        """Test get_all_market_status returns status for all markets."""
        # Monday at 10:00 AM ET
        dt = datetime(2024, 1, 8, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        status = get_all_market_status(dt)
        assert len(status) == len(Market)
        assert Market.US in status
        assert Market.EU in status
        assert Market.CRYPTO in status
        assert status[Market.US] is True
        assert status[Market.CRYPTO] is True


class TestMarketStatus:
    """Tests for MarketStatus dataclass."""

    def test_from_market_when_open(self):
        """Test creating MarketStatus when market is open."""
        # Monday at 10:00 AM ET
        dt = datetime(2024, 1, 8, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        status = MarketStatus.from_market(Market.US, dt)

        assert status.market == Market.US
        assert status.is_open is True
        assert status.is_extended_hours is False
        assert status.time_until_open is None
        assert status.time_until_close is not None
        assert status.timezone == "America/New_York"
        assert status.local_time == "10:00:00"

    def test_from_market_when_closed(self):
        """Test creating MarketStatus when market is closed."""
        # Monday at 8:00 AM ET
        dt = datetime(2024, 1, 8, 8, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        status = MarketStatus.from_market(Market.US, dt)

        assert status.market == Market.US
        assert status.is_open is False
        assert status.time_until_open is not None
        assert status.time_until_close is None

    def test_from_market_extended_hours(self):
        """Test creating MarketStatus during extended hours."""
        # Monday at 6:00 PM ET (after-hours)
        dt = datetime(2024, 1, 8, 18, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        status = MarketStatus.from_market(Market.US, dt)

        assert status.is_open is False
        assert status.is_extended_hours is True


class TestTickAndBarMarketField:
    """Tests for market field in Tick and Bar."""

    def test_tick_default_market(self):
        """Test Tick has default market of 'us'."""
        from axtrade.common import Tick
        tick = Tick(symbol="AAPL", price=185.0)
        assert tick.market == "us"

    def test_tick_custom_market(self):
        """Test Tick with custom market."""
        from axtrade.common import Tick
        tick = Tick(symbol="BTC-USD", price=50000.0, market="crypto")
        assert tick.market == "crypto"

    def test_tick_to_dict_includes_market(self):
        """Test Tick.to_dict includes market field."""
        from axtrade.common import Tick
        tick = Tick(symbol="AAPL", price=185.0, market="us")
        data = tick.to_dict()
        assert "market" in data
        assert data["market"] == "us"

    def test_bar_default_market(self):
        """Test Bar has default market of 'us'."""
        from datetime import datetime
        from axtrade.common import Bar
        bar = Bar(
            symbol="AAPL",
            open=185.0,
            high=186.0,
            low=184.0,
            close=185.5,
            volume=1000000,
            timestamp=datetime.now(),
        )
        assert bar.market == "us"
        assert bar.interval == "1m"

    def test_bar_custom_market(self):
        """Test Bar with custom market and interval."""
        from datetime import datetime
        from axtrade.common import Bar
        bar = Bar(
            symbol="BTC-USD",
            open=50000.0,
            high=51000.0,
            low=49000.0,
            close=50500.0,
            volume=100,
            timestamp=datetime.now(),
            interval="5m",
            market="crypto",
        )
        assert bar.market == "crypto"
        assert bar.interval == "5m"

    def test_bar_to_dict_includes_market(self):
        """Test Bar.to_dict includes market and interval fields."""
        from datetime import datetime
        from axtrade.common import Bar
        bar = Bar(
            symbol="AAPL",
            open=185.0,
            high=186.0,
            low=184.0,
            close=185.5,
            volume=1000000,
            timestamp=datetime.now(),
            interval="1m",
            market="us",
        )
        data = bar.to_dict()
        assert "market" in data
        assert data["market"] == "us"
        assert "interval" in data
        assert data["interval"] == "1m"
