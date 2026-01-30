"""Unit tests for portfolio risk management."""

from decimal import Decimal

import pytest

from axtrade.oms import PortfolioMetrics, PortfolioRisk, PositionRisk


class TestPositionRisk:
    """Tests for PositionRisk dataclass."""

    def test_market_value(self) -> None:
        pos = PositionRisk(
            symbol="AAPL",
            shares=100,
            entry_price=Decimal("180.00"),
            current_price=Decimal("185.00"),
        )
        assert pos.market_value == Decimal("18500.00")

    def test_cost_basis(self) -> None:
        pos = PositionRisk(
            symbol="AAPL",
            shares=100,
            entry_price=Decimal("180.00"),
            current_price=Decimal("185.00"),
        )
        assert pos.cost_basis == Decimal("18000.00")

    def test_unrealized_pnl(self) -> None:
        pos = PositionRisk(
            symbol="AAPL",
            shares=100,
            entry_price=Decimal("180.00"),
            current_price=Decimal("185.00"),
        )
        assert pos.unrealized_pnl == Decimal("500.00")

    def test_risk_amount_with_stop(self) -> None:
        pos = PositionRisk(
            symbol="AAPL",
            shares=100,
            entry_price=Decimal("180.00"),
            current_price=Decimal("185.00"),
            stop_loss=Decimal("175.00"),
        )
        # Risk = 100 * |185 - 175| = 1000
        assert pos.risk_amount == Decimal("1000.00")

    def test_risk_amount_without_stop(self) -> None:
        pos = PositionRisk(
            symbol="AAPL",
            shares=100,
            entry_price=Decimal("180.00"),
            current_price=Decimal("185.00"),
        )
        # Without stop, full position is at risk
        assert pos.risk_amount == Decimal("18500.00")


class TestPortfolioRisk:
    """Tests for PortfolioRisk class."""

    @pytest.fixture
    def portfolio(self) -> PortfolioRisk:
        return PortfolioRisk(
            account_equity=Decimal("100000"),
            max_portfolio_heat=0.10,  # 10%
            max_single_position=0.15,  # 15%
            max_sector_exposure=0.30,  # 30%
            max_positions=10,
        )

    def test_initialization(self, portfolio: PortfolioRisk) -> None:
        assert portfolio.account_equity == Decimal("100000")
        assert portfolio.max_portfolio_heat == 0.10

    def test_add_and_remove_position(self, portfolio: PortfolioRisk) -> None:
        pos = PositionRisk(
            symbol="AAPL",
            shares=100,
            entry_price=Decimal("180.00"),
            current_price=Decimal("185.00"),
            stop_loss=Decimal("175.00"),
        )
        portfolio.add_position(pos)
        assert portfolio.get_position("AAPL") is not None

        portfolio.remove_position("AAPL")
        assert portfolio.get_position("AAPL") is None

    def test_update_price(self, portfolio: PortfolioRisk) -> None:
        pos = PositionRisk(
            symbol="AAPL",
            shares=100,
            entry_price=Decimal("180.00"),
            current_price=Decimal("185.00"),
        )
        portfolio.add_position(pos)

        portfolio.update_price("AAPL", Decimal("190.00"))
        assert portfolio.get_position("AAPL").current_price == Decimal("190.00")

    def test_total_exposure(self, portfolio: PortfolioRisk) -> None:
        portfolio.add_position(
            PositionRisk(
                symbol="AAPL",
                shares=100,
                entry_price=Decimal("100.00"),
                current_price=Decimal("100.00"),
            )
        )
        portfolio.add_position(
            PositionRisk(
                symbol="MSFT",
                shares=50,
                entry_price=Decimal("200.00"),
                current_price=Decimal("200.00"),
            )
        )

        # 100 * 100 + 50 * 200 = 10000 + 10000 = 20000
        assert portfolio.total_exposure() == Decimal("20000.00")

    def test_total_risk(self, portfolio: PortfolioRisk) -> None:
        portfolio.add_position(
            PositionRisk(
                symbol="AAPL",
                shares=100,
                entry_price=Decimal("100.00"),
                current_price=Decimal("100.00"),
                stop_loss=Decimal("95.00"),
            )
        )
        portfolio.add_position(
            PositionRisk(
                symbol="MSFT",
                shares=50,
                entry_price=Decimal("200.00"),
                current_price=Decimal("200.00"),
                stop_loss=Decimal("190.00"),
            )
        )

        # AAPL: 100 * 5 = 500, MSFT: 50 * 10 = 500
        assert portfolio.total_risk() == Decimal("1000.00")

    def test_portfolio_heat(self, portfolio: PortfolioRisk) -> None:
        portfolio.add_position(
            PositionRisk(
                symbol="AAPL",
                shares=100,
                entry_price=Decimal("100.00"),
                current_price=Decimal("100.00"),
                stop_loss=Decimal("95.00"),
            )
        )

        # Risk = 500, Equity = 100000, Heat = 0.5%
        assert portfolio.portfolio_heat() == pytest.approx(0.005, rel=0.01)


