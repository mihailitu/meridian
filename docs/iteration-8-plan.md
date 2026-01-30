# Iteration 8: Advanced Risk Management

## Goal
Implement sophisticated position sizing and portfolio-level risk management including equity-based sizing, Kelly criterion, ATR-based volatility adjustment, and portfolio metrics.

## Definition of Done
```python
# Position sizer calculates optimal size based on multiple methods
sizer = PositionSizer(account_equity=100000, risk_per_trade=0.02)
size = sizer.calculate_size(
    symbol="AAPL",
    entry_price=185.0,
    stop_loss=180.0,
    method="risk_pct"  # or "kelly", "atr", "fixed"
)

# Portfolio risk tracks aggregate exposure
portfolio = PortfolioRisk(max_portfolio_heat=0.10)
portfolio.add_position("AAPL", size=100, risk_amount=500)
can_trade = portfolio.can_add_position(new_risk=300)
```

## Components

### 1. Position Sizing Methods

**Fixed Size**: Simple fixed share count (current approach)

**Risk Percentage**: Size based on max $ risk per trade
```
position_size = (account_equity * risk_pct) / (entry_price - stop_loss)
```

**Kelly Criterion**: Optimal sizing based on win rate and reward/risk
```
kelly_pct = win_rate - ((1 - win_rate) / reward_risk_ratio)
position_size = account_equity * kelly_pct * kelly_fraction
```

**ATR-Based**: Volatility-adjusted sizing
```
atr = average_true_range(prices, period=14)
stop_distance = atr * atr_multiplier
position_size = (account_equity * risk_pct) / stop_distance
```

### 2. Portfolio Risk Metrics

**Portfolio Heat**: Total capital at risk across all positions
```
heat = sum(position_risk for all positions) / account_equity
```

**Sector/Symbol Concentration**: Max exposure per symbol/sector

**Correlation Limits**: Reduce size when adding correlated positions

### 3. ATR Indicator

Add Average True Range calculation for volatility measurement.

## Files to Create/Modify

### New Files
```
src/axtrade/indicators/atr.py           # ATR calculation
src/axtrade/oms/position_sizer.py       # Position sizing logic
src/axtrade/oms/portfolio_risk.py       # Portfolio-level risk
tests/unit/test_atr.py
tests/unit/test_position_sizer.py
tests/unit/test_portfolio_risk.py
```

### Modify Existing
```
src/axtrade/indicators/__init__.py      # Export ATR
src/axtrade/oms/__init__.py             # Export new classes
src/axtrade/strategies/base.py          # Add sizer integration
config/default.yaml                      # Add position sizing config
src/axtrade/common/config.py            # Add PositionSizingConfig
```

## Implementation Details

### 1. ATR Indicator (indicators/atr.py)
```python
def calculate_true_range(high: float, low: float, prev_close: float) -> float:
    """Calculate True Range for a single bar."""
    return max(
        high - low,
        abs(high - prev_close),
        abs(low - prev_close)
    )

def calculate_atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14
) -> float | None:
    """Calculate Average True Range."""
    if len(highs) < period + 1:
        return None

    true_ranges = []
    for i in range(1, len(highs)):
        tr = calculate_true_range(highs[i], lows[i], closes[i-1])
        true_ranges.append(tr)

    # Use simple average for ATR
    return sum(true_ranges[-period:]) / period
```

