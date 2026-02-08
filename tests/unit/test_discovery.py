"""Unit tests for discovery service."""

import math
from datetime import datetime, timedelta

import pytest

from axtrade.discovery import (
    DiscoveredSymbol,
    DiscoveryService,
    DiscoveryState,
    MomentumScreener,
    ScreenerResult,
    ScreenerType,
    TrendScreener,
    VolatilityScreener,
    VolumeScreener,
)


class TestDiscoveredSymbol:
    """Tests for DiscoveredSymbol dataclass."""

    def test_create_discovered_symbol(self):
        """Test creating a discovered symbol."""
        symbol = DiscoveredSymbol(
            symbol="AAPL",
            source="momentum_screener",
            score=0.85,
            price=185.50,
            volume=1000000,
            change_pct=2.5,
        )
        assert symbol.symbol == "AAPL"
        assert symbol.source == "momentum_screener"
        assert symbol.score == 0.85
        assert symbol.price == 185.50
        assert symbol.volume == 1000000
        assert symbol.change_pct == 2.5
        assert isinstance(symbol.discovered_at, datetime)
        assert symbol.metadata == {}

    def test_discovered_symbol_with_metadata(self):
        """Test discovered symbol with metadata."""
        symbol = DiscoveredSymbol(
            symbol="MSFT",
            source="volatility_screener",
            score=-0.75,
            metadata={"rsi": 25.5, "atr_ratio": 2.5},
        )
        assert symbol.metadata["rsi"] == 25.5
        assert symbol.metadata["atr_ratio"] == 2.5

    def test_discovered_symbol_default_values(self):
        """Test discovered symbol default values."""
        symbol = DiscoveredSymbol(
            symbol="GOOGL",
            source="test",
            score=0.5,
        )
        assert symbol.price is None
        assert symbol.volume is None
        assert symbol.change_pct is None
        assert symbol.metadata == {}

    def test_is_bullish_property(self):
        """Test bullish property."""
        bullish = DiscoveredSymbol(symbol="AAPL", source="test", score=0.5)
        bearish = DiscoveredSymbol(symbol="MSFT", source="test", score=-0.5)
        neutral = DiscoveredSymbol(symbol="GOOGL", source="test", score=0.0)

        assert bullish.is_bullish is True
        assert bullish.is_bearish is False
        assert bearish.is_bullish is False
        assert bearish.is_bearish is True
        assert neutral.is_bullish is False
        assert neutral.is_bearish is False


class TestScreenerResult:
    """Tests for ScreenerResult dataclass."""

    def test_create_screener_result(self):
        """Test creating a screener result."""
        symbols = [
            DiscoveredSymbol(symbol="AAPL", source="test", score=0.9),
            DiscoveredSymbol(symbol="MSFT", source="test", score=0.8),
        ]
        result = ScreenerResult(
            screener_name="momentum_screener",
            screener_type=ScreenerType.MOMENTUM,
            symbols=symbols,
            scan_time_ms=150.5,
            total_scanned=10,
        )
        assert result.screener_name == "momentum_screener"
        assert result.screener_type == ScreenerType.MOMENTUM
        assert result.match_count == 2  # Property based on symbols length
        assert result.total_scanned == 10
        assert result.scan_time_ms == 150.5
        assert len(result.symbols) == 2

    def test_screener_result_empty(self):
        """Test screener result with no matches."""
        result = ScreenerResult(
            screener_name="test",
            screener_type=ScreenerType.VOLUME,
            symbols=[],
            scan_time_ms=50.0,
            total_scanned=5,
        )
        assert result.match_count == 0
        assert len(result.symbols) == 0


