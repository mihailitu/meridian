"""Unit tests for OrderManager.

Tests for order submission, fill handling, and position management.
"""

import asyncio
import copy
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from axtrade.common import Config, DatabaseConfig, OMSConfig, RedisConfig, RiskConfig
from axtrade.oms.broker import VolumeCapExceededError
from axtrade.oms.manager import OrderManager, OrderRejectedError
from axtrade.oms.risk import RiskCheckResult
from axtrade.oms.types import Fill, Order, OrderSide, OrderStatus, OrderType, Position


class TestOrderManager:
    """Tests for OrderManager."""

    @pytest.fixture
    def mock_config(self) -> Config:
        """Create a test configuration."""
        config = Config()
        config.redis = RedisConfig(host="localhost", port=6379)
        config.database = DatabaseConfig()
        config.oms = OMSConfig(
            paper_mode=True,
            slippage_bps=10,
            risk=RiskConfig(
                max_position_size=1000,
                max_position_value=50000.0,
                max_order_size=500,
                max_daily_loss=1000.0,
                max_open_orders=10,
            ),
        )
        return config

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock database pool."""
        pool = MagicMock()
        pool.acquire = MagicMock()
        return pool

    @pytest.fixture
    def manager(self, mock_config: Config, mock_pool: MagicMock) -> OrderManager:
        """Create OrderManager instance."""
        return OrderManager(mock_config, mock_pool)

    @pytest.fixture
    def sample_order(self) -> Order:
        """Create a sample order."""
        return Order(
            strategy_id="momentum_01",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            order_type=OrderType.MARKET,
        )

    @pytest.fixture
    def sample_fill(self, sample_order: Order) -> Fill:
        """Create a sample fill for the sample order."""
        return Fill(
            order_id=sample_order.id,
            strategy_id=sample_order.strategy_id,
            symbol=sample_order.symbol,
            side=sample_order.side,
            quantity=Decimal("100"),
            price=Decimal("185.50"),
            commission=Decimal("1.00"),
        )

    async def test_connect_initializes_components(
        self, manager: OrderManager, mock_config: Config, mock_pool: MagicMock
    ) -> None:
        """Test connect initializes repositories, broker, and connections."""
        mock_redis = AsyncMock()
        mock_broker = AsyncMock()

        with patch("axtrade.oms.manager.redis.Redis", return_value=mock_redis):
            with patch("axtrade.oms.manager.PaperBroker", return_value=mock_broker):
                await manager.connect()

        assert manager._order_repo is not None
        assert manager._position_repo is not None
        assert manager._risk_manager is not None
        assert manager._broker is not None
        mock_redis.ping.assert_called_once()
        mock_broker.connect.assert_called_once()

    async def test_disconnect_closes_connections(
        self, manager: OrderManager
    ) -> None:
        """Test disconnect closes broker and Redis."""
        mock_broker = AsyncMock()
        mock_redis = AsyncMock()

        manager._broker = mock_broker
        manager._redis = mock_redis

        await manager.disconnect()

        mock_broker.disconnect.assert_called_once()
        mock_redis.aclose.assert_called_once()
        assert manager._broker is None
        assert manager._redis is None

    async def test_submit_order_success(
        self, manager: OrderManager, sample_order: Order
    ) -> None:
        """Test successful order submission flow."""
        # Setup mocks
        mock_order_repo = AsyncMock()
        mock_position_repo = AsyncMock()
        mock_position_repo.get.return_value = None
        mock_broker = AsyncMock()
        mock_broker.submit_order.return_value = "broker-123"
        mock_risk_manager = MagicMock()
        mock_risk_manager.check_order.return_value = RiskCheckResult(approved=True)

        manager._order_repo = mock_order_repo
        manager._position_repo = mock_position_repo
        manager._broker = mock_broker
        manager._risk_manager = mock_risk_manager

        # Update price for risk check
        manager._last_prices["AAPL"] = Decimal("185.00")

        result = await manager.submit_order(sample_order)

        assert result == sample_order.id
        mock_order_repo.insert.assert_called_once_with(sample_order)
        mock_broker.submit_order.assert_called_once_with(sample_order)
        mock_risk_manager.order_submitted.assert_called_once()
        assert sample_order.status == OrderStatus.SUBMITTED

    async def test_submit_order_synchronous_fill_not_clobbered(
        self, manager: OrderManager, sample_order: Order
    ) -> None:
        """A broker that fills synchronously inside submit_order (PaperBroker)
        resolves the order to FILLED before submit_order returns; the manager
        must not stamp it back to SUBMITTED afterwards. Regression for the
        bug where every immediately-filled paper order persisted as
        'submitted' (caught by tests/integration/test_paper_pipeline.py)."""
        mock_order_repo = AsyncMock()
        mock_position_repo = AsyncMock()
        mock_position_repo.get.return_value = None
        mock_risk_manager = MagicMock()
        mock_risk_manager.check_order.return_value = RiskCheckResult(approved=True)

        async def fill_synchronously(order: Order) -> str:
            # Mimic PaperBroker: mutate the shared Order to its resolved
            # state before submit_order returns.
            order.status = OrderStatus.FILLED
            order.filled_quantity = order.quantity
            return str(order.id)

        mock_broker = AsyncMock()
        mock_broker.submit_order.side_effect = fill_synchronously

        manager._order_repo = mock_order_repo
        manager._position_repo = mock_position_repo
        manager._broker = mock_broker
        manager._risk_manager = mock_risk_manager
        manager._last_prices["AAPL"] = Decimal("185.00")

        await manager.submit_order(sample_order)

        assert sample_order.status == OrderStatus.FILLED
        # The submit path only ever writes the SUBMITTED stamp via the
        # conditional update_status_if — never the unconditional update().
        mock_order_repo.update.assert_not_called()

    async def test_submit_order_conditional_stamp_false_not_clobbered(
        self, manager: OrderManager, sample_order: Order
    ) -> None:
        """Regression for the async-broker race the old in-memory-only check
        left open: a detached fill task can persist FILLED between
        submit_order's check and its SUBMITTED write. Here update_status_if
        itself reports the row didn't match (already FILLED in the DB) even
        though nothing in this call stack touched sample_order.status —
        the in-memory object must stay whatever it already was and the
        submit path must not clobber it back to SUBMITTED."""
        mock_order_repo = AsyncMock()
        mock_order_repo.update_status_if.return_value = False
        mock_position_repo = AsyncMock()
        mock_position_repo.get.return_value = None
        mock_risk_manager = MagicMock()
        mock_risk_manager.check_order.return_value = RiskCheckResult(approved=True)

        mock_broker = AsyncMock()
        mock_broker.submit_order.return_value = "broker-123"

        manager._order_repo = mock_order_repo
        manager._position_repo = mock_position_repo
        manager._broker = mock_broker
        manager._risk_manager = mock_risk_manager
        manager._last_prices["AAPL"] = Decimal("185.00")

        # Simulate the DB row already resolved to FILLED by a concurrent
        # fill task, but nothing updated the in-memory sample_order here —
        # exercises the "stamped is False" branch specifically.
        await manager.submit_order(sample_order)

        mock_order_repo.update_status_if.assert_called_once_with(
            sample_order.id, OrderStatus.SUBMITTED, [OrderStatus.PENDING]
        )
        # stamped=False means the in-memory object must not be forced to
        # SUBMITTED — it stays PENDING here since nothing else touched it.
        assert sample_order.status == OrderStatus.PENDING

    async def test_submit_order_risk_rejected(
        self, manager: OrderManager, sample_order: Order
    ) -> None:
        """Test order rejection by risk manager."""
        mock_order_repo = AsyncMock()
        mock_position_repo = AsyncMock()
        mock_position_repo.get.return_value = None
        mock_risk_manager = MagicMock()
        mock_risk_manager.check_order.return_value = RiskCheckResult(
            approved=False, reason="Position size exceeds limit"
        )

        manager._order_repo = mock_order_repo
        manager._position_repo = mock_position_repo
        manager._broker = AsyncMock()
        manager._risk_manager = mock_risk_manager

        with pytest.raises(OrderRejectedError, match="Position size exceeds limit"):
            await manager.submit_order(sample_order)

        assert sample_order.status == OrderStatus.REJECTED
        mock_order_repo.insert.assert_called_once()

    async def test_submit_order_broker_failure(
        self, manager: OrderManager, sample_order: Order
    ) -> None:
        """Test broker submission error handling."""
        mock_order_repo = AsyncMock()
        mock_position_repo = AsyncMock()
        mock_position_repo.get.return_value = None
        mock_broker = AsyncMock()
        mock_broker.submit_order.side_effect = Exception("Connection failed")
        mock_risk_manager = MagicMock()
        mock_risk_manager.check_order.return_value = RiskCheckResult(approved=True)

        manager._order_repo = mock_order_repo
        manager._position_repo = mock_position_repo
        manager._broker = mock_broker
        manager._risk_manager = mock_risk_manager

        with pytest.raises(Exception, match="Connection failed"):
            await manager.submit_order(sample_order)

        assert sample_order.status == OrderStatus.REJECTED
        # Update should be called to persist rejection
        mock_order_repo.update.assert_called_once()

    async def test_submit_order_volume_cap_rejected(
        self, manager: OrderManager, sample_order: Order
    ) -> None:
        """Broker raising VolumeCapExceededError is a clean rejection, not a
        crash — mirrors how InsufficientCashError is handled."""
        mock_order_repo = AsyncMock()
        mock_position_repo = AsyncMock()
        mock_position_repo.get.return_value = None
        mock_broker = AsyncMock()
        mock_broker.submit_order.side_effect = VolumeCapExceededError(
            "AAPL order quantity 200 exceeds volume cap 100"
        )
        mock_risk_manager = MagicMock()
        mock_risk_manager.check_order.return_value = RiskCheckResult(approved=True)

        manager._order_repo = mock_order_repo
        manager._position_repo = mock_position_repo
        manager._broker = mock_broker
        manager._risk_manager = mock_risk_manager

        with pytest.raises(OrderRejectedError, match="volume cap"):
            await manager.submit_order(sample_order)

        assert sample_order.status == OrderStatus.REJECTED
        mock_risk_manager.order_submitted.assert_called_once()
        mock_risk_manager.order_completed.assert_called_once()
        mock_order_repo.update.assert_called_once()

    async def test_submit_order_not_connected(
        self, manager: OrderManager, sample_order: Order
    ) -> None:
        """Test submit raises error when not connected."""
        with pytest.raises(RuntimeError, match="not connected"):
            await manager.submit_order(sample_order)

    async def test_on_broker_fill_complete(
        self, manager: OrderManager, sample_order: Order, sample_fill: Fill
    ) -> None:
        """Test complete fill handling."""
        sample_order.quantity = Decimal("100")

        mock_order_repo = AsyncMock()
        mock_order_repo.get.return_value = sample_order
        mock_position_repo = AsyncMock()
        mock_position_repo.get.return_value = None
        mock_redis = AsyncMock()
        mock_risk_manager = MagicMock()

        manager._order_repo = mock_order_repo
        manager._position_repo = mock_position_repo
        manager._redis = mock_redis
        manager._risk_manager = mock_risk_manager

        await manager._on_broker_fill(sample_fill)

        # Order should be updated to FILLED
        assert sample_order.status == OrderStatus.FILLED
        assert sample_order.filled_quantity == Decimal("100")
        assert sample_order.avg_fill_price == Decimal("185.50")
        mock_order_repo.update.assert_called_once()
        mock_order_repo.insert_fill.assert_called_once()
        mock_position_repo.upsert.assert_called_once()
        mock_risk_manager.order_completed.assert_called_once()

    async def test_on_broker_fill_partial(
        self, manager: OrderManager, sample_order: Order
    ) -> None:
        """Test partial fill handling."""
        sample_order.quantity = Decimal("200")
        sample_order.filled_quantity = Decimal("0")

        partial_fill = Fill(
            order_id=sample_order.id,
            strategy_id=sample_order.strategy_id,
            symbol=sample_order.symbol,
            side=sample_order.side,
            quantity=Decimal("100"),  # Partial fill
            price=Decimal("185.50"),
        )

        mock_order_repo = AsyncMock()
        mock_order_repo.get.return_value = sample_order
        mock_position_repo = AsyncMock()
        mock_position_repo.get.return_value = None
        mock_redis = AsyncMock()
        mock_risk_manager = MagicMock()

        manager._order_repo = mock_order_repo
        manager._position_repo = mock_position_repo
        manager._redis = mock_redis
        manager._risk_manager = mock_risk_manager

        await manager._on_broker_fill(partial_fill)

        # Order should be PARTIAL
        assert sample_order.status == OrderStatus.PARTIAL
        assert sample_order.filled_quantity == Decimal("100")
        # Should NOT call order_completed for partial fills
        mock_risk_manager.order_completed.assert_not_called()

    async def test_on_broker_fill_weighted_avg_price(
        self, manager: OrderManager, sample_order: Order
    ) -> None:
        """Test weighted average fill price calculation."""
        sample_order.quantity = Decimal("200")
        sample_order.filled_quantity = Decimal("100")
        sample_order.avg_fill_price = Decimal("185.00")

        second_fill = Fill(
            order_id=sample_order.id,
            strategy_id=sample_order.strategy_id,
            symbol=sample_order.symbol,
            side=sample_order.side,
            quantity=Decimal("100"),
            price=Decimal("186.00"),
        )

        mock_order_repo = AsyncMock()
        mock_order_repo.get.return_value = sample_order
        mock_position_repo = AsyncMock()
        mock_position_repo.get.return_value = None
        mock_redis = AsyncMock()
        mock_risk_manager = MagicMock()

        manager._order_repo = mock_order_repo
        manager._position_repo = mock_position_repo
        manager._redis = mock_redis
        manager._risk_manager = mock_risk_manager

        await manager._on_broker_fill(second_fill)

        # Weighted average: (100*185 + 100*186) / 200 = 185.50
        assert sample_order.avg_fill_price == Decimal("185.50")

    async def test_update_position_new_long(
        self, manager: OrderManager, sample_fill: Fill
    ) -> None:
        """Test new long position creation."""
        mock_position_repo = AsyncMock()
        mock_position_repo.get.return_value = None
        mock_risk_manager = MagicMock()

        manager._position_repo = mock_position_repo
        manager._risk_manager = mock_risk_manager

        await manager._update_position(sample_fill)

        mock_position_repo.upsert.assert_called_once()
        call_args = mock_position_repo.upsert.call_args[0][0]
        assert call_args.side == "long"
        assert call_args.quantity == Decimal("100")
        assert call_args.avg_entry_price == Decimal("185.50")

    async def test_update_position_add_to_long(
        self, manager: OrderManager
    ) -> None:
        """Test averaging into existing long position."""
        existing_position = Position(
            strategy_id="momentum_01",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("180.00"),
        )

        add_fill = Fill(
            order_id=uuid4(),
            strategy_id="momentum_01",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            price=Decimal("190.00"),
        )

        mock_position_repo = AsyncMock()
        mock_position_repo.get.return_value = existing_position
        mock_risk_manager = MagicMock()

        manager._position_repo = mock_position_repo
        manager._risk_manager = mock_risk_manager

        await manager._update_position(add_fill)

        mock_position_repo.upsert.assert_called_once()
        call_args = mock_position_repo.upsert.call_args[0][0]
        # New avg: (100*180 + 100*190) / 200 = 185
        assert call_args.quantity == Decimal("200")
        assert call_args.avg_entry_price == Decimal("185.000000")

    async def test_update_position_close_long(
        self, manager: OrderManager
    ) -> None:
        """Test position closure with P&L calculation."""
        existing_position = Position(
            strategy_id="momentum_01",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("180.00"),
            realized_pnl=Decimal("0"),
        )

        close_fill = Fill(
            order_id=uuid4(),
            strategy_id="momentum_01",
            symbol="AAPL",
            side=OrderSide.SELL,
            quantity=Decimal("100"),
            price=Decimal("190.00"),
        )

        mock_position_repo = AsyncMock()
        mock_position_repo.get.return_value = existing_position
        mock_risk_manager = MagicMock()

        manager._position_repo = mock_position_repo
        manager._risk_manager = mock_risk_manager

        await manager._update_position(close_fill)

        mock_position_repo.upsert.assert_called_once()
        call_args = mock_position_repo.upsert.call_args[0][0]
        # P&L = (190 - 180) * 100 = $1000
        assert call_args.quantity == Decimal("0")
        assert call_args.realized_pnl == Decimal("1000")
        mock_risk_manager.record_pnl.assert_called_once_with(Decimal("1000"))

    async def test_update_position_partial_close_long(
        self, manager: OrderManager
    ) -> None:
        """Test partial position close."""
        existing_position = Position(
            strategy_id="momentum_01",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("180.00"),
            realized_pnl=Decimal("0"),
        )

        partial_close = Fill(
            order_id=uuid4(),
            strategy_id="momentum_01",
            symbol="AAPL",
            side=OrderSide.SELL,
            quantity=Decimal("50"),
            price=Decimal("190.00"),
        )

        mock_position_repo = AsyncMock()
        mock_position_repo.get.return_value = existing_position
        mock_risk_manager = MagicMock()

        manager._position_repo = mock_position_repo
        manager._risk_manager = mock_risk_manager

        await manager._update_position(partial_close)

        call_args = mock_position_repo.upsert.call_args[0][0]
        # P&L = (190 - 180) * 50 = $500
        assert call_args.quantity == Decimal("50")
        assert call_args.realized_pnl == Decimal("500")

    async def test_update_position_flip_side(
        self, manager: OrderManager
    ) -> None:
        """Test long to short flip."""
        existing_position = Position(
            strategy_id="momentum_01",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("180.00"),
            realized_pnl=Decimal("0"),
        )

        flip_fill = Fill(
            order_id=uuid4(),
            strategy_id="momentum_01",
            symbol="AAPL",
            side=OrderSide.SELL,
            quantity=Decimal("150"),  # Sell more than we have
            price=Decimal("190.00"),
        )

        mock_position_repo = AsyncMock()
        mock_position_repo.get.return_value = existing_position
        mock_risk_manager = MagicMock()

        manager._position_repo = mock_position_repo
        manager._risk_manager = mock_risk_manager

        await manager._update_position(flip_fill)

        call_args = mock_position_repo.upsert.call_args[0][0]
        # After flip: short 50 shares
        assert call_args.side == "short"
        assert call_args.quantity == Decimal("50")
        assert call_args.avg_entry_price == Decimal("190.00")

    async def test_update_position_new_short(
        self, manager: OrderManager
    ) -> None:
        """Test new short position creation."""
        short_fill = Fill(
            order_id=uuid4(),
            strategy_id="momentum_01",
            symbol="AAPL",
            side=OrderSide.SELL,
            quantity=Decimal("100"),
            price=Decimal("185.50"),
        )

        mock_position_repo = AsyncMock()
        mock_position_repo.get.return_value = None
        mock_risk_manager = MagicMock()

        manager._position_repo = mock_position_repo
        manager._risk_manager = mock_risk_manager

        await manager._update_position(short_fill)

        call_args = mock_position_repo.upsert.call_args[0][0]
        assert call_args.side == "short"
        assert call_args.quantity == Decimal("100")

    async def test_update_position_close_short(
        self, manager: OrderManager
    ) -> None:
        """Test short position close with P&L."""
        existing_position = Position(
            strategy_id="momentum_01",
            symbol="AAPL",
            side="short",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("190.00"),
            realized_pnl=Decimal("0"),
        )

        close_fill = Fill(
            order_id=uuid4(),
            strategy_id="momentum_01",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            price=Decimal("180.00"),
        )

        mock_position_repo = AsyncMock()
        mock_position_repo.get.return_value = existing_position
        mock_risk_manager = MagicMock()

        manager._position_repo = mock_position_repo
        manager._risk_manager = mock_risk_manager

        await manager._update_position(close_fill)

        call_args = mock_position_repo.upsert.call_args[0][0]
        # Short P&L = (entry - exit) * qty = (190 - 180) * 100 = $1000
        assert call_args.quantity == Decimal("0")
        assert call_args.realized_pnl == Decimal("1000")

    async def test_update_position_reopen_after_close_same_side(
        self, manager: OrderManager
    ) -> None:
        """Re-entry after a full close must produce a fresh long position,
        not pyramid onto the closed row. Regression for the ghost-position
        bug where closed_at never cleared and avg_entry_price/quantity got
        merged with the prior (closed) row.
        """
        closed_position = Position(
            strategy_id="momentum_01",
            symbol="AAPL",
            side="long",
            quantity=Decimal("0"),
            avg_entry_price=Decimal("180.00"),
            realized_pnl=Decimal("1000"),
            opened_at=datetime(2025, 8, 1, 10, 0, tzinfo=timezone.utc),
            closed_at=datetime(2025, 8, 1, 10, 40, tzinfo=timezone.utc),
        )

        reopen_fill = Fill(
            order_id=uuid4(),
            strategy_id="momentum_01",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("50"),
            price=Decimal("200.00"),
            filled_at=datetime(2025, 8, 1, 11, 6, tzinfo=timezone.utc),
        )

        mock_position_repo = AsyncMock()
        mock_position_repo.get.return_value = closed_position
        mock_risk_manager = MagicMock()
        manager._position_repo = mock_position_repo
        manager._risk_manager = mock_risk_manager

        await manager._update_position(reopen_fill)

        upserted = mock_position_repo.upsert.call_args[0][0]
        assert upserted.side == "long"
        assert upserted.quantity == Decimal("50"), "must not pyramid onto closed row"
        assert upserted.avg_entry_price == Decimal("200.00"), "must use the new fill price, not blended"
        assert upserted.closed_at is None, "closed_at must clear on re-open"
        assert upserted.opened_at == reopen_fill.filled_at, "opened_at must reset to the new fill time"
        assert upserted.realized_pnl == Decimal("1000"), "prior realized P&L preserved as cumulative"

    async def test_update_position_reopen_after_close_opposite_side(
        self, manager: OrderManager
    ) -> None:
        """Re-entry after close can flip side; the new position must reflect
        the fill's side, not the prior closed side."""
        closed_long = Position(
            strategy_id="momentum_01",
            symbol="AAPL",
            side="long",
            quantity=Decimal("0"),
            avg_entry_price=Decimal("180.00"),
            realized_pnl=Decimal("500"),
            closed_at=datetime(2025, 8, 1, 10, 40, tzinfo=timezone.utc),
        )

        short_entry = Fill(
            order_id=uuid4(),
            strategy_id="momentum_01",
            symbol="AAPL",
            side=OrderSide.SELL,
            quantity=Decimal("30"),
            price=Decimal("190.00"),
            filled_at=datetime(2025, 8, 1, 11, 0, tzinfo=timezone.utc),
        )

        mock_position_repo = AsyncMock()
        mock_position_repo.get.return_value = closed_long
        mock_risk_manager = MagicMock()
        manager._position_repo = mock_position_repo
        manager._risk_manager = mock_risk_manager

        await manager._update_position(short_entry)

        upserted = mock_position_repo.upsert.call_args[0][0]
        assert upserted.side == "short"
        assert upserted.quantity == Decimal("30")
        assert upserted.avg_entry_price == Decimal("190.00")
        assert upserted.closed_at is None

    async def test_fill_callback_invoked(
        self, manager: OrderManager, sample_order: Order, sample_fill: Fill
    ) -> None:
        """Test fill callback is invoked."""
        mock_order_repo = AsyncMock()
        mock_order_repo.get.return_value = sample_order
        mock_position_repo = AsyncMock()
        mock_position_repo.get.return_value = None
        mock_redis = AsyncMock()
        mock_risk_manager = MagicMock()

        manager._order_repo = mock_order_repo
        manager._position_repo = mock_position_repo
        manager._redis = mock_redis
        manager._risk_manager = mock_risk_manager

        callback_fills = []
        manager.on_fill(lambda f: callback_fills.append(f))

        await manager._on_broker_fill(sample_fill)

        assert len(callback_fills) == 1
        assert callback_fills[0].id == sample_fill.id

    async def test_fill_callback_error_handled(
        self, manager: OrderManager, sample_order: Order, sample_fill: Fill
    ) -> None:
        """Test fill callback errors are caught."""
        mock_order_repo = AsyncMock()
        mock_order_repo.get.return_value = sample_order
        mock_position_repo = AsyncMock()
        mock_position_repo.get.return_value = None
        mock_redis = AsyncMock()
        mock_risk_manager = MagicMock()

        manager._order_repo = mock_order_repo
        manager._position_repo = mock_position_repo
        manager._redis = mock_redis
        manager._risk_manager = mock_risk_manager

        def bad_callback(f):
            raise ValueError("Callback error")

        manager.on_fill(bad_callback)

        # Should not raise
        await manager._on_broker_fill(sample_fill)

    async def test_publish_fill_to_redis(
        self, manager: OrderManager, sample_fill: Fill
    ) -> None:
        """Test fill is published to Redis stream."""
        mock_redis = AsyncMock()
        manager._redis = mock_redis

        await manager._publish_fill(sample_fill)

        mock_redis.xadd.assert_called_once()
        args = mock_redis.xadd.call_args[0]
        assert args[0] == "stream:fills"
        call_kwargs = mock_redis.xadd.call_args[1]
        assert call_kwargs["maxlen"] == manager.config.redis.stream_maxlen
        assert call_kwargs["approximate"] is True

    async def test_publish_fill_omits_maxlen_when_unlimited(
        self, manager: OrderManager, sample_fill: Fill
    ) -> None:
        """stream_maxlen=0 disables trimming: xadd is called without maxlen
        (audit P1-8a)."""
        manager.config.redis.stream_maxlen = 0
        mock_redis = AsyncMock()
        manager._redis = mock_redis

        await manager._publish_fill(sample_fill)

        call_kwargs = mock_redis.xadd.call_args[1]
        assert "maxlen" not in call_kwargs
        assert "approximate" not in call_kwargs

    async def test_publish_fill_no_redis(
        self, manager: OrderManager, sample_fill: Fill
    ) -> None:
        """Test publish_fill handles no Redis connection."""
        manager._redis = None

        # Should not raise
        await manager._publish_fill(sample_fill)

    def test_update_price_caches(self, manager: OrderManager) -> None:
        """Test update_price caches price."""
        mock_broker = MagicMock()
        manager._broker = mock_broker

        manager.update_price("AAPL", 185.50)

        assert manager._last_prices["AAPL"] == Decimal("185.50")
        mock_broker.update_price.assert_called_once_with("AAPL", Decimal("185.50"), volume=None)

    def test_update_price_forwards_volume(self, manager: OrderManager) -> None:
        """update_price with a volume converts and forwards it to the broker."""
        mock_broker = MagicMock()
        manager._broker = mock_broker

        manager.update_price("AAPL", 185.50, volume=50000)

        mock_broker.update_price.assert_called_once_with(
            "AAPL", Decimal("185.50"), volume=Decimal("50000")
        )

    async def test_get_position(self, manager: OrderManager) -> None:
        """Test get_position delegates to repository."""
        mock_position_repo = AsyncMock()
        expected_position = Position(
            strategy_id="test",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("185.00"),
        )
        mock_position_repo.get.return_value = expected_position

        manager._position_repo = mock_position_repo

        result = await manager.get_position("test", "AAPL")

        assert result == expected_position
        mock_position_repo.get.assert_called_once_with("test", "AAPL")

    async def test_get_position_not_connected(self, manager: OrderManager) -> None:
        """Test get_position returns None when not connected."""
        result = await manager.get_position("test", "AAPL")
        assert result is None

    async def test_get_open_positions(self, manager: OrderManager) -> None:
        """Test get_open_positions delegates to repository."""
        mock_position_repo = AsyncMock()
        positions = [
            Position(
                strategy_id="test",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("185.00"),
            )
        ]
        mock_position_repo.get_open_positions.return_value = positions

        manager._position_repo = mock_position_repo

        result = await manager.get_open_positions()

        assert result == positions

    async def test_get_open_positions_with_filter(self, manager: OrderManager) -> None:
        """Test get_open_positions with strategy filter."""
        mock_position_repo = AsyncMock()
        mock_position_repo.get_open_positions.return_value = []

        manager._position_repo = mock_position_repo

        await manager.get_open_positions(strategy_id="momentum_01")

        mock_position_repo.get_open_positions.assert_called_once_with("momentum_01")

    async def test_get_open_positions_not_connected(
        self, manager: OrderManager
    ) -> None:
        """Test get_open_positions returns empty list when not connected."""
        result = await manager.get_open_positions()
        assert result == []

    def test_risk_manager_property(self, manager: OrderManager) -> None:
        """Test risk_manager property."""
        mock_risk_manager = MagicMock()
        manager._risk_manager = mock_risk_manager

        assert manager.risk_manager == mock_risk_manager

    def test_risk_manager_property_none(self, manager: OrderManager) -> None:
        """Test risk_manager property returns None before connect."""
        assert manager.risk_manager is None


