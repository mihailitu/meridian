"""Buy-and-hold calibration benchmark strategy."""

from decimal import Decimal
from typing import Optional

from axtrade.oms import Order, OrderSide, OrderType

from .base import BarWithIndicators, BaseStrategy


class BuyHoldStrategy(BaseStrategy):
    """Calibration benchmark: buy each allowed symbol once, never exit.

    The expected outcome of running this through the fulltest pipeline is
    computable by hand from the input data — for each symbol,
    ``quantity x (last_close - entry_fill_price) - commission`` — so a run
    validates the harness's fill, accounting, and reporting paths
    end-to-end. If the reported equity diverges from the arithmetic, the
    harness is wrong, not the strategy.

    Not a trading strategy: excluded from fulltest runs unless explicitly
    selected via ``--strategies buy_hold``.
    """

    def __init__(self, strategy_id: str, config: dict):
        super().__init__(strategy_id, config)
        self.position_size = Decimal(str(config.get("position_size", 100)))

        syms = config.get("allowed_symbols")
        self.allowed_symbols: Optional[set[str]] = set(syms) if syms else None

        # Symbols we've already sent the one buy for. Tracked separately
        # from self.positions so a slow fill can't cause a double order.
        self._ordered: set[str] = set()

    @property
    def name(self) -> str:
        return "BuyHold"

    def on_bar(self, data: BarWithIndicators) -> Optional[Order]:
        if self.allowed_symbols is not None and data.symbol not in self.allowed_symbols:
            return None

        if data.symbol in self._ordered:
            return None

        if self.at_capacity():
            return None

        self._ordered.add(data.symbol)
        return Order(
            strategy_id=self.strategy_id,
            symbol=data.symbol,
            side=OrderSide.BUY,
            quantity=self.position_size,
            order_type=OrderType.MARKET,
        )
