"""Bars query command."""

from axtrade.common import BarRepository, DatabasePool, load_config


async def bars_command(symbol: str, limit: int, interval: str) -> None:
    """Query and display historical bars.

    Args:
        symbol: Symbol to query
        limit: Number of bars to display
        interval: Bar interval
    """
    config = load_config()
    pool = DatabasePool(config.database)

    try:
        await pool.connect()
        repo = BarRepository(pool)

        bars = await repo.get_bars(symbol.upper(), interval, limit)

        if not bars:
            print(f"No bars found for {symbol.upper()} {interval}")
            return

        # Print header
        print(
            f"{'time':<20} {'open':>10} {'high':>10} {'low':>10} "
            f"{'close':>10} {'volume':>12} {'sma_20':>10} {'rsi_14':>8}"
        )
        print("-" * 102)

        # Print bars (reverse to show oldest first)
        for bar in reversed(bars):
            time_str = bar["time"].strftime("%Y-%m-%d %H:%M")
            sma_str = f"{bar['sma_20']:.2f}" if bar["sma_20"] else "-"
            rsi_str = f"{bar['rsi_14']:.1f}" if bar["rsi_14"] else "-"

            print(
                f"{time_str:<20} {bar['open']:>10.2f} {bar['high']:>10.2f} "
                f"{bar['low']:>10.2f} {bar['close']:>10.2f} "
                f"{bar['volume']:>12} {sma_str:>10} {rsi_str:>8}"
            )

    finally:
        await pool.disconnect()
