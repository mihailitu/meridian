"""Portfolio-level risk management and metrics."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


@dataclass
class PositionRisk:
    """Risk information for a single position."""

    symbol: str
    shares: int
    entry_price: Decimal
    current_price: Decimal
    stop_loss: Optional[Decimal] = None
    sector: str = "unknown"

    @property
    def market_value(self) -> Decimal:
        """Current market value of position."""
        return Decimal(self.shares) * self.current_price

    @property
    def cost_basis(self) -> Decimal:
        """Original cost of position."""
        return Decimal(self.shares) * self.entry_price

    @property
    def unrealized_pnl(self) -> Decimal:
        """Unrealized profit/loss."""
        return self.market_value - self.cost_basis

    @property
    def risk_amount(self) -> Decimal:
        """Dollar amount at risk if stop loss is hit."""
        if self.stop_loss is None:
            # If no stop, assume full position is at risk
            return self.market_value
        return Decimal(self.shares) * abs(self.current_price - self.stop_loss)


@dataclass
class PortfolioMetrics:
    """Aggregate portfolio risk metrics."""

    account_equity: Decimal
    total_exposure: Decimal  # Total $ in positions
    total_risk: Decimal  # Total $ at risk
    portfolio_heat: float  # risk / equity
    largest_position_pct: float  # Largest position as % of equity
    position_count: int
    sector_exposures: dict[str, Decimal] = field(default_factory=dict)


class PortfolioRisk:
    """Track and manage portfolio-level risk.

    Monitors aggregate exposure, concentration, and risk limits
    to prevent excessive portfolio-wide risk.
    """

    def __init__(
        self,
        account_equity: Decimal,
        max_portfolio_heat: float = 0.10,
        max_single_position: float = 0.15,
        max_sector_exposure: float = 0.30,
        max_positions: int = 20,
    ):
        """Initialize portfolio risk manager.

        Args:
            account_equity: Total account value
            max_portfolio_heat: Max total risk as % of equity (0.10 = 10%)
            max_single_position: Max single position as % of equity
            max_sector_exposure: Max exposure per sector as % of equity
            max_positions: Maximum number of open positions
        """
        self.account_equity = account_equity
        self.max_portfolio_heat = max_portfolio_heat
        self.max_single_position = max_single_position
        self.max_sector_exposure = max_sector_exposure
        self.max_positions = max_positions

        self._positions: dict[str, PositionRisk] = {}

    def update_equity(self, equity: Decimal) -> None:
        """Update account equity."""
        self.account_equity = equity

    def add_position(self, position: PositionRisk) -> None:
        """Add or update a position.

        Args:
            position: Position risk information
        """
        self._positions[position.symbol] = position

    def remove_position(self, symbol: str) -> None:
        """Remove a closed position.

        Args:
            symbol: Symbol to remove
        """
        self._positions.pop(symbol, None)

    def update_price(self, symbol: str, price: Decimal) -> None:
        """Update current price for a position.

        Args:
            symbol: Symbol to update
            price: New current price
        """
        if symbol in self._positions:
            self._positions[symbol].current_price = price

    def update_stop(self, symbol: str, stop_loss: Decimal) -> None:
        """Update stop loss for a position.

        Args:
            symbol: Symbol to update
            stop_loss: New stop loss price
        """
        if symbol in self._positions:
            self._positions[symbol].stop_loss = stop_loss

    def get_position(self, symbol: str) -> Optional[PositionRisk]:
        """Get position risk info.

        Args:
            symbol: Symbol to look up

        Returns:
            PositionRisk if exists, None otherwise
        """
        return self._positions.get(symbol)

    def total_exposure(self) -> Decimal:
        """Total market value of all positions."""
        return sum(p.market_value for p in self._positions.values())

    def total_risk(self) -> Decimal:
        """Total dollar amount at risk across all positions."""
        return sum(p.risk_amount for p in self._positions.values())

    def portfolio_heat(self) -> float:
        """Portfolio heat (total risk / equity)."""
        if self.account_equity == 0:
            return 0.0
        return float(self.total_risk() / self.account_equity)

    def get_metrics(self) -> PortfolioMetrics:
        """Calculate current portfolio metrics.

        Returns:
            PortfolioMetrics with aggregate data
        """
        if not self._positions:
            return PortfolioMetrics(
                account_equity=self.account_equity,
                total_exposure=Decimal("0"),
                total_risk=Decimal("0"),
                portfolio_heat=0.0,
                largest_position_pct=0.0,
                position_count=0,
                sector_exposures={},
            )

        total_exposure = self.total_exposure()
        total_risk = self.total_risk()

        # Largest position
        largest = max(p.market_value for p in self._positions.values())
        largest_pct = float(largest / self.account_equity) if self.account_equity else 0

        # Sector exposures
        sector_exposures: dict[str, Decimal] = {}
        for pos in self._positions.values():
            sector = pos.sector
            sector_exposures[sector] = sector_exposures.get(sector, Decimal("0")) + pos.market_value

        return PortfolioMetrics(
            account_equity=self.account_equity,
            total_exposure=total_exposure,
            total_risk=total_risk,
            portfolio_heat=self.portfolio_heat(),
            largest_position_pct=largest_pct,
            position_count=len(self._positions),
            sector_exposures=sector_exposures,
        )

    def can_add_position(self) -> bool:
        """Check if a new position can be added (count limit).

        Returns:
            True if under max position count
        """
        return len(self._positions) < self.max_positions

    def can_add_risk(self, additional_risk: Decimal) -> bool:
        """Check if adding risk would exceed portfolio heat limit.

        Args:
            additional_risk: Dollar amount of risk to add

        Returns:
            True if adding risk stays within limits
        """
        if self.account_equity == 0:
            return False
        new_heat = float((self.total_risk() + additional_risk) / self.account_equity)
        return new_heat <= self.max_portfolio_heat

    def can_add_exposure(self, additional_exposure: Decimal, sector: str = "unknown") -> bool:
        """Check if adding exposure would exceed limits.

        Checks both single position limit and sector limit.

        Args:
            additional_exposure: Dollar amount of exposure to add
            sector: Sector of the new position

        Returns:
            True if adding exposure stays within limits
        """
        if self.account_equity == 0:
            return False

        # Check single position limit
        position_pct = float(additional_exposure / self.account_equity)
        if position_pct > self.max_single_position:
            return False

        # Check sector limit
        current_sector = sum(
            p.market_value for p in self._positions.values() if p.sector == sector
        )
        new_sector_pct = float((current_sector + additional_exposure) / self.account_equity)
        if new_sector_pct > self.max_sector_exposure:
            return False

        return True

    def get_available_risk(self) -> Decimal:
        """Get remaining risk capacity before hitting heat limit.

        Returns:
            Dollar amount of risk still available
        """
        max_risk = self.account_equity * Decimal(str(self.max_portfolio_heat))
        current_risk = self.total_risk()
        return max(Decimal("0"), max_risk - current_risk)

    def get_position_limit(self, price: Decimal, sector: str = "unknown") -> int:
        """Get maximum shares allowed for a new position.

        Considers single position limit and sector limits.

        Args:
            price: Price per share
            sector: Sector of the position

        Returns:
            Maximum number of shares allowed
        """
        if price == 0:
            return 0

        # Single position limit
        max_single = self.account_equity * Decimal(str(self.max_single_position))
        max_shares_single = int(max_single / price)

        # Sector limit
        current_sector = sum(
            p.market_value for p in self._positions.values() if p.sector == sector
        )
        available_sector = (
            self.account_equity * Decimal(str(self.max_sector_exposure)) - current_sector
        )
        max_shares_sector = int(available_sector / price) if available_sector > 0 else 0

        return min(max_shares_single, max_shares_sector)

    def check_limits(
        self,
        shares: int,
        price: Decimal,
        risk_per_share: Decimal,
        sector: str = "unknown",
    ) -> tuple[bool, str]:
        """Comprehensive limit check for a proposed position.

        Args:
            shares: Number of shares
            price: Price per share
            risk_per_share: Risk amount per share (e.g., stop distance)
            sector: Sector of the position

        Returns:
            Tuple of (passes_all_checks, reason_if_failed)
        """
        exposure = Decimal(shares) * price
        risk = Decimal(shares) * risk_per_share

        # Position count
        if not self.can_add_position():
            return False, f"Max positions ({self.max_positions}) reached"

        # Portfolio heat
        if not self.can_add_risk(risk):
            current = self.portfolio_heat() * 100
            limit = self.max_portfolio_heat * 100
            return False, f"Portfolio heat {current:.1f}% would exceed {limit:.1f}%"

        # Single position size
        position_pct = float(exposure / self.account_equity) * 100
        if position_pct > self.max_single_position * 100:
            return False, f"Position size {position_pct:.1f}% exceeds {self.max_single_position*100:.0f}%"

        # Sector concentration
        if not self.can_add_exposure(exposure, sector):
            return False, f"Sector exposure for {sector} would exceed limit"

        return True, "OK"
