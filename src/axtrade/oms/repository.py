"""OMS database repositories."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from axtrade.common.db import DatabasePool
from axtrade.common.logging import get_logger

from .types import Fill, Order, OrderSide, OrderStatus, OrderType, Position


def _fifo_daily_realized(rows) -> dict[str, Decimal]:
    """Match buy/sell fills FIFO per (strategy_id, symbol), bucketed by day.

    Shared FIFO core for `get_daily_pnl_series`, `get_daily_realized_pnl`,
    and `get_total_realized_pnl` so the three no longer carry independent
    (and driftable) copies of the same matching logic. Buy lots carry
    forward across days until a later sell consumes them; commissions are
    prorated across partial matches. Sells with no matching buy lot are
    skipped (unmatched short sells contribute no realized P&L here).

    Args:
        rows: Fill rows (asyncpg records or dict-likes) with keys
            strategy_id, symbol, side, quantity, price, commission,
            filled_at, ordered oldest-first.

    Returns:
        Dict mapping ISO day string ("%Y-%m-%d") to realized P&L for fills
        matched (sold) that day.
    """
    # Track buy lots per strategy+symbol: {(strategy, symbol): [(qty, price, commission)]}
    buy_lots: dict[tuple[str, str], list[tuple[Decimal, Decimal, Decimal]]] = {}
    daily_pnl: dict[str, Decimal] = {}

    for row in rows:
        key = (row["strategy_id"], row["symbol"])
        qty = Decimal(str(row["quantity"]))
        price = Decimal(str(row["price"]))
        commission = Decimal(str(row["commission"]))
        day = row["filled_at"].strftime("%Y-%m-%d")

        if row["side"] == "buy":
            if key not in buy_lots:
                buy_lots[key] = []
            buy_lots[key].append((qty, price, commission))
        else:
            # Sell - match against buys in FIFO order
            if key not in buy_lots:
                continue

            remaining_sell_qty = qty
            sell_commission = commission

            while remaining_sell_qty > 0 and buy_lots[key]:
                buy_qty, buy_price, buy_commission = buy_lots[key][0]
                match_qty = min(remaining_sell_qty, buy_qty)

                trade_pnl = (price - buy_price) * match_qty
                buy_comm_portion = buy_commission * (match_qty / buy_qty)
                sell_comm_portion = sell_commission * (match_qty / qty)
                trade_pnl -= (buy_comm_portion + sell_comm_portion)

                if day not in daily_pnl:
                    daily_pnl[day] = Decimal("0")
                daily_pnl[day] += trade_pnl

                remaining_sell_qty -= match_qty

                if match_qty >= buy_qty:
                    buy_lots[key].pop(0)
                else:
                    new_buy_qty = buy_qty - match_qty
                    new_buy_commission = buy_commission * (new_buy_qty / buy_qty)
                    buy_lots[key][0] = (new_buy_qty, buy_price, new_buy_commission)

    return daily_pnl


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

    async def update_status_if(
        self, order_id: UUID, new_status: OrderStatus, expected: list[OrderStatus]
    ) -> bool:
        """Conditionally update an order's status in a single atomic UPDATE.

        Only applies when the row's current status is one of `expected`,
        closing the race where two writers (e.g. the submit-path SUBMITTED
        stamp and a detached async-broker fill/cancel callback) each do a
        read-then-write and clobber each other. Returns True iff a row was
        actually updated.

        Args:
            order_id: Order to update
            new_status: Status to set
            expected: Statuses the row must currently have for the update
                to apply

        Returns:
            True if the row matched and was updated, False otherwise
        """
        query = """
            UPDATE orders SET status = $1, updated_at = $4
            WHERE id = $2 AND status = ANY($3::text[])
            RETURNING id
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                query,
                new_status.value,
                order_id,
                [status.value for status in expected],
                datetime.now(UTC),
            )
        return row is not None

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
        """Calculate realized P&L from today's fills using FIFO matching.

        Realized P&L is calculated by matching sell fills against buy fills
        in FIFO order for each strategy+symbol combination. Only P&L from
        sells that occurred today is included.

        Args:
            strategy_id: Optional strategy filter

        Returns:
            Total realized P&L for today
        """
        # Fetch all fills to properly match buys and sells
        # We need historical buys to calculate cost basis for today's sells
        if strategy_id:
            query = """
                SELECT strategy_id, symbol, side, quantity, price, commission, filled_at
                FROM fills
                WHERE strategy_id = $1
                ORDER BY filled_at ASC
            """
            params = (strategy_id,)
        else:
            query = """
                SELECT strategy_id, symbol, side, quantity, price, commission, filled_at
                FROM fills
                ORDER BY filled_at ASC
            """
            params = ()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params) if params else await conn.fetch(query)

        daily_pnl = _fifo_daily_realized(rows)
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        return daily_pnl.get(today, Decimal("0"))

    async def get_total_realized_pnl(
        self, strategy_id: Optional[str] = None
    ) -> Decimal:
        """Calculate cumulative realized P&L across all fills using FIFO matching.

        Unlike summing `positions.realized_pnl` over currently-open positions
        (which misses fully-closed positions and double-counts when combined
        with today's realized P&L), this replays every fill through FIFO
        matching and sums the realized P&L across all days - both open and
        closed positions are accounted for correctly.

        Args:
            strategy_id: Optional strategy filter

        Returns:
            Total realized P&L across all fills
        """
        if strategy_id:
            query = """
                SELECT strategy_id, symbol, side, quantity, price, commission, filled_at
                FROM fills
                WHERE strategy_id = $1
                ORDER BY filled_at ASC
            """
            params = (strategy_id,)
        else:
            query = """
                SELECT strategy_id, symbol, side, quantity, price, commission, filled_at
                FROM fills
                ORDER BY filled_at ASC
            """
            params = ()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params) if params else await conn.fetch(query)

        daily_pnl = _fifo_daily_realized(rows)
        if not daily_pnl:
            return Decimal("0")
        return sum(daily_pnl.values(), Decimal("0"))

    async def get_daily_pnl_series(
        self, limit: int = 30, strategy_id: Optional[str] = None
    ) -> list[Decimal]:
        """Get daily P&L series for rolling calculations using FIFO matching.

        Calculates realized P&L per day by matching sells against buys in FIFO
        order. Buy lots carry forward across days until matched.

        Args:
            limit: Number of days to return
            strategy_id: Optional strategy filter

        Returns:
            List of daily P&L values (most recent first)
        """
        # Fetch all fills ordered by time
        if strategy_id:
            query = """
                SELECT strategy_id, symbol, side, quantity, price, commission, filled_at
                FROM fills
                WHERE strategy_id = $1
                ORDER BY filled_at ASC
            """
            params = (strategy_id,)
        else:
            query = """
                SELECT strategy_id, symbol, side, quantity, price, commission, filled_at
                FROM fills
                ORDER BY filled_at ASC
            """
            params = ()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params) if params else await conn.fetch(query)

        daily_pnl = _fifo_daily_realized(rows)

        # Sort by date descending and return limited results
        sorted_days = sorted(daily_pnl.keys(), reverse=True)[:limit]
        return [daily_pnl[day] for day in sorted_days]

    async def get_fills_chronological(
        self, strategy_id: Optional[str] = None
    ) -> list[Fill]:
        """Get all fills ordered oldest-first, for FIFO trade pairing.

        FIFO trade pairing (`axtrade.analytics.pair_fills_fifo`) needs the
        full fill history, oldest first: a recency-limited window (like
        `get_recent_fills`) would drop early buy lots and mis-pair the sells
        that close them.

        Args:
            strategy_id: Optional strategy filter

        Returns:
            All fills for the strategy (or all strategies), oldest first
        """
        if strategy_id:
            query = """
                SELECT id, order_id, strategy_id, symbol, side, quantity, price, commission, filled_at
                FROM fills WHERE strategy_id = $1 ORDER BY filled_at ASC
            """
            params = (strategy_id,)
        else:
            query = """
                SELECT id, order_id, strategy_id, symbol, side, quantity, price, commission, filled_at
                FROM fills ORDER BY filled_at ASC
            """
            params = ()

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params) if params else await conn.fetch(query)

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
                side = EXCLUDED.side,
                quantity = EXCLUDED.quantity,
                avg_entry_price = EXCLUDED.avg_entry_price,
                current_price = EXCLUDED.current_price,
                unrealized_pnl = EXCLUDED.unrealized_pnl,
                realized_pnl = EXCLUDED.realized_pnl,
                opened_at = EXCLUDED.opened_at,
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
