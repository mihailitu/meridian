"""Unit tests for OMS repository layer.

Tests for OrderRepository and PositionRepository database operations.
Uses mocking to avoid requiring a real database.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from axtrade.oms.repository import OrderRepository, PositionRepository
from axtrade.oms.types import Fill, Order, OrderSide, OrderStatus, OrderType, Position


class TestOrderRepository:
    """Tests for OrderRepository."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock database pool."""
        pool = MagicMock()
        pool.acquire = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool: MagicMock) -> OrderRepository:
        """Create OrderRepository with mock pool."""
        return OrderRepository(mock_pool)

    @pytest.fixture
    def sample_order(self) -> Order:
        """Create a sample order for testing."""
        return Order(
            id=uuid4(),
            strategy_id="momentum_01",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            order_type=OrderType.MARKET,
            status=OrderStatus.PENDING,
            filled_quantity=Decimal("0"),
            avg_fill_price=None,
            created_at=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
            updated_at=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
        )

    @pytest.fixture
    def sample_fill(self) -> Fill:
        """Create a sample fill for testing."""
        return Fill(
            id=uuid4(),
            order_id=uuid4(),
            strategy_id="momentum_01",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            price=Decimal("185.50"),
            commission=Decimal("1.00"),
            filled_at=datetime(2024, 1, 15, 9, 30, 5, tzinfo=timezone.utc),
        )

    async def test_insert_order_executes_query(
        self, repo: OrderRepository, mock_pool: MagicMock, sample_order: Order
    ) -> None:
        """Test that insert executes the correct SQL query."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        await repo.insert(sample_order)

        mock_conn.execute.assert_called_once()
        args = mock_conn.execute.call_args[0]
        assert "INSERT INTO orders" in args[0]
        assert args[1] == sample_order.id
        assert args[2] == sample_order.strategy_id
        assert args[3] == sample_order.symbol
        assert args[4] == sample_order.side.value
        assert args[5] == sample_order.order_type.value
        assert args[6] == sample_order.quantity

    async def test_insert_order_with_limit_price(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Test insert with limit order parameters."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        order = Order(
            strategy_id="momentum_01",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal("185.00"),
        )

        await repo.insert(order)

        args = mock_conn.execute.call_args[0]
        assert args[7] == Decimal("185.00")  # limit_price position

    async def test_update_order_status(
        self, repo: OrderRepository, mock_pool: MagicMock, sample_order: Order
    ) -> None:
        """Test that update modifies order status correctly."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        sample_order.status = OrderStatus.FILLED
        sample_order.filled_quantity = Decimal("100")
        sample_order.avg_fill_price = Decimal("185.50")

        await repo.update(sample_order)

        mock_conn.execute.assert_called_once()
        args = mock_conn.execute.call_args[0]
        assert "UPDATE orders SET" in args[0]
        assert args[1] == sample_order.id
        assert args[2] == Decimal("100")  # filled_quantity
        assert args[3] == Decimal("185.50")  # avg_fill_price
        assert args[4] == "filled"  # status

    async def test_get_order_by_id(
        self, repo: OrderRepository, mock_pool: MagicMock, sample_order: Order
    ) -> None:
        """Test retrieval of order by ID."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        mock_conn.fetchrow.return_value = {
            "id": sample_order.id,
            "strategy_id": sample_order.strategy_id,
            "symbol": sample_order.symbol,
            "side": sample_order.side.value,
            "order_type": sample_order.order_type.value,
            "quantity": sample_order.quantity,
            "limit_price": None,
            "stop_price": None,
            "filled_quantity": sample_order.filled_quantity,
            "avg_fill_price": None,
            "status": sample_order.status.value,
            "created_at": sample_order.created_at,
            "updated_at": sample_order.updated_at,
        }

        result = await repo.get(sample_order.id)

        assert result is not None
        assert result.id == sample_order.id
        assert result.symbol == "AAPL"
        assert result.side == OrderSide.BUY
        assert result.status == OrderStatus.PENDING

    async def test_get_order_not_found(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Test get returns None for non-existent order."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_conn.fetchrow.return_value = None

        result = await repo.get(uuid4())

        assert result is None

    async def test_get_orders_by_strategy(
        self, repo: OrderRepository, mock_pool: MagicMock, sample_order: Order
    ) -> None:
        """Test filtered query by strategy ID."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        mock_conn.fetch.return_value = [
            {
                "id": sample_order.id,
                "strategy_id": "momentum_01",
                "symbol": "AAPL",
                "side": "buy",
                "order_type": "market",
                "quantity": Decimal("100"),
                "limit_price": None,
                "stop_price": None,
                "filled_quantity": Decimal("100"),
                "avg_fill_price": Decimal("185.50"),
                "status": "filled",
                "created_at": sample_order.created_at,
                "updated_at": sample_order.updated_at,
            }
        ]

        result = await repo.get_by_strategy("momentum_01")

        assert len(result) == 1
        assert result[0].strategy_id == "momentum_01"
        mock_conn.fetch.assert_called_once()

    async def test_get_orders_by_strategy_with_status_filter(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Test filtered query by strategy ID and status."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_conn.fetch.return_value = []

        await repo.get_by_strategy("momentum_01", status=OrderStatus.FILLED, limit=50)

        args = mock_conn.fetch.call_args[0]
        assert "status = $2" in args[0]
        assert args[1] == "momentum_01"
        assert args[2] == "filled"
        assert args[3] == 50

    async def test_insert_fill(
        self, repo: OrderRepository, mock_pool: MagicMock, sample_fill: Fill
    ) -> None:
        """Test fill persistence."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        await repo.insert_fill(sample_fill)

        mock_conn.execute.assert_called_once()
        args = mock_conn.execute.call_args[0]
        assert "INSERT INTO fills" in args[0]
        assert args[1] == sample_fill.id
        assert args[2] == sample_fill.order_id
        assert args[3] == sample_fill.strategy_id
        assert args[4] == sample_fill.symbol
        assert args[5] == sample_fill.side.value
        assert args[6] == sample_fill.quantity
        assert args[7] == sample_fill.price
        assert args[8] == sample_fill.commission

    async def test_get_recent_orders_no_filters(
        self, repo: OrderRepository, mock_pool: MagicMock, sample_order: Order
    ) -> None:
        """Test get_recent_orders without filters."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        mock_conn.fetch.return_value = [
            {
                "id": sample_order.id,
                "strategy_id": sample_order.strategy_id,
                "symbol": sample_order.symbol,
                "side": sample_order.side.value,
                "order_type": sample_order.order_type.value,
                "quantity": sample_order.quantity,
                "limit_price": None,
                "stop_price": None,
                "filled_quantity": Decimal("0"),
                "avg_fill_price": None,
                "status": sample_order.status.value,
                "created_at": sample_order.created_at,
                "updated_at": sample_order.updated_at,
            }
        ]

        result = await repo.get_recent_orders(limit=50)

        assert len(result) == 1
        args = mock_conn.fetch.call_args[0]
        # No WHERE clause when no filters
        assert "WHERE" not in args[0] or args[0].count("WHERE") == 0

    async def test_get_recent_orders_with_filters(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Test get_recent_orders with status and symbol filters."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_conn.fetch.return_value = []

        await repo.get_recent_orders(
            strategy_id="momentum_01", status="filled", limit=10
        )

        args = mock_conn.fetch.call_args[0]
        assert "WHERE" in args[0]
        assert "strategy_id = $1" in args[0]
        assert "status = $2" in args[0]

    async def test_get_fills_for_order(
        self, repo: OrderRepository, mock_pool: MagicMock, sample_fill: Fill
    ) -> None:
        """Test fill retrieval for an order."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        mock_conn.fetch.return_value = [
            {
                "id": sample_fill.id,
                "order_id": sample_fill.order_id,
                "strategy_id": sample_fill.strategy_id,
                "symbol": sample_fill.symbol,
                "side": sample_fill.side.value,
                "quantity": sample_fill.quantity,
                "price": sample_fill.price,
                "commission": sample_fill.commission,
                "filled_at": sample_fill.filled_at,
            }
        ]

        result = await repo.get_fills_for_order(sample_fill.order_id)

        assert len(result) == 1
        assert result[0].id == sample_fill.id
        assert result[0].price == Decimal("185.50")
        assert result[0].side == OrderSide.BUY

    async def test_get_recent_fills_no_filter(
        self, repo: OrderRepository, mock_pool: MagicMock, sample_fill: Fill
    ) -> None:
        """Test get_recent_fills without strategy filter."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        mock_conn.fetch.return_value = [
            {
                "id": sample_fill.id,
                "order_id": sample_fill.order_id,
                "strategy_id": sample_fill.strategy_id,
                "symbol": sample_fill.symbol,
                "side": sample_fill.side.value,
                "quantity": sample_fill.quantity,
                "price": sample_fill.price,
                "commission": sample_fill.commission,
                "filled_at": sample_fill.filled_at,
            }
        ]

        result = await repo.get_recent_fills(limit=25)

        assert len(result) == 1
        args = mock_conn.fetch.call_args[0]
        assert "WHERE" not in args[0]

    async def test_get_recent_fills_with_strategy_filter(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Test get_recent_fills with strategy filter."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_conn.fetch.return_value = []

        await repo.get_recent_fills(strategy_id="momentum_01", limit=10)

        args = mock_conn.fetch.call_args[0]
        assert "WHERE strategy_id = $1" in args[0]
        assert args[1] == "momentum_01"

    async def test_get_daily_realized_pnl_calculates_fifo(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Test daily realized P&L uses FIFO matching."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        now = datetime.now(timezone.utc)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Buy 100 @ $100, then sell 100 @ $110 (today) = $1000 profit minus commissions
        mock_conn.fetch.return_value = [
            {
                "strategy_id": "test",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": Decimal("100"),
                "price": Decimal("100"),
                "commission": Decimal("1"),
                "filled_at": today,
            },
            {
                "strategy_id": "test",
                "symbol": "AAPL",
                "side": "sell",
                "quantity": Decimal("100"),
                "price": Decimal("110"),
                "commission": Decimal("1"),
                "filled_at": now,
            },
        ]

        result = await repo.get_daily_realized_pnl()

        # P&L = (110 - 100) * 100 - 1 - 1 = $998
        assert result == Decimal("998")

    async def test_get_daily_realized_pnl_with_strategy_filter(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Test daily realized P&L with strategy filter."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_conn.fetch.return_value = []

        await repo.get_daily_realized_pnl(strategy_id="momentum_01")

        args = mock_conn.fetch.call_args[0]
        assert "WHERE strategy_id = $1" in args[0]

    async def test_get_daily_pnl_series(
        self, repo: OrderRepository, mock_pool: MagicMock
    ) -> None:
        """Test daily P&L series calculation."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        day1 = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)
        day2 = datetime(2024, 1, 16, 10, 0, tzinfo=timezone.utc)

        mock_conn.fetch.return_value = [
            {
                "strategy_id": "test",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": Decimal("100"),
                "price": Decimal("100"),
                "commission": Decimal("1"),
                "filled_at": day1,
            },
            {
                "strategy_id": "test",
                "symbol": "AAPL",
                "side": "sell",
                "quantity": Decimal("100"),
                "price": Decimal("105"),
                "commission": Decimal("1"),
                "filled_at": day2,
            },
        ]

        result = await repo.get_daily_pnl_series(limit=30)

        # Only day2 has realized P&L
        assert len(result) == 1
        # P&L = (105 - 100) * 100 - 2 = $498
        assert result[0] == Decimal("498")


class TestPositionRepository:
    """Tests for PositionRepository."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock database pool."""
        pool = MagicMock()
        pool.acquire = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool: MagicMock) -> PositionRepository:
        """Create PositionRepository with mock pool."""
        return PositionRepository(mock_pool)

    @pytest.fixture
    def sample_position(self) -> Position:
        """Create a sample position for testing."""
        return Position(
            id=uuid4(),
            strategy_id="momentum_01",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("185.00"),
            current_price=Decimal("186.00"),
            unrealized_pnl=Decimal("100.00"),
            realized_pnl=Decimal("50.00"),
            opened_at=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
            closed_at=None,
            updated_at=datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
        )

    async def test_get_position(
        self, repo: PositionRepository, mock_pool: MagicMock, sample_position: Position
    ) -> None:
        """Test retrieval by strategy+symbol."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        mock_conn.fetchrow.return_value = {
            "id": sample_position.id,
            "strategy_id": sample_position.strategy_id,
            "symbol": sample_position.symbol,
            "side": sample_position.side,
            "quantity": sample_position.quantity,
            "avg_entry_price": sample_position.avg_entry_price,
            "current_price": sample_position.current_price,
            "unrealized_pnl": sample_position.unrealized_pnl,
            "realized_pnl": sample_position.realized_pnl,
            "opened_at": sample_position.opened_at,
            "closed_at": sample_position.closed_at,
            "updated_at": sample_position.updated_at,
        }

        result = await repo.get("momentum_01", "AAPL")

        assert result is not None
        assert result.strategy_id == "momentum_01"
        assert result.symbol == "AAPL"
        assert result.side == "long"
        assert result.quantity == Decimal("100")

    async def test_get_position_not_found(
        self, repo: PositionRepository, mock_pool: MagicMock
    ) -> None:
        """Test get returns None for non-existent position."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_conn.fetchrow.return_value = None

        result = await repo.get("unknown", "INVALID")

        assert result is None

    async def test_get_open_positions(
        self, repo: PositionRepository, mock_pool: MagicMock, sample_position: Position
    ) -> None:
        """Test open positions query."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        mock_conn.fetch.return_value = [
            {
                "id": sample_position.id,
                "strategy_id": sample_position.strategy_id,
                "symbol": sample_position.symbol,
                "side": sample_position.side,
                "quantity": sample_position.quantity,
                "avg_entry_price": sample_position.avg_entry_price,
                "current_price": sample_position.current_price,
                "unrealized_pnl": sample_position.unrealized_pnl,
                "realized_pnl": sample_position.realized_pnl,
                "opened_at": sample_position.opened_at,
                "closed_at": None,
                "updated_at": sample_position.updated_at,
            }
        ]

        result = await repo.get_open_positions()

        assert len(result) == 1
        assert result[0].symbol == "AAPL"
        args = mock_conn.fetch.call_args[0]
        assert "closed_at IS NULL" in args[0]
        assert "quantity > 0" in args[0]

    async def test_get_open_positions_with_strategy_filter(
        self, repo: PositionRepository, mock_pool: MagicMock
    ) -> None:
        """Test open positions with strategy filter."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_conn.fetch.return_value = []

        await repo.get_open_positions(strategy_id="momentum_01")

        args = mock_conn.fetch.call_args[0]
        assert "strategy_id = $1" in args[0]

    async def test_upsert_new_position(
        self, repo: PositionRepository, mock_pool: MagicMock, sample_position: Position
    ) -> None:
        """Test insert of new position."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        await repo.upsert(sample_position)

        mock_conn.execute.assert_called_once()
        args = mock_conn.execute.call_args[0]
        assert "INSERT INTO positions" in args[0]
        assert "ON CONFLICT" in args[0]
        assert args[1] == sample_position.strategy_id
        assert args[2] == sample_position.symbol
        assert args[3] == sample_position.side
        assert args[4] == sample_position.quantity

    async def test_upsert_existing_position(
        self, repo: PositionRepository, mock_pool: MagicMock
    ) -> None:
        """Test update of existing position via upsert."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        position = Position(
            strategy_id="momentum_01",
            symbol="AAPL",
            side="long",
            quantity=Decimal("200"),  # Updated quantity
            avg_entry_price=Decimal("185.00"),
            current_price=Decimal("190.00"),
            unrealized_pnl=Decimal("1000.00"),
        )

        await repo.upsert(position)

        args = mock_conn.execute.call_args[0]
        assert "DO UPDATE SET" in args[0]
        assert "quantity = EXCLUDED.quantity" in args[0]

    async def test_update_price(
        self, repo: PositionRepository, mock_pool: MagicMock, sample_position: Position
    ) -> None:
        """Test price/pnl update."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        # First call: get position
        mock_conn.fetchrow.return_value = {
            "id": sample_position.id,
            "strategy_id": sample_position.strategy_id,
            "symbol": sample_position.symbol,
            "side": sample_position.side,
            "quantity": sample_position.quantity,
            "avg_entry_price": sample_position.avg_entry_price,
            "current_price": sample_position.current_price,
            "unrealized_pnl": sample_position.unrealized_pnl,
            "realized_pnl": sample_position.realized_pnl,
            "opened_at": sample_position.opened_at,
            "closed_at": sample_position.closed_at,
            "updated_at": sample_position.updated_at,
        }

        await repo.update_price("momentum_01", "AAPL", Decimal("190.00"))

        # Should have called upsert after get
        assert mock_conn.execute.called

    async def test_update_price_no_position(
        self, repo: PositionRepository, mock_pool: MagicMock
    ) -> None:
        """Test update_price does nothing when position not found."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_conn.fetchrow.return_value = None

        await repo.update_price("unknown", "INVALID", Decimal("100.00"))

        # Should not attempt upsert
        mock_conn.execute.assert_not_called()