class TestPortfolioMetrics:
    """Tests for get_metrics method."""

    @pytest.fixture
    def portfolio(self) -> PortfolioRisk:
        return PortfolioRisk(
            account_equity=Decimal("100000"),
            max_portfolio_heat=0.10,
        )

    def test_empty_metrics(self, portfolio: PortfolioRisk) -> None:
        metrics = portfolio.get_metrics()

        assert metrics.total_exposure == Decimal("0")
        assert metrics.total_risk == Decimal("0")
        assert metrics.portfolio_heat == 0.0
        assert metrics.position_count == 0

    def test_metrics_with_positions(self, portfolio: PortfolioRisk) -> None:
        portfolio.add_position(
            PositionRisk(
                symbol="AAPL",
                shares=100,
                entry_price=Decimal("100.00"),
                current_price=Decimal("100.00"),
                stop_loss=Decimal("95.00"),
                sector="tech",
            )
        )
        portfolio.add_position(
            PositionRisk(
                symbol="MSFT",
                shares=50,
                entry_price=Decimal("200.00"),
                current_price=Decimal("200.00"),
                stop_loss=Decimal("190.00"),
                sector="tech",
            )
        )

        metrics = portfolio.get_metrics()

        assert metrics.total_exposure == Decimal("20000.00")
        assert metrics.total_risk == Decimal("1000.00")
        assert metrics.position_count == 2
        assert "tech" in metrics.sector_exposures
        assert metrics.sector_exposures["tech"] == Decimal("20000.00")


class TestPortfolioLimits:
    """Tests for limit checking methods."""

    @pytest.fixture
    def portfolio(self) -> PortfolioRisk:
        return PortfolioRisk(
            account_equity=Decimal("100000"),
            max_portfolio_heat=0.10,  # 10% = $10k risk max
            max_single_position=0.15,  # 15% = $15k max
            max_sector_exposure=0.30,  # 30% = $30k max per sector
            max_positions=5,
        )

    def test_can_add_position_under_limit(self, portfolio: PortfolioRisk) -> None:
        assert portfolio.can_add_position() is True

    def test_can_add_position_at_limit(self, portfolio: PortfolioRisk) -> None:
        for i in range(5):
            portfolio.add_position(
                PositionRisk(
                    symbol=f"SYM{i}",
                    shares=10,
                    entry_price=Decimal("100.00"),
                    current_price=Decimal("100.00"),
                )
            )
        assert portfolio.can_add_position() is False

    def test_can_add_risk_under_limit(self, portfolio: PortfolioRisk) -> None:
        # Max risk is 10% = $10,000
        assert portfolio.can_add_risk(Decimal("5000")) is True
        assert portfolio.can_add_risk(Decimal("10000")) is True
        assert portfolio.can_add_risk(Decimal("10001")) is False

    def test_can_add_risk_with_existing(self, portfolio: PortfolioRisk) -> None:
        # Add $5k risk
        portfolio.add_position(
            PositionRisk(
                symbol="AAPL",
                shares=100,
                entry_price=Decimal("100.00"),
                current_price=Decimal("100.00"),
                stop_loss=Decimal("50.00"),  # $50 risk per share
            )
        )

        # Now can add up to $5k more
        assert portfolio.can_add_risk(Decimal("5000")) is True
        assert portfolio.can_add_risk(Decimal("5001")) is False

    def test_can_add_exposure_single_position_limit(
        self, portfolio: PortfolioRisk
    ) -> None:
        # Max single position is 15% = $15k
        assert portfolio.can_add_exposure(Decimal("15000")) is True
        assert portfolio.can_add_exposure(Decimal("15001")) is False

    def test_can_add_exposure_sector_limit(self, portfolio: PortfolioRisk) -> None:
        # Add $20k to tech sector
        portfolio.add_position(
            PositionRisk(
                symbol="AAPL",
                shares=200,
                entry_price=Decimal("100.00"),
                current_price=Decimal("100.00"),
                sector="tech",
            )
        )

        # Max sector is 30% = $30k, so $10k more allowed
        assert portfolio.can_add_exposure(Decimal("10000"), sector="tech") is True
        assert portfolio.can_add_exposure(Decimal("10001"), sector="tech") is False

        # Different sector is fine
        assert portfolio.can_add_exposure(Decimal("15000"), sector="finance") is True

    def test_get_available_risk(self, portfolio: PortfolioRisk) -> None:
        assert portfolio.get_available_risk() == Decimal("10000")

        portfolio.add_position(
            PositionRisk(
                symbol="AAPL",
                shares=100,
                entry_price=Decimal("100.00"),
                current_price=Decimal("100.00"),
                stop_loss=Decimal("60.00"),  # $40 risk = $4k total
            )
        )

        assert portfolio.get_available_risk() == Decimal("6000")

    def test_get_position_limit(self, portfolio: PortfolioRisk) -> None:
        # Max single = 15% = $15k, at $100/share = 150 shares
        assert portfolio.get_position_limit(Decimal("100.00")) == 150

    def test_check_limits_passes(self, portfolio: PortfolioRisk) -> None:
        passed, reason = portfolio.check_limits(
            shares=100,
            price=Decimal("100.00"),
            risk_per_share=Decimal("5.00"),  # $500 total risk
        )
        assert passed is True
        assert reason == "OK"

    def test_check_limits_position_count(self, portfolio: PortfolioRisk) -> None:
        for i in range(5):
            portfolio.add_position(
                PositionRisk(
                    symbol=f"SYM{i}",
                    shares=10,
                    entry_price=Decimal("100.00"),
                    current_price=Decimal("100.00"),
                )
            )

        passed, reason = portfolio.check_limits(
            shares=100,
            price=Decimal("100.00"),
            risk_per_share=Decimal("5.00"),
        )
        assert passed is False
        assert "max positions" in reason.lower()

    def test_check_limits_portfolio_heat(self, portfolio: PortfolioRisk) -> None:
        passed, reason = portfolio.check_limits(
            shares=100,
            price=Decimal("100.00"),
            risk_per_share=Decimal("110.00"),  # $11k risk > 10% limit
        )
        assert passed is False
        assert "heat" in reason.lower()

    def test_check_limits_position_size(self, portfolio: PortfolioRisk) -> None:
        passed, reason = portfolio.check_limits(
            shares=200,
            price=Decimal("100.00"),  # $20k > 15% limit
            risk_per_share=Decimal("1.00"),
        )
        assert passed is False
        assert "position size" in reason.lower()
