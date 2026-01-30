"""Unit tests for position sizer."""

from decimal import Decimal

import pytest

from axtrade.oms import PositionSizer, SizingMethod, SizingResult


class TestPositionSizer:
    """Tests for PositionSizer class."""

    @pytest.fixture
    def sizer(self) -> PositionSizer:
        return PositionSizer(
            account_equity=Decimal("100000"),
            risk_per_trade=0.02,  # 2%
            max_position_pct=0.10,  # 10%
            kelly_fraction=0.25,
            atr_multiplier=2.0,
        )

    def test_initialization(self, sizer: PositionSizer) -> None:
        assert sizer.account_equity == Decimal("100000")
        assert sizer.risk_per_trade == 0.02
        assert sizer.max_position_pct == 0.10

    def test_update_equity(self, sizer: PositionSizer) -> None:
        sizer.update_equity(Decimal("150000"))
        assert sizer.account_equity == Decimal("150000")


class TestFixedSize:
    """Tests for fixed_size method."""

    @pytest.fixture
    def sizer(self) -> PositionSizer:
        return PositionSizer(
            account_equity=Decimal("100000"),
            max_position_pct=0.10,
        )

    def test_fixed_size_under_limit(self, sizer: PositionSizer) -> None:
        result = sizer.fixed_size(shares=100, price=Decimal("50.00"))

        assert result.shares == 100
        assert result.dollar_amount == Decimal("5000.00")
        assert result.method == SizingMethod.FIXED

    def test_fixed_size_over_limit(self, sizer: PositionSizer) -> None:
        # 10% of 100k = 10k max, at $200/share = 50 shares max
        result = sizer.fixed_size(shares=100, price=Decimal("200.00"))

        assert result.shares == 50  # Limited
        assert result.dollar_amount == Decimal("10000.00")

    def test_fixed_size_with_stop_loss(self, sizer: PositionSizer) -> None:
        result = sizer.fixed_size(
            shares=100,
            price=Decimal("100.00"),
            stop_loss=Decimal("95.00"),
        )

        assert result.shares == 100
        # Risk = 100 shares * $5 stop distance
        assert result.risk_amount == Decimal("500.00")


class TestRiskPctSize:
    """Tests for risk_pct_size method."""

    @pytest.fixture
    def sizer(self) -> PositionSizer:
        return PositionSizer(
            account_equity=Decimal("100000"),
            risk_per_trade=0.02,  # 2% = $2000
            max_position_pct=0.50,  # 50% to allow testing without hitting limit
        )

    def test_risk_pct_size_normal(self, sizer: PositionSizer) -> None:
        # Risk $2000, stop distance $5, so 400 shares
        result = sizer.risk_pct_size(
            price=Decimal("100.00"),
            stop_loss=Decimal("95.00"),
        )

        assert result.shares == 400
        assert result.method == SizingMethod.RISK_PCT
        # Actual risk = 400 * $5 = $2000
        assert result.risk_amount == Decimal("2000.00")

    def test_risk_pct_size_limited_by_max_position(self, sizer: PositionSizer) -> None:
        # Risk $2000, stop distance $1, so would be 2000 shares
        # But max position is 50% = $50k = 500 shares at $100
        result = sizer.risk_pct_size(
            price=Decimal("100.00"),
            stop_loss=Decimal("99.00"),
        )

        assert result.shares == 500  # Limited by max position
        assert result.dollar_amount == Decimal("50000.00")

    def test_risk_pct_size_zero_stop_distance(self, sizer: PositionSizer) -> None:
        result = sizer.risk_pct_size(
            price=Decimal("100.00"),
            stop_loss=Decimal("100.00"),  # Same as price
        )

        assert result.shares == 0
        assert "zero" in result.notes.lower()

    def test_risk_pct_size_wide_stop(self, sizer: PositionSizer) -> None:
        # Risk $2000, stop distance $20, so 100 shares
        result = sizer.risk_pct_size(
            price=Decimal("100.00"),
            stop_loss=Decimal("80.00"),
        )

        assert result.shares == 100
        assert result.risk_amount == Decimal("2000.00")