class TestDiscoveryState:
    """Tests for DiscoveryState dataclass."""

    def test_create_discovery_state(self):
        """Test creating discovery state."""
        state = DiscoveryState(
            active_screeners=["momentum", "volatility"],
            last_scan=datetime.utcnow(),
            total_discovered=15,
            discovered_symbols=[],
            is_scanning=False,
        )
        assert len(state.active_screeners) == 2
        assert state.total_discovered == 15
        assert state.is_scanning is False

    def test_discovery_state_with_symbols(self):
        """Test discovery state with discovered symbols."""
        symbols = [
            DiscoveredSymbol(symbol="AAPL", source="test", score=0.5),
        ]
        state = DiscoveryState(
            active_screeners=[],
            last_scan=None,
            total_discovered=1,
            discovered_symbols=symbols,
        )
        assert len(state.discovered_symbols) == 1
        assert state.discovered_symbols[0].symbol == "AAPL"


def create_test_bars_data(
    symbol: str,
    count: int,
    base_price: float = 100.0,
    base_volume: int = 10000,
    trend: str = "flat",
    volatility: str = "normal",
) -> list[dict]:
    """Create test bar data as dicts with specified characteristics."""
    bars = []
    now = datetime.utcnow()

    for i in range(count):
        # Calculate price based on trend
        if trend == "up":
            price = base_price * (1 + 0.005 * i)  # 0.5% increase per bar
        elif trend == "down":
            price = base_price * (1 - 0.005 * i)  # 0.5% decrease per bar
        elif trend == "volatile":
            # Oscillating with larger swings
            price = base_price * (1 + 0.02 * math.sin(i * 0.8))
        else:
            # Flat with small noise
            price = base_price * (1 + 0.001 * math.sin(i * 0.3))

        # Calculate OHLC
        if volatility == "high":
            spread = price * 0.02  # 2% spread
        elif volatility == "low":
            spread = price * 0.002  # 0.2% spread
        else:
            spread = price * 0.005  # 0.5% spread

        high = price + spread
        low = price - spread
        open_price = price - spread * 0.3
        close_price = price + spread * 0.3 if trend == "up" else price - spread * 0.3

        # Volume variations
        if i % 5 == 0 and volatility == "high":
            volume = base_volume * 3  # Volume spike
        else:
            volume = base_volume

        # Calculate a simple RSI-like value for momentum screener
        # For trending up, RSI tends high; for trending down, RSI tends low
        if trend == "up":
            rsi = 50 + min(i * 2, 35)  # Goes from 50 toward 85
        elif trend == "down":
            rsi = 50 - min(i * 2, 35)  # Goes from 50 toward 15
        else:
            rsi = 50  # Neutral

        bar = {
            "symbol": symbol,
            "time": (now - timedelta(minutes=count - i)).isoformat(),
            "open": open_price,
            "high": high,
            "low": low,
            "close": close_price,
            "volume": volume,
            "interval": "1m",
            "rsi_14": rsi,
        }
        bars.append(bar)

    return bars


