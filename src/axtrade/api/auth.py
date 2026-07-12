"""API key authentication dependency (audit P0-5)."""

import secrets
from typing import Optional

from fastapi import Header, HTTPException

from .dependencies import state


async def require_api_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> None:
    """Require a matching X-API-Key header on mutating endpoints.

    When no api_key is configured (state.api_key is empty), auth is
    disabled and every request is allowed through. Otherwise the header
    must be present and match via a constant-time comparison.
    """
    expected = state.api_key
    if not expected:
        return

    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
