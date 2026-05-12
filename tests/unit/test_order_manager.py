"""Unit tests for OrderManager.

Tests for order submission, fill handling, and position management.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from axtrade.common import Config, DatabaseConfig, OMSConfig, RedisConfig, RiskConfig
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
        mock_broker.update_price.assert_called_once_with("AAPL", Decimal("185.50"))

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