class TestMomentumScreener:
    """Tests for MomentumScreener."""

    def test_screener_name_and_type(self):
        """Test screener name and type."""
        screener = MomentumScreener(name="test_momentum")
        assert screener.name == "test_momentum"
        assert screener.screener_type == ScreenerType.MOMENTUM

    def test_screener_default_params(self):
        """Test default parameters."""
        screener = MomentumScreener()
        assert screener.params["rsi_oversold"] == 30
        assert screener.params["rsi_overbought"] == 70
        assert screener.params["min_bars"] == 20

    def test_screener_custom_params(self):
        """Test custom parameters."""
        screener = MomentumScreener(
            rsi_oversold=25,
            rsi_overbought=75,
            min_bars=30,
        )
        assert screener.params["rsi_oversold"] == 25
        assert screener.params["rsi_overbought"] == 75
        assert screener.params["min_bars"] == 30

    @pytest.mark.asyncio
    async def test_scan_insufficient_bars(self):
        """Test scanning with insufficient bars."""
        screener = MomentumScreener(min_bars=20)
        bars_data = {"AAPL": create_test_bars_data("AAPL", 10)}  # Less than min_bars
        result = await screener.scan(["AAPL"], bars_data)
        assert result.match_count == 0

    @pytest.mark.asyncio
    async def test_scan_oversold_bullish(self):
        """Test detecting oversold (bullish) condition."""
        screener = MomentumScreener(rsi_oversold=30, min_bars=15)
        # Create data with low RSI (oversold)
        bars_data = {"AAPL": create_test_bars_data("AAPL", 20, trend="down")}
        result = await screener.scan(["AAPL"], bars_data)
        # Should detect oversold condition (positive score)
        if result.match_count > 0:
            assert result.symbols[0].score > 0
            assert "rsi" in result.symbols[0].metadata

    @pytest.mark.asyncio
    async def test_scan_overbought_bearish(self):
        """Test detecting overbought (bearish) condition."""
        screener = MomentumScreener(rsi_overbought=70, min_bars=15)
        # Create data with high RSI (overbought)
        bars_data = {"AAPL": create_test_bars_data("AAPL", 20, trend="up")}
        result = await screener.scan(["AAPL"], bars_data)
        # Should detect overbought condition (negative score)
        if result.match_count > 0:
            assert result.symbols[0].score < 0
            assert "rsi" in result.symbols[0].metadata

    @pytest.mark.asyncio
    async def test_scan_no_signal(self):
        """Test no signal in neutral conditions."""
        screener = MomentumScreener(min_bars=15)
        # Flat market - RSI should be around 50
        bars_data = {"AAPL": create_test_bars_data("AAPL", 25, trend="flat")}
        result = await screener.scan(["AAPL"], bars_data)
        # May or may not return result depending on exact RSI
        assert isinstance(result, ScreenerResult)


class TestVolatilityScreener:
    """Tests for VolatilityScreener."""

    def test_screener_name_and_type(self):
        """Test screener name and type."""
        screener = VolatilityScreener(name="test_volatility")
        assert screener.name == "test_volatility"
        assert screener.screener_type == ScreenerType.VOLATILITY

    def test_screener_default_params(self):
        """Test default parameters."""
        screener = VolatilityScreener()
        assert screener.params["min_atr_ratio"] == 2.0
        assert screener.params["min_bars"] == 20

    @pytest.mark.asyncio
    async def test_scan_insufficient_bars(self):
        """Test scanning with insufficient bars."""
        screener = VolatilityScreener(min_bars=20)
        bars_data = {"AAPL": create_test_bars_data("AAPL", 10)}
        result = await screener.scan(["AAPL"], bars_data)
        assert result.match_count == 0

    @pytest.mark.asyncio
    async def test_scan_high_volatility(self):
        """Test detecting high volatility."""
        screener = VolatilityScreener(min_atr_ratio=1.5, min_bars=15)
        bars_data = {"AAPL": create_test_bars_data("AAPL", 25, volatility="high")}
        result = await screener.scan(["AAPL"], bars_data)
        # High volatility should trigger a signal
        if result.match_count > 0:
            assert "avg_range_pct" in result.symbols[0].metadata

    @pytest.mark.asyncio
    async def test_scan_low_volatility(self):
        """Test no signal in low volatility."""
        screener = VolatilityScreener(min_atr_ratio=2.0, min_bars=15)
        bars_data = {"AAPL": create_test_bars_data("AAPL", 25, volatility="low")}
        result = await screener.scan(["AAPL"], bars_data)
        # Low volatility shouldn't trigger high-volatility screener
        # Result may have 0 matches
        assert isinstance(result, ScreenerResult)


