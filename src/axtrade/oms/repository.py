"""OMS database repositories."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from axtrade.common.db import DatabasePool
from axtrade.common.logging import get_logger

from .types import Fill, Order, OrderSide, OrderStatus, OrderType, Position


class OrderRepository:
    """Repository for order persistence."""

    def __init__(self, pool: DatabasePool):
        self.pool = pool
        self.logger = get_logger("oms.orders")

    async def insert(self, order: Order) -> None:
        """Insert a new order."""
        query = """
            INSERT INTO orders (
                id, strategy_id, symbol, side, order_type, quantity,
                limit_price, stop_price, filled_quantity, avg_fill_price,
                status, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                order.id,
                order.strategy_id,
                order.symbol,
                order.side.value,
                order.order_type.value,
                order.quantity,
                order.limit_price,
                order.stop_price,
                order.filled_quantity,
                order.avg_fill_price,
                order.status.value,
                order.created_at,
                order.updated_at,
            )

    async def update(self, order: Order) -> None:
        """Update an existing order."""
        query = """
            UPDATE orders SET
                filled_quantity = $2,
                avg_fill_price = $3,
                status = $4,
                updated_at = $5
            WHERE id = $1
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                order.id,
                order.filled_quantity,
                order.avg_fill_price,
                order.status.value,
                datetime.now(UTC),
            )

    async def get(self, order_id: UUID) -> Optional[Order]:
        """Get an order by ID."""
        query = """
            SELECT id, strategy_id, symbol, side, order_type, quantity,
                   limit_price, stop_price, filled_quantity, avg_fill_price,
                   status, created_at, updated_at
            FROM orders WHERE id = $1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, order_id)

        if not row:
            return None

        return Order(
            id=row["id"],
            strategy_id=row["strategy_id"],
            symbol=row["symbol"],
            side=OrderSide(row["side"]),
            order_type=OrderType(row["order_type"]),
            quantity=row["quantity"],
            limit_price=row["limit_price"],
            stop_price=row["stop_price"],
            filled_quantity=row["filled_quantity"],
            avg_fill_price=row["avg_fill_price"],
            status=OrderStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def get_by_strategy(
        self, strategy_id: str, status: Optional[OrderStatus] = None, limit: int = 100
    ) -> list[Order]:
        """Get orders for a strategy."""
        if status:
            query = """
                SELECT id, strategy_id, symbol, side, order_type, quantity,
                       limit_price, stop_price, filled_quantity, avg_fill_price,
                       status, created_at, updated_at
                FROM orders WHERE strategy_id = $1 AND status = $2
                ORDER BY created_at DESC LIMIT $3
            """
            params = (strategy_id, status.value, limit)
        else:
            query = """
                SELECT id, strategy_id, symbol, side, order_type, quantity,
                       limit_price, stop_price, filled_quantity, avg_fill_price,
                       status, created_at, updated_at
                FROM orders WHERE strategy_id = $1
                ORDER BY created_at DESC LIMIT $2
            """
            params = (strategy_id, limit)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [
            Order(
                id=row["id"],
                strategy_id=row["strategy_id"],
                symbol=row["symbol"],
                side=OrderSide(row["side"]),
                order_type=OrderType(row["order_type"]),
                quantity=row["quantity"],
                limit_price=row["limit_price"],
                stop_price=row["stop_price"],
                filled_quantity=row["filled_quantity"],
                avg_fill_price=row["avg_fill_price"],
                status=OrderStatus(row["status"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    async def insert_fill(self, fill: Fill) -> None:
        """Insert a fill record."""
        query = """
            INSERT INTO fills (
                id, order_id, strategy_id, symbol, side, quantity, price, commission, filled_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                fill.id,
                fill.order_id,
                fill.strategy_id,
                fill.symbol,
                fill.side.value,
                fill.quantity,
                fill.price,
                fill.commission,
                fill.filled_at,
            )

    async def get_recent_orders(
        self, strategy_id: Optional[str] = None, status: Optional[str] = None, limit: int = 50
    ) -> list[Order]:
        """Get recent orders with optional filters."""
        conditions = []
        params: list = []
        param_idx = 1

        if strategy_id:
            conditions.append(f"strategy_id = ${param_idx}")
            params.append(strategy_id)
            param_idx += 1

        if status:
            conditions.append(f"status = ${param_idx}")
            params.append(status)
            param_idx += 1

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        query = f"""
            SELECT id, strategy_id, symbol, side, order_type, quantity,
                   limit_price, stop_price, filled_quantity, avg_fill_price,
                   status, created_at, updated_at
            FROM orders {where_clause}
            ORDER BY created_at DESC LIMIT ${param_idx}
        """
        params.append(limit)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [
            Order(
                id=row["id"],
                strategy_id=row["strategy_id"],
                symbol=row["symbol"],
                side=OrderSide(row["side"]),
                order_type=OrderType(row["order_type"]),
                quantity=row["quantity"],
                limit_price=row["limit_price"],
                stop_price=row["stop_price"],
                filled_quantity=row["filled_quantity"],
                avg_fill_price=row["avg_fill_price"],
                status=OrderStatus(row["status"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    async def get_fills_for_order(self, order_id: UUID) -> list[Fill]:
        """Get all fills for an order."""
        query = """
            SELECT id, order_id, strategy_id, symbol, side, quantity, price, commission, filled_at
            FROM fills WHERE order_id = $1 ORDER BY filled_at
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, order_id)

        return [
            Fill(
                id=row["id"],
                order_id=row["order_id"],
                strategy_id=row["strategy_id"],
                symbol=row["symbol"],
                side=OrderSide(row["side"]),
                quantity=row["quantity"],
                price=row["price"],
                commission=row["commission"],
                filled_at=row["filled_at"],
            )
            for row in rows
        ]

    async def get_recent_fills(
        self, strategy_id: Optional[str] = None, limit: int = 50
    ) -> list[Fill]:
        """Get recent fills with optional strategy filter."""
        if strategy_id:
            query = """
                SELECT id, order_id, strategy_id, symbol, side, quantity, price, commission, filled_at
                FROM fills WHERE strategy_id = $1 ORDER BY filled_at DESC LIMIT $2
            """
            params = (strategy_id, limit)
        else:
            query = """
                SELECT id, order_id, strategy_id, symbol, side, quantity, price, commission, filled_at
                FROM fills ORDER BY filled_at DESC LIMIT $1
            """
            params = (limit,)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [
            Fill(
                id=row["id"],
                order_id=row["order_id"],
                strategy_id=row["strategy_id"],
                symbol=row["symbol"],
                side=OrderSide(row["side"]),
                quantity=row["quantity"],
                price=row["price"],
                commission=row["commission"],
                filled_at=row["filled_at"],
            )
            for row in rows
        ]

    async def get_daily_realized_pnl(
        self, strategy_id: Optional[str] = None
    ) -> Decimal:
        """Calculate realized P&L from today's fills."""
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

        if strategy_id:
            query = """
                SELECT COALESCE(SUM(
                    CASE WHEN side = 'sell' THEN quantity * price - commission
                         ELSE -(quantity * price + commission)
                    END
                ), 0) as pnl
                FROM fills
                WHERE strategy_id = $1 AND filled_at >= $2
            """
            params = (strategy_id, today_start)
        else:
            query = """
                SELECT COALESCE(SUM(
                    CASE WHEN side = 'sell' THEN quantity * price - commission
                         ELSE -(quantity * price + commission)
                    END
                ), 0) as pnl
                FROM fills WHERE filled_at >= $1
            """
            params = (today_start,)

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)

        return Decimal(str(row["pnl"])) if row else Decimal("0")

    async def get_daily_pnl_series(
        self, limit: int = 30, strategy_id: Optional[str] = None
    ) -> list[Decimal]:
        """Get daily P&L series for rolling calculations.

        Args:
            limit: Number of days to return
            strategy_id: Optional strategy filter

        Returns:
            List of daily P&L values (most recent first)
        """
        if strategy_id:
            query = """
                SELECT DATE(filled_at) as day,
                       SUM(CASE WHEN side = 'sell' THEN quantity * price - commission
                                ELSE -(quantity * price + commission) END) as pnl
                FROM fills
                WHERE strategy_id = $1
                GROUP BY DATE(filled_at)
                ORDER BY day DESC
                LIMIT $2
            """
            params = (strategy_id, limit)
        else:
            query = """
                SELECT DATE(filled_at) as day,
                       SUM(CASE WHEN side = 'sell' THEN quantity * price - commission
                                ELSE -(quantity * price + commission) END) as pnl
                FROM fills
                GROUP BY DATE(filled_at)
                ORDER BY day DESC
                LIMIT $1
            """
            params = (limit,)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [Decimal(str(row["pnl"])) for row in rows]


class PositionRepository:
    """Repository for position persistence."""

    def __init__(self, pool: DatabasePool):
        self.pool = pool
        self.logger = get_logger("oms.positions")

    async def get(self, strategy_id: str, symbol: str) -> Optional[Position]:
        """Get a position by strategy and symbol."""
        query = """
            SELECT id, strategy_id, symbol, side, quantity, avg_entry_price,
                   current_price, unrealized_pnl, realized_pnl, opened_at, closed_at, updated_at
            FROM positions
            WHERE strategy_id = $1 AND symbol = $2
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, strategy_id, symbol)

        if not row:
            return None

        return Position(
            id=row["id"],
            strategy_id=row["strategy_id"],
            symbol=row["symbol"],
            side=row["side"],
            quantity=row["quantity"],
            avg_entry_price=row["avg_entry_price"],
            current_price=row["current_price"],
            unrealized_pnl=row["unrealized_pnl"],
            realized_pnl=row["realized_pnl"],
            opened_at=row["opened_at"],
            closed_at=row["closed_at"],
            updated_at=row["updated_at"],
        )

    async def get_open_positions(self, strategy_id: Optional[str] = None) -> list[Position]:
        """Get all open positions, optionally filtered by strategy."""
        if strategy_id:
            query = """
                SELECT id, strategy_id, symbol, side, quantity, avg_entry_price,
                       current_price, unrealized_pnl, realized_pnl, opened_at, closed_at, updated_at
                FROM positions
                WHERE strategy_id = $1 AND closed_at IS NULL AND quantity > 0
                ORDER BY opened_at DESC
            """
            params = (strategy_id,)
        else:
            query = """
                SELECT id, strategy_id, symbol, side, quantity, avg_entry_price,
                       current_price, unrealized_pnl, realized_pnl, opened_at, closed_at, updated_at
                FROM positions
                WHERE closed_at IS NULL AND quantity > 0
                ORDER BY opened_at DESC
            """
            params = ()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [
            Position(
                id=row["id"],
                strategy_id=row["strategy_id"],
                symbol=row["symbol"],
                side=row["side"],
                quantity=row["quantity"],
                avg_entry_price=row["avg_entry_price"],
                current_price=row["current_price"],
                unrealized_pnl=row["unrealized_pnl"],
                realized_pnl=row["realized_pnl"],
                opened_at=row["opened_at"],
                closed_at=row["closed_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    async def upsert(self, position: Position) -> None:
        """Insert or update a position."""
        query = """
            INSERT INTO positions (
                strategy_id, symbol, side, quantity, avg_entry_price,
                current_price, unrealized_pnl, realized_pnl, opened_at, closed_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (strategy_id, symbol)
            DO UPDATE SET
                quantity = EXCLUDED.quantity,
                avg_entry_price = EXCLUDED.avg_entry_price,
                current_price = EXCLUDED.current_price,
                unrealized_pnl = EXCLUDED.unrealized_pnl,
                realized_pnl = EXCLUDED.realized_pnl,
                closed_at = EXCLUDED.closed_at,
                updated_at = EXCLUDED.updated_at
        """
        now = datetime.now(UTC)
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                position.strategy_id,
                position.symbol,
                position.side,
                position.quantity,
                position.avg_entry_price,
                position.current_price,
                position.unrealized_pnl,
                position.realized_pnl,
                position.opened_at or now,
                position.closed_at,
                now,
            )

    async def update_price(
        self, strategy_id: str, symbol: str, current_price: Decimal
    ) -> None:
        """Update position current price and P&L."""
        position = await self.get(strategy_id, symbol)
        if not position:
            return

        unrealized_pnl = position.calculate_unrealized_pnl(current_price)
        position.current_price = current_price
        position.unrealized_pnl = unrealized_pnl
        await self.upsert(position)