### 2. Position Sizer (oms/position_sizer.py)
```python
@dataclass
class SizingResult:
    shares: int
    dollar_amount: Decimal
    risk_amount: Decimal
    method: str

class PositionSizer:
    def __init__(
        self,
        account_equity: Decimal,
        risk_per_trade: float = 0.02,      # 2% risk per trade
        max_position_pct: float = 0.10,    # 10% max position
        kelly_fraction: float = 0.25,       # Use 1/4 Kelly
    ):
        self.account_equity = account_equity
        self.risk_per_trade = risk_per_trade
        self.max_position_pct = max_position_pct
        self.kelly_fraction = kelly_fraction

    def fixed_size(self, shares: int) -> SizingResult:
        """Return fixed share count."""

    def risk_pct_size(
        self,
        entry_price: Decimal,
        stop_loss: Decimal,
    ) -> SizingResult:
        """Size based on risk percentage."""
        risk_amount = self.account_equity * Decimal(str(self.risk_per_trade))
        stop_distance = abs(entry_price - stop_loss)
        if stop_distance == 0:
            return self.fixed_size(0)
        shares = int(risk_amount / stop_distance)
        return self._apply_limits(shares, entry_price)

    def kelly_size(
        self,
        entry_price: Decimal,
        win_rate: float,
        avg_win: Decimal,
        avg_loss: Decimal,
    ) -> SizingResult:
        """Size based on Kelly Criterion."""
        if avg_loss == 0:
            return self.fixed_size(0)
        reward_risk = avg_win / avg_loss
        kelly_pct = win_rate - ((1 - win_rate) / float(reward_risk))
        kelly_pct = max(0, kelly_pct) * self.kelly_fraction
        dollar_amount = self.account_equity * Decimal(str(kelly_pct))
        shares = int(dollar_amount / entry_price)
        return self._apply_limits(shares, entry_price)

    def atr_size(
        self,
        entry_price: Decimal,
        atr: float,
        atr_multiplier: float = 2.0,
    ) -> SizingResult:
        """Size based on ATR volatility."""
        stop_distance = Decimal(str(atr * atr_multiplier))
        if stop_distance == 0:
            return self.fixed_size(0)
        risk_amount = self.account_equity * Decimal(str(self.risk_per_trade))
        shares = int(risk_amount / stop_distance)
        return self._apply_limits(shares, entry_price)

    def _apply_limits(self, shares: int, price: Decimal) -> SizingResult:
        """Apply max position size limits."""
        max_shares = int(
            (self.account_equity * Decimal(str(self.max_position_pct))) / price
        )
        shares = min(shares, max_shares)
        return SizingResult(
            shares=shares,
            dollar_amount=Decimal(shares) * price,
            risk_amount=...,
            method=...,
        )
```

### 3. Portfolio Risk (oms/portfolio_risk.py)
```python
@dataclass
class PositionRisk:
    symbol: str
    shares: int
    entry_price: Decimal
    current_price: Decimal
    stop_loss: Decimal | None
    risk_amount: Decimal  # $ at risk if stop hit

@dataclass
class PortfolioMetrics:
    total_exposure: Decimal      # Total $ in positions
    total_risk: Decimal          # Total $ at risk
    portfolio_heat: float        # risk / equity
    largest_position_pct: float  # Concentration
    position_count: int

class PortfolioRisk:
    def __init__(
        self,
        account_equity: Decimal,
        max_portfolio_heat: float = 0.10,    # 10% max total risk
        max_single_position: float = 0.15,   # 15% max per position
        max_correlated_exposure: float = 0.25,  # 25% max correlated
    ):
        self.account_equity = account_equity
        self.max_portfolio_heat = max_portfolio_heat
        self.max_single_position = max_single_position
        self.max_correlated_exposure = max_correlated_exposure
        self._positions: dict[str, PositionRisk] = {}

    def add_position(self, position: PositionRisk) -> None:
        """Track a new position."""

    def remove_position(self, symbol: str) -> None:
        """Remove closed position."""

    def update_price(self, symbol: str, price: Decimal) -> None:
        """Update position current price."""

    def can_add_risk(self, additional_risk: Decimal) -> bool:
        """Check if adding risk would exceed limits."""
        current_heat = self.get_metrics().portfolio_heat
        new_heat = (self.total_risk() + additional_risk) / self.account_equity
        return new_heat <= self.max_portfolio_heat

    def get_metrics(self) -> PortfolioMetrics:
        """Calculate current portfolio metrics."""

    def get_position_limit(self, symbol: str) -> Decimal:
        """Get max position size for symbol considering concentration."""
```

### 4. Config Updates
```python
@dataclass
class PositionSizingConfig:
    method: str = "risk_pct"           # fixed, risk_pct, kelly, atr
    risk_per_trade: float = 0.02       # 2% risk per trade
    max_position_pct: float = 0.10     # 10% max position
    kelly_fraction: float = 0.25       # Use 1/4 Kelly
    atr_multiplier: float = 2.0        # 2x ATR for stops

@dataclass
class PortfolioRiskConfig:
    max_portfolio_heat: float = 0.10   # 10% max total risk
    max_single_position: float = 0.15  # 15% max per position
    max_correlated_exposure: float = 0.25
```

## Implementation Order

1. **ATR Indicator**: Create atr.py with true range and ATR calculation
2. **Position Sizer**: Create position_sizer.py with all sizing methods
3. **Portfolio Risk**: Create portfolio_risk.py with metrics tracking
4. **Config**: Add PositionSizingConfig and PortfolioRiskConfig
5. **Integration**: Update strategies to optionally use position sizer
6. **Tests**: Comprehensive tests for all components

## Verification Steps

1. Run tests: `pytest tests/unit/test_atr.py tests/unit/test_position_sizer.py tests/unit/test_portfolio_risk.py -v`
2. Verify sizing calculations manually
3. Run all tests: `pytest -v`