class _RacyOrderRepo:
    """Fake order repo modeling a shared DB row for concurrency tests.

    get() copies the current row state after yielding control (mimicking a
    real async DB round-trip), and update() overwrites the row wholesale
    from the passed-in order — exactly what the real conditional-free
    UPDATE in OrderRepository.update() does. Without _on_broker_fill's
    _fill_lock serializing the whole read-modify-write, two concurrent
    fills that both read before either writes will lose one increment.
    """

    def __init__(self, order: Order) -> None:
        self._row = order
        self.update_calls = 0

    async def get(self, order_id: UUID) -> Order:
        await asyncio.sleep(0)
        return copy.copy(self._row)

    async def update(self, order: Order) -> None:
        await asyncio.sleep(0)
        self.update_calls += 1
        self._row.filled_quantity = order.filled_quantity
        self._row.avg_fill_price = order.avg_fill_price
        self._row.status = order.status

    async def insert_fill(self, fill: Fill) -> None:
        await asyncio.sleep(0)


class TestOrderManagerFillConcurrency:
    """Tests for the _fill_lock serialization added around _on_broker_fill
    (Audit P1-2c): two concurrent partial fills for the same order must not
    lose an increment to filled_quantity / avg_fill_price."""

    @pytest.fixture
    def mock_config(self) -> Config:
        config = Config()
        config.redis = RedisConfig(host="localhost", port=6379)
        config.database = DatabaseConfig()
        config.oms = OMSConfig(paper_mode=True, risk=RiskConfig())
        return config

    @pytest.fixture
    def manager(self, mock_config: Config) -> OrderManager:
        return OrderManager(mock_config, MagicMock())

    async def test_concurrent_partial_fills_do_not_lose_updates(
        self, manager: OrderManager
    ) -> None:
        order = Order(
            strategy_id="momentum_01",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            status=OrderStatus.SUBMITTED,
        )
        racy_repo = _RacyOrderRepo(order)
        mock_position_repo = AsyncMock()
        mock_position_repo.get.return_value = None
        mock_redis = AsyncMock()
        mock_risk_manager = MagicMock()

        manager._order_repo = racy_repo
        manager._position_repo = mock_position_repo
        manager._redis = mock_redis
        manager._risk_manager = mock_risk_manager

        fill1 = Fill(
            order_id=order.id, strategy_id=order.strategy_id, symbol="AAPL",
            side=OrderSide.BUY, quantity=Decimal("50"), price=Decimal("100"),
        )
        fill2 = Fill(
            order_id=order.id, strategy_id=order.strategy_id, symbol="AAPL",
            side=OrderSide.BUY, quantity=Decimal("50"), price=Decimal("110"),
        )

        await asyncio.gather(
            manager._on_broker_fill(fill1), manager._on_broker_fill(fill2)
        )

        assert racy_repo._row.filled_quantity == Decimal("100"), (
            "lost update: both fills must be reflected, not just one"
        )
        assert racy_repo._row.status == OrderStatus.FILLED
        # Weighted avg is order-independent: (100*50 + 110*50) / 100 = 105
        assert racy_repo._row.avg_fill_price == Decimal("105")
        # order_completed() must fire exactly once — only the fill that
        # completes the order should decrement the open-order counter.
        mock_risk_manager.order_completed.assert_called_once()