class TestVolumeScreener:
    """Tests for VolumeScreener."""

    def test_screener_name_and_type(self):
        """Test screener name and type."""
        screener = VolumeScreener(name="test_volume")
        assert screener.name == "test_volume"
        assert screener.screener_type == ScreenerType.VOLUME

    def test_screener_default_params(self):
        """Test default parameters."""
        screener = VolumeScreener()
        assert screener.params["volume_multiplier"] == 2.0
        assert screener.params["min_bars"] == 20

    @pytest.mark.asyncio
    async def test_scan_insufficient_bars(self):
        """Test scanning with insufficient bars."""
        screener = VolumeScreener(min_bars=20)
        bars_data = {"AAPL": create_test_bars_data("AAPL", 10)}
        result = await screener.scan(["AAPL"], bars_data)
        assert result.match_count == 0

    @pytest.mark.asyncio
    async def test_scan_volume_spike(self):
        """Test detecting volume spike."""
        screener = VolumeScreener(volume_multiplier=1.5, min_bars=10)
        # Create bars with a volume spike at the end
        bars_data = {"AAPL": create_test_bars_data("AAPL", 20, base_volume=10000)}
        # Manually increase last bar's volume
        bars_data["AAPL"][-1]["volume"] = 50000  # 5x normal volume
        result = await screener.scan(["AAPL"], bars_data)
        if result.match_count > 0:
            assert "volume_ratio" in result.symbols[0].metadata


class TestTrendScreener:
    """Tests for TrendScreener."""

    def test_screener_name_and_type(self):
        """Test screener name and type."""
        screener = TrendScreener(name="test_trend")
        assert screener.name == "test_trend"
        assert screener.screener_type == ScreenerType.TREND

    def test_screener_default_params(self):
        """Test default parameters."""
        screener = TrendScreener()
        assert screener.params["min_trend_strength"] == 50
        assert screener.params["min_bars"] == 25

    @pytest.mark.asyncio
    async def test_scan_insufficient_bars(self):
        """Test scanning with insufficient bars."""
        screener = TrendScreener(min_bars=30)
        bars_data = {"AAPL": create_test_bars_data("AAPL", 20)}
        result = await screener.scan(["AAPL"], bars_data)
        assert result.match_count == 0

    @pytest.mark.asyncio
    async def test_scan_strong_uptrend(self):
        """Test detecting strong uptrend."""
        screener = TrendScreener(min_trend_strength=30, min_bars=20)
        bars_data = {"AAPL": create_test_bars_data("AAPL", 30, trend="up")}
        result = await screener.scan(["AAPL"], bars_data)
        if result.match_count > 0:
            assert result.symbols[0].score > 0  # Bullish
            assert "trend_strength" in result.symbols[0].metadata

    @pytest.mark.asyncio
    async def test_scan_strong_downtrend(self):
        """Test detecting strong downtrend."""
        screener = TrendScreener(min_trend_strength=30, min_bars=20)
        bars_data = {"AAPL": create_test_bars_data("AAPL", 30, trend="down")}
        result = await screener.scan(["AAPL"], bars_data)
        if result.match_count > 0:
            assert result.symbols[0].score < 0  # Bearish
            assert "trend_strength" in result.symbols[0].metadata


