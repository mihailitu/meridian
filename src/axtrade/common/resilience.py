"""Resilience utilities for service loops."""

import asyncio
from typing import Awaitable, Callable, Optional

from .logging import get_logger

logger = get_logger("resilience")


class LoopSupervisor:
    """Supervises async loops with retry and alerting.

    Provides exponential backoff on errors, optional maximum retries,
    and callback-based alerting after repeated failures.
    """

    def __init__(
        self,
        name: str,
        max_retries: int = 0,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        alert_after: int = 3,
        alert_callback: Optional[Callable[[str, Exception], Awaitable[None]]] = None,
    ):
        """Initialize the loop supervisor.

        Args:
            name: Name of the loop being supervised (for logging)
            max_retries: Maximum retry attempts (0 = infinite)
            base_delay: Initial delay in seconds before retry
            max_delay: Maximum delay cap in seconds
            alert_after: Number of consecutive errors before alerting
            alert_callback: Async callback(loop_name, error) for alerting
        """
        self.name = name
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.alert_after = alert_after
        self.alert_callback = alert_callback
        self._consecutive_errors = 0
        self._running = True

    @property
    def consecutive_errors(self) -> int:
        """Return the current consecutive error count."""
        return self._consecutive_errors

    def stop(self) -> None:
        """Signal the supervisor to stop retrying."""
        self._running = False

    def reset_errors(self) -> None:
        """Reset the consecutive error count (call on success)."""
        self._consecutive_errors = 0

    def _calculate_delay(self) -> float:
        """Calculate the next backoff delay."""
        delay = self.base_delay * (2 ** (self._consecutive_errors - 1))
        return min(delay, self.max_delay)

    async def handle_error(self, error: Exception) -> bool:
        """Handle an error with exponential backoff.

        Args:
            error: The exception that occurred

        Returns:
            True if should continue retrying, False if should stop
        """
        self._consecutive_errors += 1

        if self.max_retries > 0 and self._consecutive_errors > self.max_retries:
            logger.error(
                "Loop exceeded max retries",
                loop=self.name,
                retries=self._consecutive_errors,
                error=str(error),
            )
            return False

        delay = self._calculate_delay()

        logger.warning(
            "Loop error, will retry",
            loop=self.name,
            error=str(error),
            error_type=type(error).__name__,
            consecutive_errors=self._consecutive_errors,
            retry_delay=delay,
        )

        if self._consecutive_errors >= self.alert_after and self.alert_callback:
            try:
                await self.alert_callback(self.name, error)
            except Exception as alert_err:
                logger.error(
                    "Alert callback failed",
                    loop=self.name,
                    error=str(alert_err),
                )

        await asyncio.sleep(delay)
        return self._running
