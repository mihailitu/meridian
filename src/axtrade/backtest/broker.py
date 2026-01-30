"""Simulated broker for backtesting."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from axtrade.common import Bar
from axtrade.oms import Fill, Order, OrderSide, OrderStatus, Position

from .types import EquityPoint, TradeRecord


class SimulatedBroker:
    """Simulates order execution using historical prices."""

    def __init__(
        self,
        initial_capital: Decimal,
        commission: Decimal = Decimal("1.00"),
        slippage_bps: int = 5,
    ):
        """Initialize simulated broker.

        Args:
            initial_capital: Starting cash amount
            commission: Commission per trade
            slippage_bps: Slippage in basis points (1 bp = 0.01%)
        """
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.commission = commission
        self.slippage_bps = slippage_bps

        self._positions: dict[str, Position] = {}
        self.trades: list[TradeRecord] = []
        self.equity_curve: list[EquityPoint] = []
        self._peak_equity = initial_capital

    def execute_order(
        self,
        order: Order,
        bar: Bar,
        strategy_id: str,
    ) -> Optional[Fill]:
        """Execute order at bar's close price with slippage.

        Args:
            order: Order to execute
            bar: Current bar for price reference
            strategy_id: Strategy that generated the order

        Returns:
            Fill if order executed, None if rejected
        """
        # Calculate execution price with slippage
        base_price = Decimal(str(bar.close))
        slippage_mult = Decimal(str(1 + (self.slippage_bps / 10000)))

        if order.side == OrderSide.BUY:
            exec_price = base_price * slippage_mult
        else:
            exec_price = base_price / slippage_mult

        exec_price = exec_price.quantize(Decimal("0.01"))

        # Check sufficient capital for buys
        if order.side == OrderSide.BUY:
            total_cost = exec_price * order.quantity + self.commission
            if total_cost > self.cash:
                order.status = OrderStatus.REJECTED
                return None

        # Execute the order
        pnl: Optional[Decimal] = None

        if order.side == OrderSide.BUY:
            # Deduct cash
            self.cash -= exec_price * order.quantity + self.commission

            # Create or add to position
            if order.symbol in self._positions:
                pos = self._positions[order.symbol]
                # Average up the position
                total_qty = pos.quantity + order.quantity
                total_cost = (pos.avg_entry_price * pos.quantity) + (
                    exec_price * order.quantity
                )
                pos.avg_entry_price = total_cost / total_qty
                pos.quantity = total_qty
            else:
                self._positions[order.symbol] = Position(
                    strategy_id=strategy_id,
                    symbol=order.symbol,
                    side="long",
                    quantity=order.quantity,
                    avg_entry_price=exec_price,
                    opened_at=bar.timestamp,
                )

        else:  # SELL
            if order.symbol not in self._positions:
                order.status = OrderStatus.REJECTED
                return None

            pos = self._positions[order.symbol]

            # Calculate P&L
            pnl = (exec_price - pos.avg_entry_price) * order.quantity
            pnl -= self.commission  # Deduct commission from P&L

            # Add proceeds to cash
            self.cash += exec_price * order.quantity - self.commission

            # Update or remove position
            pos.quantity -= order.quantity
            if pos.quantity <= 0:
                pos.realized_pnl += pnl + self.commission  # Add back for position tracking
                pos.closed_at = bar.timestamp
                del self._positions[order.symbol]
            else:
                pos.realized_pnl += pnl + self.commission

        # Update order status
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.avg_fill_price = exec_price

        # Record trade
        trade = TradeRecord(
            timestamp=bar.timestamp,
            side=order.side.value.upper(),
            quantity=order.quantity,
            price=exec_price,
            commission=self.commission,
            pnl=pnl,
        )
        self.trades.append(trade)

        # Create fill
        fill = Fill(
            order_id=order.id,
            strategy_id=strategy_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=exec_price,
            commission=self.commission,
            filled_at=bar.timestamp,
        )

        return fill

    def update_equity(self, bar: Bar, timestamp: datetime) -> None:
        """Update equity curve with current mark-to-market.

        Args:
            bar: Current bar for position valuation
            timestamp: Timestamp for equity point
        """
        # Calculate total equity
        equity = self.cash

        for symbol, pos in self._positions.items():
            if pos.symbol == bar.symbol:
                market_value = pos.quantity * Decimal(str(bar.close))
                equity += market_value

        # Calculate drawdown from peak
        if equity > self._peak_equity:
            self._peak_equity = equity

        drawdown = Decimal("0")
        if self._peak_equity > 0:
            drawdown = ((self._peak_equity - equity) / self._peak_equity) * 100

        self.equity_curve.append(
            EquityPoint(
                timestamp=timestamp,
                equity=equity,
                drawdown=drawdown,
            )
        )

    def get_position(self, symbol: str) -> Optional[Position]:
        """Get current position for symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Position if exists, None otherwise
        """
        return self._positions.get(symbol)

    def get_equity(self) -> Decimal:
        """Get current total equity."""
        if self.equity_curve:
            return self.equity_curve[-1].equity
        return self.initial_capital

    def get_total_commission(self) -> Decimal:
        """Get total commission paid."""
        return sum((t.commission for t in self.trades), Decimal("0"))
