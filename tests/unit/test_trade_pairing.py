"""Unit tests for FIFO trade pairing.

Covers `axtrade.analytics.trades.pair_fills_fifo` (fill -> TradeRecord
round-trip pairing used by the live API) and the shared FIFO core it was
extracted alongside, `axtrade.oms.repository._fifo_daily_realized`.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from axtrade.analytics import pair_fills_fifo
from axtrade.oms.repository import _fifo_daily_realized
from axtrade.oms.types import Fill, OrderSide

NOW = datetime(2026, 7, 1, 14, 30, tzinfo=timezone.utc)


def _fill(strategy_id, symbol, side, quantity, price, commission, filled_at):
    """Build a Fill with Decimal-coerced numeric fields."""
    return Fill(
        id=uuid4(),
        order_id=uuid4(),
        strategy_id=strategy_id,
        symbol=symbol,
        side=side,
        quantity=Decimal(str(quantity)),
        price=Decimal(str(price)),
        commission=Decimal(str(commission)),
        filled_at=filled_at,
    )


class TestPairFillsFifo:
    """Tests for pair_fills_fifo."""

    def test_simple_round_trip(self) -> None:
        """A single buy fully closed by a single sell produces one trade."""
        buy = _fill("s1", "AAPL", OrderSide.BUY, 100, "185.00", "1.00", NOW)
        sell = _fill(
            "s1", "AAPL", OrderSide.SELL, 100, "190.00", "1.00", NOW + timedelta(hours=1)
        )

        trades = pair_fills_fifo([buy, sell])

        assert len(trades) == 1
        t = trades[0]
        assert t.trade_id == str(sell.id)
        assert t.symbol == "AAPL"
        assert t.strategy_id == "s1"
        assert t.side == "long"
        assert t.entry_time == buy.filled_at
        assert t.exit_time == sell.filled_at
        assert t.quantity == Decimal("100")
        assert t.entry_price == Decimal("185.00")
        assert t.exit_price == Decimal("190.00")
        # pnl = (190 - 185) * 100 - 1.00 (buy commission) - 1.00 (sell commission)
        assert t.pnl == Decimal("498.00")
        assert t.commission == Decimal("2.00")

    def test_sell_spans_two_buy_lots(self) -> None:
        """A sell that consumes two FIFO lots gets a weighted entry price and
        an entry_time taken from the *first* matched lot."""
        buy1 = _fill("s1", "AAPL", OrderSide.BUY, 50, "100.00", "0.50", NOW)
        buy2 = _fill(
            "s1", "AAPL", OrderSide.BUY, 50, "110.00", "0.50", NOW + timedelta(minutes=5)
        )
        sell = _fill(
            "s1", "AAPL", OrderSide.SELL, 100, "120.00", "1.00", NOW + timedelta(hours=1)
        )

        trades = pair_fills_fifo([buy1, buy2, sell])

        assert len(trades) == 1
        t = trades[0]
        assert t.quantity == Decimal("100")
        assert t.entry_time == buy1.filled_at
        # weighted entry price = (50*100 + 50*110) / 100 = 105
        assert t.entry_price == Decimal("105")
        # pnl = (120-100)*50 + (120-110)*50 - 0.50 - 0.50 - 1.00 = 1000+500-2 = 1498
        assert t.pnl == Decimal("1498.00")
        assert t.commission == Decimal("2.00")

    def test_partial_lot_consumption_reduces_remaining_commission(self) -> None:
        """A sell that only partially consumes a buy lot proportionally reduces
        the lot's remaining commission for the *next* sell that closes it."""
        buy = _fill("s1", "AAPL", OrderSide.BUY, 100, "100.00", "2.00", NOW)
        sell1 = _fill(
            "s1", "AAPL", OrderSide.SELL, 40, "110.00", "0.40", NOW + timedelta(minutes=10)
        )
        sell2 = _fill(
            "s1", "AAPL", OrderSide.SELL, 60, "120.00", "0.60", NOW + timedelta(minutes=20)
        )

        trades = pair_fills_fifo([buy, sell1, sell2])

        assert len(trades) == 2
        t1, t2 = trades

        # sell1 matches 40/100 of the lot: buy commission portion = 2.00 * 40/100 = 0.80
        assert t1.quantity == Decimal("40")
        assert t1.commission == Decimal("0.80") + Decimal("0.40")
        assert t1.pnl == (Decimal("110.00") - Decimal("100.00")) * 40 - Decimal(
            "0.80"
        ) - Decimal("0.40")

        # Remaining lot: qty=60, commission proportionally reduced to 2.00 * 60/100 = 1.20
        assert t2.quantity == Decimal("60")
        assert t2.commission == Decimal("1.20") + Decimal("0.60")
        assert t2.pnl == (Decimal("120.00") - Decimal("100.00")) * 60 - Decimal(
            "1.20"
        ) - Decimal("0.60")

    def test_unmatched_sell_skipped(self) -> None:
        """A sell with no prior buy lot (unmatched short) produces no record."""
        sell = _fill("s1", "AAPL", OrderSide.SELL, 10, "100.00", "0.10", NOW)

        trades = pair_fills_fifo([sell])

        assert trades == []

    def test_sell_larger_than_available_lot_only_pairs_matched_qty(self) -> None:
        """A sell larger than the available lot quantity still produces a
        trade for the matched portion, with sell commission prorated."""
        buy = _fill("s1", "AAPL", OrderSide.BUY, 30, "100.00", "0.30", NOW)
        sell = _fill(
            "s1", "AAPL", OrderSide.SELL, 50, "110.00", "0.50", NOW + timedelta(minutes=5)
        )

        trades = pair_fills_fifo([buy, sell])

        assert len(trades) == 1
        t = trades[0]
        assert t.quantity == Decimal("30")
        # sell commission prorated by matched/sell qty = 0.50 * 30/50 = 0.30
        assert t.commission == Decimal("0.30") + Decimal("0.30")

    def test_strategy_and_symbol_isolation(self) -> None:
        """FIFO lots are scoped per (strategy_id, symbol) - unrelated buys
        don't leak into another strategy's or symbol's matching."""
        buy_a = _fill("s1", "AAPL", OrderSide.BUY, 10, "100.00", "0", NOW)
        buy_b = _fill("s2", "AAPL", OrderSide.BUY, 10, "200.00", "0", NOW)  # different strategy
        sell_a = _fill(
            "s1", "AAPL", OrderSide.SELL, 10, "110.00", "0", NOW + timedelta(minutes=1)
        )
        buy_c = _fill("s1", "MSFT", OrderSide.BUY, 5, "300.00", "0", NOW)  # different symbol
        sell_c = _fill(
            "s1", "MSFT", OrderSide.SELL, 5, "310.00", "0", NOW + timedelta(minutes=2)
        )

        trades = pair_fills_fifo([buy_a, buy_b, sell_a, buy_c, sell_c])

        # s2's AAPL buy has no sell and produces nothing
        assert len(trades) == 2
        by_symbol = {t.symbol: t for t in trades}
        assert by_symbol["AAPL"].entry_price == Decimal("100.00")
        assert by_symbol["AAPL"].strategy_id == "s1"
        assert by_symbol["MSFT"].entry_price == Decimal("300.00")

    def test_enum_and_string_side_are_equivalent(self) -> None:
        """`side` may be an OrderSide enum or a plain string - both normalize
        the same way via getattr(fill.side, "value", fill.side)."""

        @dataclass
        class FakeFill:
            id: object
            strategy_id: str
            symbol: str
            side: str
            quantity: Decimal
            price: Decimal
            commission: Decimal
            filled_at: datetime

        buy = FakeFill(
            uuid4(), "s1", "AAPL", "buy", Decimal("10"), Decimal("100"), Decimal("0"), NOW
        )
        sell = FakeFill(
            uuid4(),
            "s1",
            "AAPL",
            "sell",
            Decimal("10"),
            Decimal("110"),
            Decimal("0"),
            NOW + timedelta(minutes=1),
        )

        trades = pair_fills_fifo([buy, sell])

        assert len(trades) == 1
        assert trades[0].pnl == Decimal("100.00")

    def test_out_of_order_input_gets_sorted(self) -> None:
        """Fills are sorted by filled_at before FIFO matching, regardless of
        input order."""
        buy = _fill("s1", "AAPL", OrderSide.BUY, 10, "100.00", "0", NOW)
        sell = _fill(
            "s1", "AAPL", OrderSide.SELL, 10, "110.00", "0", NOW + timedelta(minutes=1)
        )

        trades = pair_fills_fifo([sell, buy])  # sell listed before its buy

        assert len(trades) == 1
        assert trades[0].pnl == Decimal("100.00")

    def test_empty_input(self) -> None:
        """No fills produces no trades."""
        assert pair_fills_fifo([]) == []