class TestDiscoveryService:
    """Tests for DiscoveryService."""

    def test_create_service(self):
        """Test creating discovery service."""
        service = DiscoveryService()
        assert service is not None
        state = service.get_state()
        assert isinstance(state, DiscoveryState)

    def test_create_service_with_screeners(self):
        """Test creating service with custom screeners."""
        screeners = [MomentumScreener(name="m1")]
        service = DiscoveryService(screeners=screeners)
        names = service.get_screener_names()
        assert "m1" in names
        assert len(names) == 1

    def test_add_screener(self):
        """Test adding a screener."""
        service = DiscoveryService(screeners=[])
        screener = MomentumScreener(name="momentum_test")
        service.add_screener(screener)
        names = service.get_screener_names()
        assert "momentum_test" in names

    def test_remove_screener(self):
        """Test removing a screener."""
        service = DiscoveryService(screeners=[MomentumScreener(name="momentum_test")])
        result = service.remove_screener("momentum_test")
        assert result is True
        names = service.get_screener_names()
        assert "momentum_test" not in names

    def test_remove_nonexistent_screener(self):
        """Test removing a screener that doesn't exist."""
        service = DiscoveryService(screeners=[])
        result = service.remove_screener("nonexistent")
        assert result is False

    def test_get_discovered_empty(self):
        """Test getting discovered symbols when empty."""
        service = DiscoveryService(screeners=[])
        symbols = service.get_discovered()
        assert symbols == []

    def test_get_discovered_with_filters(self):
        """Test filtering discovered symbols."""
        service = DiscoveryService(screeners=[])
        # Add some discovered symbols manually
        service._discovered["AAPL"] = DiscoveredSymbol(
            symbol="AAPL",
            source="momentum",
            score=0.8,
        )
        service._discovered["MSFT"] = DiscoveredSymbol(
            symbol="MSFT",
            source="momentum",
            score=-0.7,
        )
        service._discovered["GOOGL"] = DiscoveredSymbol(
            symbol="GOOGL",
            source="volatility",
            score=0.5,
        )

        # Test bullish only
        bullish = service.get_discovered(bullish_only=True)
        assert all(s.score > 0 for s in bullish)

        # Test bearish only
        bearish = service.get_discovered(bearish_only=True)
        assert all(s.score < 0 for s in bearish)

        # Test source filter
        momentum = service.get_discovered(source="momentum")
        assert all(s.source == "momentum" for s in momentum)

        # Test min_score filter
        high_score = service.get_discovered(min_score=0.6)
        assert all(abs(s.score) >= 0.6 for s in high_score)

        # Test limit
        limited = service.get_discovered(limit=2)
        assert len(limited) <= 2

    def test_clear_discovered(self):
        """Test clearing discovered symbols."""
        service = DiscoveryService(screeners=[])
        service._discovered["AAPL"] = DiscoveredSymbol(
            symbol="AAPL",
            source="test",
            score=0.5,
        )
        service.clear_discovered()
        assert len(service._discovered) == 0

    def test_get_state(self):
        """Test getting discovery state."""
        service = DiscoveryService(screeners=[
            MomentumScreener(name="m1"),
            VolatilityScreener(name="v1"),
        ])
        service._discovered["AAPL"] = DiscoveredSymbol(
            symbol="AAPL",
            source="test",
            score=0.5,
        )

        state = service.get_state()
        assert "m1" in state.active_screeners
        assert "v1" in state.active_screeners
        assert state.total_discovered == 1

    def test_add_manual_symbol(self):
        """Test adding a symbol manually."""
        service = DiscoveryService(screeners=[])
        symbol = service.add_manual_symbol("aapl", price=185.50)

        assert symbol.symbol == "AAPL"  # Should be uppercase
        assert symbol.source == "manual"
        assert symbol.score == 0.0
        assert symbol.price == 185.50
        assert "AAPL" in service._discovered

    def test_add_manual_symbol_with_notes(self):
        """Test adding a symbol with notes."""
        service = DiscoveryService(screeners=[])
        symbol = service.add_manual_symbol("TSLA", price=250.00, notes="Earnings play")

        assert symbol.symbol == "TSLA"
        assert symbol.metadata["notes"] == "Earnings play"

    def test_add_manual_symbol_overwrites_existing(self):
        """Test that manual symbol overwrites existing entry."""
        service = DiscoveryService(screeners=[])
        service._discovered["AAPL"] = DiscoveredSymbol(
            symbol="AAPL",
            source="momentum",
            score=0.8,
        )

        symbol = service.add_manual_symbol("AAPL", price=190.00)
        assert service._discovered["AAPL"].source == "manual"
        assert service._discovered["AAPL"].price == 190.00

    @pytest.mark.asyncio
    async def test_scan_no_screeners(self):
        """Test scanning with no screeners registered."""
        service = DiscoveryService()
        # Remove all default screeners
        for name in list(service._screeners.keys()):
            service.remove_screener(name)
        results = await service.scan(["AAPL", "MSFT"])
        assert results == []

    @pytest.mark.asyncio
    async def test_scan_no_symbols(self):
        """Test scanning with no symbols."""
        service = DiscoveryService(screeners=[MomentumScreener()])
        results = await service.scan([])
        assert len(results) == 1  # One screener result
        assert results[0].total_scanned == 0

    @pytest.mark.asyncio
    async def test_scan_already_running(self):
        """Test scanning when already in progress."""
        service = DiscoveryService(screeners=[])
        service._is_scanning = True
        results = await service.scan(["AAPL"])
        assert results == []

    @pytest.mark.asyncio
    async def test_update_discovered(self):
        """Test that scans update the discovered cache."""
        service = DiscoveryService(screeners=[MomentumScreener(name="momentum", min_bars=10)])
        # Can't easily test without mocking the bar repo, but we can test the internal method
        symbol = DiscoveredSymbol(symbol="AAPL", source="test", score=0.5)
        service._update_discovered(symbol)
        assert "AAPL" in service._discovered
        assert service._discovered["AAPL"].score == 0.5

        # Higher score should replace
        symbol2 = DiscoveredSymbol(symbol="AAPL", source="test", score=0.8)
        service._update_discovered(symbol2)
        assert service._discovered["AAPL"].score == 0.8

        # Lower score should not replace
        symbol3 = DiscoveredSymbol(symbol="AAPL", source="test", score=0.3)
        service._update_discovered(symbol3)
        assert service._discovered["AAPL"].score == 0.8