class TestKellySize:
    """Tests for kelly_size method."""

    @pytest.fixture
    def sizer(self) -> PositionSizer:
        return PositionSizer(
            account_equity=Decimal("100000"),
            kelly_fraction=0.25,  # Quarter Kelly
            max_position_pct=0.20,
        )

    def test_kelly_size_positive_edge(self, sizer: PositionSizer) -> None:
        # Win rate 60%, reward/risk 1.5
        # Kelly = 0.6 - (0.4 / 1.5) = 0.6 - 0.267 = 0.333
        # Quarter Kelly = 0.083
        result = sizer.kelly_size(
            price=Decimal("100.00"),
            win_rate=0.60,
            avg_win=Decimal("150.00"),
            avg_loss=Decimal("100.00"),
        )

        assert result.shares > 0
        assert result.method == SizingMethod.KELLY
        # Should be around 8.3% of equity / $100 = 83 shares
        assert result.shares == 83

    def test_kelly_size_negative_edge(self, sizer: PositionSizer) -> None:
        # Win rate 30%, reward/risk 1.0
        # Kelly = 0.3 - (0.7 / 1.0) = 0.3 - 0.7 = -0.4
        result = sizer.kelly_size(
            price=Decimal("100.00"),
            win_rate=0.30,
            avg_win=Decimal("100.00"),
            avg_loss=Decimal("100.00"),
        )

        assert result.shares == 0
        assert "negative" in result.notes.lower()

    def test_kelly_size_invalid_inputs(self, sizer: PositionSizer) -> None:
        # Zero avg loss
        result = sizer.kelly_size(
            price=Decimal("100.00"),
            win_rate=0.50,
            avg_win=Decimal("100.00"),
            avg_loss=Decimal("0"),
        )
        assert result.shares == 0

        # Win rate out of range
        result = sizer.kelly_size(
            price=Decimal("100.00"),
            win_rate=1.5,
            avg_win=Decimal("100.00"),
            avg_loss=Decimal("100.00"),
        )
        assert result.shares == 0


class TestATRSize:
    """Tests for atr_size method."""

    @pytest.fixture
    def sizer(self) -> PositionSizer:
        return PositionSizer(
            account_equity=Decimal("100000"),
            risk_per_trade=0.02,  # 2% = $2000
            atr_multiplier=2.0,
            max_position_pct=0.50,  # 50% to allow testing without hitting limit
        )

    def test_atr_size_normal(self, sizer: PositionSizer) -> None:
        # ATR = 2.5, multiplier = 2.0, stop = $5
        # Risk $2000 / $5 = 400 shares
        result = sizer.atr_size(
            price=Decimal("100.00"),
            atr=2.5,
        )

        assert result.shares == 400
        assert result.method == SizingMethod.ATR
        assert result.risk_amount == Decimal("2000.00")

    def test_atr_size_high_volatility(self, sizer: PositionSizer) -> None:
        # ATR = 10.0, multiplier = 2.0, stop = $20
        # Risk $2000 / $20 = 100 shares
        result = sizer.atr_size(
            price=Decimal("100.00"),
            atr=10.0,
        )

        assert result.shares == 100
        assert result.risk_amount == Decimal("2000.00")

    def test_atr_size_zero_atr(self, sizer: PositionSizer) -> None:
        result = sizer.atr_size(
            price=Decimal("100.00"),
            atr=0.0,
        )

        assert result.shares == 0


class TestCalculateDispatch:
    """Tests for calculate dispatch method."""

    @pytest.fixture
    def sizer(self) -> PositionSizer:
        return PositionSizer(
            account_equity=Decimal("100000"),
            risk_per_trade=0.02,
            max_position_pct=0.10,
        )

    def test_dispatch_fixed(self, sizer: PositionSizer) -> None:
        result = sizer.calculate(
            method="fixed",
            price=Decimal("100.00"),
            fixed_shares=50,
        )
        assert result.method == SizingMethod.FIXED
        assert result.shares == 50

    def test_dispatch_risk_pct(self, sizer: PositionSizer) -> None:
        result = sizer.calculate(
            method=SizingMethod.RISK_PCT,
            price=Decimal("100.00"),
            stop_loss=Decimal("95.00"),
        )
        assert result.method == SizingMethod.RISK_PCT

    def test_dispatch_missing_params(self, sizer: PositionSizer) -> None:
        with pytest.raises(ValueError, match="stop_loss required"):
            sizer.calculate(
                method=SizingMethod.RISK_PCT,
                price=Decimal("100.00"),
            )

        with pytest.raises(ValueError, match="atr required"):
            sizer.calculate(
                method=SizingMethod.ATR,
                price=Decimal("100.00"),
            )
