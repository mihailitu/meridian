"""Strategy management API endpoints."""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException

from axtrade.analytics import TradeRecord, calculate_strategy_performance, pair_fills_fifo
from axtrade.common import StrategiesConfig
from axtrade.oms.repository import OrderRepository, PositionRepository
from axtrade.strategies import STRATEGY_TYPES
from axtrade.strategies.control import StrategyControlPublisher, StrategyStateRepository

from ..auth import require_api_key
from ..dependencies import (
    get_order_repo,
    get_position_repo,
    get_strategies_config,
    get_strategy_control,
    get_strategy_state_repo,
)
from ..schemas import (
    OrderResponse,
    PositionResponse,
    StrategyDetailResponse,
    StrategyPerformanceResponse,
    StrategyStatusResponse,
)

router = APIRouter()


def _get_strategy_name(strategy_type: str) -> str:
    """Get display name for a strategy type."""
    strategy_class = STRATEGY_TYPES.get(strategy_type)
    if strategy_class:
        # Create a temp instance to get name
        temp = strategy_class(strategy_id="temp", config={})
        return temp.name
    return strategy_type.replace("_", " ").title()


async def _get_trades_for_strategy(
    order_repo: OrderRepository,
    strategy_id: str,
) -> list[TradeRecord]:
    """Get round-trip trade records for a specific strategy via FIFO pairing.

    Uses FIFO round-trip pairing shared with fulltest-style analytics (see
    `axtrade.analytics.pair_fills_fifo`), so P&L reflects matched buy/sell
    pairs rather than raw individual fills.
    """
    fills = await order_repo.get_fills_chronological(strategy_id=strategy_id)
    return pair_fills_fifo(fills)


@router.get("/strategies", response_model=list[StrategyStatusResponse])
async def list_strategies(
    strategies_config: StrategiesConfig = Depends(get_strategies_config),
    state_repo: StrategyStateRepository = Depends(get_strategy_state_repo),
    position_repo: PositionRepository = Depends(get_position_repo),
    order_repo: OrderRepository = Depends(get_order_repo),
) -> list[StrategyStatusResponse]:
    """List all configured strategies with their current status.

    Returns:
        List of strategy status objects with enabled state, position count, and daily P&L
    """
    # Get persisted states
    states = await state_repo.get_all()
    state_map = {s.strategy_id: s.enabled for s in states}

    results = []
    for strat_config in strategies_config.enabled:
        # Enabled status: use persisted state if exists, otherwise config default
        enabled = state_map.get(strat_config.id, strat_config.enabled)

        # Get positions for this strategy
        positions = await position_repo.get_open_positions(strat_config.id)
        position_count = len(positions)

        # Get daily P&L
        daily_pnl = await order_repo.get_daily_realized_pnl(strat_config.id)

        results.append(StrategyStatusResponse(
            strategy_id=strat_config.id,
            name=_get_strategy_name(strat_config.type),
            type=strat_config.type,
            enabled=enabled,
            position_count=position_count,
            daily_pnl=daily_pnl,
        ))

    return results


@router.get("/strategies/{strategy_id}", response_model=StrategyDetailResponse)
async def get_strategy_detail(
    strategy_id: str,
    strategies_config: StrategiesConfig = Depends(get_strategies_config),
    state_repo: StrategyStateRepository = Depends(get_strategy_state_repo),
    position_repo: PositionRepository = Depends(get_position_repo),
    order_repo: OrderRepository = Depends(get_order_repo),
) -> StrategyDetailResponse:
    """Get detailed information about a specific strategy.

    Args:
        strategy_id: Strategy identifier

    Returns:
        Strategy details including config, positions, and recent orders
    """
    # Find strategy in config
    strat_config = None
    for s in strategies_config.enabled:
        if s.id == strategy_id:
            strat_config = s
            break

    if not strat_config:
        raise HTTPException(status_code=404, detail=f"Strategy not found: {strategy_id}")

    # Get persisted state
    state = await state_repo.get(strategy_id)
    enabled = state.enabled if state else strat_config.enabled

    # Get positions
    positions = await position_repo.get_open_positions(strategy_id)
    position_responses = [
        PositionResponse(
            symbol=p.symbol,
            side=p.side,
            quantity=p.quantity,
            avg_entry_price=p.avg_entry_price,
            current_price=p.current_price,
            unrealized_pnl=p.unrealized_pnl,
            strategy_id=p.strategy_id,
        )
        for p in positions
    ]

    # Get recent orders
    orders = await order_repo.get_by_strategy(strategy_id, limit=20)
    order_responses = [
        OrderResponse(
            id=str(o.id),
            symbol=o.symbol,
            side=o.side.value,
            quantity=o.quantity,
            order_type=o.order_type.value,
            status=o.status.value,
            limit_price=o.limit_price,
            filled_quantity=o.filled_quantity,
            avg_fill_price=o.avg_fill_price,
            strategy_id=o.strategy_id,
            created_at=o.created_at,
            updated_at=o.updated_at,
        )
        for o in orders
    ]

    # Get daily P&L
    daily_pnl = await order_repo.get_daily_realized_pnl(strategy_id)

    return StrategyDetailResponse(
        strategy_id=strat_config.id,
        name=_get_strategy_name(strat_config.type),
        type=strat_config.type,
        enabled=enabled,
        config=strat_config.config,
        position_count=len(positions),
        daily_pnl=daily_pnl,
        positions=position_responses,
        recent_orders=order_responses,
    )


