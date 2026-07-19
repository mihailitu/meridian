"""Phase 6 research layer: batch daily-bar construction and universe hygiene.

Plain pandas, no asyncio -- this is an offline research pipeline over the
`data/historical/` 1m parquet archive, not part of the live/fulltest event
loop. See docs/phase6-cross-sectional.md (Phase A) for the design.
"""

from .daily import build_all, build_symbol_daily, trading_calendar
from .universe import compute_eligibility, hygiene_report, survivorship_summary

__all__ = [
    "build_all",
    "build_symbol_daily",
    "compute_eligibility",
    "hygiene_report",
    "survivorship_summary",
    "trading_calendar",
]
