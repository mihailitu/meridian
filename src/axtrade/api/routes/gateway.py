"""Gateway API endpoints for provider status and preferences."""

from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException, Request

from axtrade.common import load_config

from ..schemas import GatewayPreferenceRequest, GatewayStatusResponse

router = APIRouter()

AVAILABLE_ADAPTERS = ["mock", "ibkr", "alpaca", "yahoo"]

# Store preferred adapter in memory (persists for server lifetime)
_preferred_adapter: Optional[str] = None


def _get_config_path() -> Path:
    """Get the config file path."""
    return Path(__file__).parent.parent.parent.parent.parent.parent / "config" / "default.yaml"


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


@router.post("/gateway/preference", response_model=GatewayStatusResponse)
async def set_gateway_preference(
    request: GatewayPreferenceRequest,
) -> GatewayStatusResponse:
    """Set preferred gateway adapter.

    This updates the config file. A gateway restart is required for the change
    to take effect.
    """
    global _preferred_adapter

    adapter = request.adapter.lower()
    if adapter not in AVAILABLE_ADAPTERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid adapter: {adapter}. Available: {AVAILABLE_ADAPTERS}",
        )

    # Update the config file
    config_path = _get_config_path()
    if config_path.exists():
        with open(config_path) as f:
            config_data = yaml.safe_load(f)

        config_data["gateway"]["adapter"] = adapter

        with open(config_path, "w") as f:
            yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)

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