class TestOrderManagerTerminalPropagation:
    """Tests for OrderManager._on_broker_terminal (Audit P1-4).

    Fixes the open-order-counter leak where a broker-side cancel/reject
    with no fill never called order_completed(), permanently consuming a
    slot out of max_open_orders.
    """

    @pytest.fixture
    def mock_config(self) -> Config:
        config = Config()
        config.redis = RedisConfig(host="localhost", port=6379)
        config.database = DatabaseConfig()
        config.oms = OMSConfig(paper_mode=True, risk=RiskConfig())
        return config

    @pytest.fixture
    def manager(self, mock_config: Config) -> OrderManager:
        return OrderManager(mock_config, MagicMock())

    @staticmethod
    def _order(status: OrderStatus) -> Order:
        return Order(
            strategy_id="momentum_01",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("10"),
            status=status,
        )

    async def test_cancelled_stamps_and_decrements_counter(
        self, manager: OrderManager
    ) -> None:
        order = self._order(OrderStatus.SUBMITTED)
        mock_order_repo = AsyncMock()
        mock_order_repo.get.return_value = order
        mock_order_repo.update_status_if.return_value = True
        mock_risk_manager = MagicMock()

        manager._order_repo = mock_order_repo
        manager._risk_manager = mock_risk_manager

        await manager._on_broker_terminal(order.id, OrderStatus.CANCELLED)

        mock_order_repo.update_status_if.assert_called_once_with(
            order.id,
            OrderStatus.CANCELLED,
            [OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIAL],
        )
        mock_risk_manager.order_completed.assert_called_once()
        assert order.status == OrderStatus.CANCELLED

    async def test_second_cancelled_event_is_noop(self, manager: OrderManager) -> None:
        """The row is already CANCELLED (from the first event); a second
        broker notification for the same order must not double-decrement."""
        order = self._order(OrderStatus.CANCELLED)
        mock_order_repo = AsyncMock()
        mock_order_repo.get.return_value = order
        mock_risk_manager = MagicMock()

        manager._order_repo = mock_order_repo
        manager._risk_manager = mock_risk_manager

        await manager._on_broker_terminal(order.id, OrderStatus.CANCELLED)

        mock_order_repo.update_status_if.assert_not_called()
        mock_risk_manager.order_completed.assert_not_called()

    async def test_cancelled_after_full_fill_does_not_clobber(
        self, manager: OrderManager
    ) -> None:
        order = self._order(OrderStatus.FILLED)
        mock_order_repo = AsyncMock()
        mock_order_repo.get.return_value = order
        mock_risk_manager = MagicMock()

        manager._order_repo = mock_order_repo
        manager._risk_manager = mock_risk_manager

        await manager._on_broker_terminal(order.id, OrderStatus.CANCELLED)

        mock_order_repo.update_status_if.assert_not_called()
        mock_risk_manager.order_completed.assert_not_called()
        assert order.status == OrderStatus.FILLED

    async def test_missing_order_is_noop(self, manager: OrderManager) -> None:
        mock_order_repo = AsyncMock()
        mock_order_repo.get.return_value = None
        mock_risk_manager = MagicMock()

        manager._order_repo = mock_order_repo
        manager._risk_manager = mock_risk_manager

        await manager._on_broker_terminal(uuid4(), OrderStatus.CANCELLED)

        mock_order_repo.update_status_if.assert_not_called()
        mock_risk_manager.order_completed.assert_not_called()

    async def test_stamp_race_lost_does_not_call_order_completed(
        self, manager: OrderManager
    ) -> None:
        """update_status_if returning False (row moved to a terminal state
        between the get() and the conditional update) must not decrement
        the counter a second time."""
        order = self._order(OrderStatus.SUBMITTED)
        mock_order_repo = AsyncMock()
        mock_order_repo.get.return_value = order
        mock_order_repo.update_status_if.return_value = False
        mock_risk_manager = MagicMock()

        manager._order_repo = mock_order_repo
        manager._risk_manager = mock_risk_manager

        await manager._on_broker_terminal(order.id, OrderStatus.CANCELLED)

        mock_risk_manager.order_completed.assert_not_called()