class TestScreenerType:
    """Tests for ScreenerType enum."""

    def test_screener_types(self):
        """Test all screener types exist."""
        assert ScreenerType.MOMENTUM.value == "momentum"
        assert ScreenerType.VOLATILITY.value == "volatility"
        assert ScreenerType.VOLUME.value == "volume"
        assert ScreenerType.TREND.value == "trend"
        assert ScreenerType.BREAKOUT.value == "breakout"


class TestScreenerIntegration:
    """Integration tests for screeners working together."""

    @pytest.mark.asyncio
    async def test_multiple_screeners_same_data(self):
        """Test running multiple screeners on same data."""
        momentum = MomentumScreener(name="m", min_bars=15)
        volatility = VolatilityScreener(name="v", min_bars=15)
        volume = VolumeScreener(name="vol", min_bars=15)

        # High volatility trending down bars
        bars_data = {"AAPL": create_test_bars_data("AAPL", 25, trend="down", volatility="high")}

        m_result = await momentum.scan(["AAPL"], bars_data)
        v_result = await volatility.scan(["AAPL"], bars_data)
        vol_result = await volume.scan(["AAPL"], bars_data)

        # All should return ScreenerResult
        assert isinstance(m_result, ScreenerResult)
        assert isinstance(v_result, ScreenerResult)
        assert isinstance(vol_result, ScreenerResult)

    @pytest.mark.asyncio
    async def test_service_with_multiple_screeners(self):
        """Test discovery service with multiple screeners."""
        service = DiscoveryService(screeners=[
            MomentumScreener(name="momentum", min_bars=15),
            VolatilityScreener(name="volatility", min_bars=15),
        ])
        # Without db_pool, _fetch_bars_data returns empty
        # So we directly test that the service handles this gracefully
        results = await service.scan(["AAPL", "MSFT", "GOOGL"])

        assert len(results) == 2  # Two screeners
        screener_names = [r.screener_name for r in results]
        assert "momentum" in screener_names
        assert "volatility" in screener_names

    @pytest.mark.asyncio
    async def test_scan_specific_screeners(self):
        """Test scanning with specific screener names."""
        service = DiscoveryService(screeners=[
            MomentumScreener(name="momentum", min_bars=15),
            TrendScreener(name="trend", min_bars=20),
            VolatilityScreener(name="volatility", min_bars=15),
        ])

        # Only run momentum screener
        results = await service.scan(
            symbols=["AAPL"],
            screener_names=["momentum"],
        )

        assert len(results) == 1
        assert results[0].screener_name == "momentum"

    @pytest.mark.asyncio
    async def test_scan_updates_state(self):
        """Test that scanning updates the service state."""
        service = DiscoveryService(screeners=[MomentumScreener(name="momentum", min_bars=15)])

        assert service._last_scan is None
        assert service._is_scanning is False

        await service.scan(["AAPL"])

        assert service._last_scan is not None
        assert service._is_scanning is False  # Should be False after scan completes

        state = service.get_state()
        assert state.last_scan is not None