@router.post(
    "/strategies/{strategy_id}/enable",
    response_model=StrategyStatusResponse,
    dependencies=[Depends(require_api_key)],
)
async def enable_strategy(
    strategy_id: str,
    strategies_config: StrategiesConfig = Depends(get_strategies_config),
    state_repo: StrategyStateRepository = Depends(get_strategy_state_repo),
    control: StrategyControlPublisher = Depends(get_strategy_control),
    position_repo: PositionRepository = Depends(get_position_repo),
    order_repo: OrderRepository = Depends(get_order_repo),
) -> StrategyStatusResponse:
    """Enable a strategy.

    Args:
        strategy_id: Strategy identifier

    Returns:
        Updated strategy status
    """
    # Verify strategy exists in config
    strat_config = None
    for s in strategies_config.enabled:
        if s.id == strategy_id:
            strat_config = s
            break

    if not strat_config:
        raise HTTPException(status_code=404, detail=f"Strategy not found: {strategy_id}")

    # Persist state
    await state_repo.set_state(strategy_id, enabled=True)

    # Publish control command
    await control.enable(strategy_id)

    # Get updated status
    positions = await position_repo.get_open_positions(strategy_id)
    daily_pnl = await order_repo.get_daily_realized_pnl(strategy_id)

    return StrategyStatusResponse(
        strategy_id=strategy_id,
        name=_get_strategy_name(strat_config.type),
        type=strat_config.type,
        enabled=True,
        position_count=len(positions),
        daily_pnl=daily_pnl,
    )


@router.post(
    "/strategies/{strategy_id}/disable",
    response_model=StrategyStatusResponse,
    dependencies=[Depends(require_api_key)],
)
async def disable_strategy(
    strategy_id: str,
    strategies_config: StrategiesConfig = Depends(get_strategies_config),
    state_repo: StrategyStateRepository = Depends(get_strategy_state_repo),
    control: StrategyControlPublisher = Depends(get_strategy_control),
    position_repo: PositionRepository = Depends(get_position_repo),
    order_repo: OrderRepository = Depends(get_order_repo),
) -> StrategyStatusResponse:
    """Disable a strategy.

    Args:
        strategy_id: Strategy identifier

    Returns:
        Updated strategy status
    """
    # Verify strategy exists in config
    strat_config = None
    for s in strategies_config.enabled:
        if s.id == strategy_id:
            strat_config = s
            break

    if not strat_config:
        raise HTTPException(status_code=404, detail=f"Strategy not found: {strategy_id}")

    # Persist state
    await state_repo.set_state(strategy_id, enabled=False)

    # Publish control command
    await control.disable(strategy_id)

    # Get updated status
    positions = await position_repo.get_open_positions(strategy_id)
    daily_pnl = await order_repo.get_daily_realized_pnl(strategy_id)

    return StrategyStatusResponse(
        strategy_id=strategy_id,
        name=_get_strategy_name(strat_config.type),
        type=strat_config.type,
        enabled=False,
        position_count=len(positions),
        daily_pnl=daily_pnl,
    )


@router.get("/strategies/{strategy_id}/performance", response_model=StrategyPerformanceResponse)
async def get_strategy_performance(
    strategy_id: str,
    strategies_config: StrategiesConfig = Depends(get_strategies_config),
    order_repo: OrderRepository = Depends(get_order_repo),
) -> StrategyPerformanceResponse:
    """Get detailed performance metrics for a strategy.

    Args:
        strategy_id: Strategy identifier

    Returns:
        Performance metrics including P&L, win rate, Sharpe, Sortino, drawdown
    """
    # Verify strategy exists in config
    found = any(s.id == strategy_id for s in strategies_config.enabled)
    if not found:
        raise HTTPException(status_code=404, detail=f"Strategy not found: {strategy_id}")

    # Get trades
    trades = await _get_trades_for_strategy(order_repo, strategy_id)

    if not trades:
        # Return zeros if no trades
        return StrategyPerformanceResponse(
            strategy_id=strategy_id,
            total_pnl=Decimal("0"),
            trade_count=0,
            win_rate=0.0,
            avg_trade_pnl=Decimal("0"),
            profit_factor=0.0,
            sharpe_ratio=None,
            sortino_ratio=None,
            max_drawdown=0.0,
            avg_trade_duration_hours=0.0,
            largest_win=Decimal("0"),
            largest_loss=Decimal("0"),
        )

    # Calculate performance
    perf_map = calculate_strategy_performance(trades)
    perf = perf_map.get(strategy_id)

    if not perf:
        # No performance data for this strategy
        return StrategyPerformanceResponse(
            strategy_id=strategy_id,
            total_pnl=Decimal("0"),
            trade_count=0,
            win_rate=0.0,
            avg_trade_pnl=Decimal("0"),
            profit_factor=0.0,
            sharpe_ratio=None,
            sortino_ratio=None,
            max_drawdown=0.0,
            avg_trade_duration_hours=0.0,
            largest_win=Decimal("0"),
            largest_loss=Decimal("0"),
        )

    return StrategyPerformanceResponse(
        strategy_id=perf.strategy_id,
        total_pnl=perf.total_pnl,
        trade_count=perf.trade_count,
        win_rate=perf.win_rate,
        avg_trade_pnl=perf.avg_trade_pnl,
        profit_factor=perf.profit_factor,
        sharpe_ratio=perf.sharpe_ratio,
        sortino_ratio=perf.sortino_ratio,
        max_drawdown=perf.max_drawdown,
        avg_trade_duration_hours=perf.avg_trade_duration_hours,
        largest_win=perf.largest_win,
        largest_loss=perf.largest_loss,
    )