class TestFifoDailyRealized:
    """Tests for the shared FIFO-by-day helper in oms.repository."""

    def test_multiple_days(self) -> None:
        """Realized P&L is bucketed by the sell's day, and a lot that spans
        multiple sells carries its reduced commission across days."""
        day1 = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
        day2 = datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)

        rows = [
            {
                "strategy_id": "s1",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": Decimal("100"),
                "price": Decimal("100"),
                "commission": Decimal("1"),
                "filled_at": day1,
            },
            {
                "strategy_id": "s1",
                "symbol": "AAPL",
                "side": "sell",
                "quantity": Decimal("50"),
                "price": Decimal("110"),
                "commission": Decimal("0.5"),
                "filled_at": day1,
            },
            {
                "strategy_id": "s1",
                "symbol": "AAPL",
                "side": "sell",
                "quantity": Decimal("50"),
                "price": Decimal("120"),
                "commission": Decimal("0.5"),
                "filled_at": day2,
            },
        ]

        result = _fifo_daily_realized(rows)

        assert set(result.keys()) == {"2026-06-01", "2026-06-02"}
        # day1: (110-100)*50 - buy_comm(1*50/100=0.5) - sell_comm(0.5) = 500-1 = 499
        assert result["2026-06-01"] == Decimal("499")
        # day2: (120-100)*50 - buy_comm(remaining lot: 1*50/100=0.5) - sell_comm(0.5) = 1000-1 = 999
        assert result["2026-06-02"] == Decimal("999")

    def test_unmatched_sell_contributes_nothing(self) -> None:
        rows = [
            {
                "strategy_id": "s1",
                "symbol": "AAPL",
                "side": "sell",
                "quantity": Decimal("10"),
                "price": Decimal("100"),
                "commission": Decimal("0"),
                "filled_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
            },
        ]

        assert _fifo_daily_realized(rows) == {}

    def test_strategy_symbol_isolation(self) -> None:
        """Buys/sells for one (strategy, symbol) don't match against another."""
        day = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
        rows = [
            {
                "strategy_id": "s1",
                "symbol": "AAPL",
                "side": "buy",
                "quantity": Decimal("10"),
                "price": Decimal("100"),
                "commission": Decimal("0"),
                "filled_at": day,
            },
            {
                "strategy_id": "s2",
                "symbol": "AAPL",
                "side": "sell",
                "quantity": Decimal("10"),
                "price": Decimal("110"),
                "commission": Decimal("0"),
                "filled_at": day,
            },
        ]

        # s2's sell has no lots of its own (s1's buy is a different strategy)
        assert _fifo_daily_realized(rows) == {}

    def test_empty_rows(self) -> None:
        assert _fifo_daily_realized([]) == {}
