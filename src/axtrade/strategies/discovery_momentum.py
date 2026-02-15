"""Discovery-driven momentum strategy.

Trades symbols discovered by the screening pipeline, entering long
positions on high-score bullish signals and exiting when the score
decays or stop-loss triggers.
"""

from decimal import Decimal
from typing import Optional

from axtrade.discovery.service import DiscoveryService
from axtrade.oms import Order, OrderSide, OrderType

from .base import BarWithIndicators, BaseStrategy


class DiscoveryMomentumStrategy(BaseStrategy):
    """Long-only strategy that trades symbols surfaced by discovery screeners.

    Entry: symbol is discovered with score >= min_score, bullish, RSI < 70,
           price above SMA, and own position count < max_positions.
    Exit: score dropped below score_decay_exit, stop loss hit, RSI overbought,
          or symbol removed from discovered cache.
    """

    def __init__(self, strategy_id: str, config: dict):
        super().__init__(strategy_id, config)

        self.min_score = config.get("min_score", 60)
        self.position_size = Decimal(str(config.get("position_size", 50)))
        self.stop_loss_pct = config.get("stop_loss_pct", 0.03)
        self.score_decay_exit = config.get("score_decay_exit", 30)
        self.max_positions = config.get("max_positions", 10)

        self._discovery_service: Optional[DiscoveryService] = None

    @property
    def name(self) -> str:
        return "DiscoveryMomentum"

    def set_discovery_service(self, svc: DiscoveryService) -> None:
        """Inject the discovery service for live score lookups."""
        self._discovery_service = svc

    def _get_discovery_score(self, symbol: str) -> Optional[float]:
        """Get the current discovery score for a symbol, or None if not discovered."""
        if not self._discovery_service:
            return None

        for ds in self._discovery_service.get_discovered():
            if ds.symbol == symbol and ds.is_bullish:
                return ds.score
        return None

    def on_bar(self, data: BarWithIndicators) -> Optional[Order]:
        """Process bar and generate trading signals."""
        if self._discovery_service is None:
            return None

        if data.sma_20 is None or data.rsi_14 is None:
            return None

        position = self.get_position(data.symbol)
        score = self._get_discovery_score(data.symbol)

        # Exit logic
        if position and position.quantity > 0:
            return self._check_exit(data, position, score)

        # Entry logic
        return self._check_entry(data, score)

    def _check_entry(self, data: BarWithIndicators, score: Optional[float]) -> Optional[Order]:
        """Check for entry conditions."""
        if score is None or score < self.min_score:
            return None

        if len(self.positions) >= self.max_positions:
            return None

        # RSI not overbought
        if data.rsi_14 >= 70:
            return None

        # Price above SMA (trend confirmation)
        if data.close <= data.sma_20:
            return None

        return Order(
            strategy_id=self.strategy_id,
            symbol=data.symbol,
            side=OrderSide.BUY,
            quantity=self.position_size,
            order_type=OrderType.MARKET,
        )

    def _check_exit(self, data: BarWithIndicators, position, score: Optional[float]) -> Optional[Order]:
        """Check for exit conditions."""
        # Symbol no longer in discovery cache
        if score is None:
            return self._create_close_order(data.symbol, position.quantity)

        # Score decayed below threshold
        if score < self.score_decay_exit:
            return self._create_close_order(data.symbol, position.quantity)

        # Stop loss
        if position.avg_entry_price:
            entry_price = float(position.avg_entry_price)
            loss_pct = (data.close - entry_price) / entry_price
            if loss_pct < -self.stop_loss_pct:
                return self._create_close_order(data.symbol, position.quantity)

        # RSI overbought
        if data.rsi_14 > 70:
            return self._create_close_order(data.symbol, position.quantity)

        return None

    def _create_close_order(self, symbol: str, quantity: Decimal) -> Order:
        """Create an order to close the position."""
        return Order(
            strategy_id=self.strategy_id,
            symbol=symbol,
            side=OrderSide.SELL,
            quantity=quantity,
            order_type=OrderType.MARKET,
        )