class TestOrderManagerCancelOrder:
    """Tests for OrderManager.cancel_order (Audit P1-4)."""

    @pytest.fixture
    def mock_config(self) -> Config:
        config = Config()
        config.redis = RedisConfig(host="localhost", port=6379)
        config.database = DatabaseConfig()
        config.oms = OMSConfig(paper_mode=True, risk=RiskConfig())
        return config

    @pytest.fixture
    def manager(self, mock_config: Config) -> OrderManager:
        return OrderManager(mock_config, MagicMock())

    async def test_cancel_not_connected_returns_false(
        self, manager: OrderManager
    ) -> None:
        result = await manager.cancel_order(uuid4())
        assert result is False

    async def test_cancel_unknown_order_returns_false(
        self, manager: OrderManager
    ) -> None:
        mock_order_repo = AsyncMock()
        mock_order_repo.get.return_value = None
        manager._order_repo = mock_order_repo
        manager._broker = AsyncMock()

        result = await manager.cancel_order(uuid4())

        assert result is False
        manager._broker.cancel_order.assert_not_called()

    async def test_cancel_terminal_order_returns_false(
        self, manager: OrderManager
    ) -> None:
        order = Order(
            strategy_id="momentum_01", symbol="AAPL", side=OrderSide.BUY,
            quantity=Decimal("10"), status=OrderStatus.FILLED,
        )
        mock_order_repo = AsyncMock()
        mock_order_repo.get.return_value = order
        manager._order_repo = mock_order_repo
        manager._broker = AsyncMock()

        result = await manager.cancel_order(order.id)

        assert result is False
        manager._broker.cancel_order.assert_not_called()

    async def test_cancel_uses_broker_order_id_mapping(
        self, manager: OrderManager
    ) -> None:
        """Fake-IBKR path: submit_order recorded our order id -> ibkr order
        id; cancel_order must translate through that mapping, not pass our
        UUID straight through."""
        order = Order(
            strategy_id="momentum_01", symbol="AAPL", side=OrderSide.BUY,
            quantity=Decimal("10"), status=OrderStatus.SUBMITTED,
        )
        mock_order_repo = AsyncMock()
        mock_order_repo.get.return_value = order
        mock_broker = AsyncMock()
        mock_broker.cancel_order.return_value = True
        manager._order_repo = mock_order_repo
        manager._broker = mock_broker
        manager._broker_order_ids[order.id] = "7"

        result = await manager.cancel_order(order.id)

        assert result is True
        mock_broker.cancel_order.assert_called_once_with("7")

    async def test_cancel_paper_broker_path_returns_false(
        self, manager: OrderManager
    ) -> None:
        """Paper path: submit_order's mapping is our own id as a string
        (PaperBroker.submit_order returns str(order.id)); cancel_order
        always returns False since PaperBroker never holds a resting
        order."""
        order = Order(
            strategy_id="momentum_01", symbol="AAPL", side=OrderSide.BUY,
            quantity=Decimal("10"), status=OrderStatus.SUBMITTED,
        )
        mock_order_repo = AsyncMock()
        mock_order_repo.get.return_value = order
        mock_broker = AsyncMock()
        mock_broker.cancel_order.return_value = False
        manager._order_repo = mock_order_repo
        manager._broker = mock_broker
        manager._broker_order_ids[order.id] = str(order.id)

        result = await manager.cancel_order(order.id)

        assert result is False
        mock_broker.cancel_order.assert_called_once_with(str(order.id))
