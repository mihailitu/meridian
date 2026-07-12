"""Gateway API endpoints for provider status and preferences."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from axtrade.common import load_config

from ..auth import require_api_key
from ..schemas import GatewayPreferenceRequest, GatewayStatusResponse

router = APIRouter()

AVAILABLE_ADAPTERS = ["mock", "ibkr", "alpaca", "yahoo"]

# Store preferred adapter in memory (persists for server lifetime)
_preferred_adapter: Optional[str] = None


@router.get("/gateway/status", response_model=GatewayStatusResponse)
async def get_gateway_status(request: Request) -> GatewayStatusResponse:
    """Get current gateway status and adapter information."""
    global _preferred_adapter

    config = load_config()
    current_adapter = config.gateway.adapter

    requires_restart = (
        _preferred_adapter is not None and _preferred_adapter != current_adapter
    )

    return GatewayStatusResponse(
        current_adapter=current_adapter,
        preferred_adapter=_preferred_adapter,
        available_adapters=AVAILABLE_ADAPTERS,
        requires_restart=requires_restart,
    )


@router.post(
    "/gateway/preference",
    response_model=GatewayStatusResponse,
    dependencies=[Depends(require_api_key)],
)
async def set_gateway_preference(
    request: GatewayPreferenceRequest,
) -> GatewayStatusResponse:
    """Set preferred gateway adapter.

    This only records the preference in memory for the lifetime of the API
    server (audit P1-7: it no longer rewrites config/default.yaml). The
    operator restarts the gateway with the desired adapter
    (`make run-<adapter>`) to actually apply it.
    """
    global _preferred_adapter

    adapter = request.adapter.lower()
    if adapter not in AVAILABLE_ADAPTERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid adapter: {adapter}. Available: {AVAILABLE_ADAPTERS}",
        )

    _preferred_adapter = adapter

    # Get current running adapter
    config = load_config()
    current_adapter = config.gateway.adapter

    requires_restart = adapter != current_adapter

    return GatewayStatusResponse(
        current_adapter=current_adapter,
        preferred_adapter=adapter,
        available_adapters=AVAILABLE_ADAPTERS,
        requires_restart=requires_restart,
    )
