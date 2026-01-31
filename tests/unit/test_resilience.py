"""Tests for resilience utilities."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from axtrade.common.resilience import LoopSupervisor


class TestLoopSupervisor:
    """Tests for LoopSupervisor."""

    async def test_retries_on_error(self):
        """Should continue retrying when handle_error returns True."""
        supervisor = LoopSupervisor(
            name="test_loop",
            base_delay=0.01,
            max_delay=0.1,
        )

        error = ValueError("test error")
        should_continue = await supervisor.handle_error(error)

        assert should_continue is True
        assert supervisor.consecutive_errors == 1

    async def test_exponential_backoff(self):
        """Should use exponential backoff for delays."""
        supervisor = LoopSupervisor(
            name="test_loop",
            base_delay=1.0,
            max_delay=60.0,
        )

        # _calculate_delay uses _consecutive_errors - 1 as exponent
        # After 1 error: delay = 1.0 * 2^0 = 1.0
        supervisor._consecutive_errors = 1
        assert supervisor._calculate_delay() == 1.0

        # After 2 errors: delay = 1.0 * 2^1 = 2.0
        supervisor._consecutive_errors = 2
        assert supervisor._calculate_delay() == 2.0

        # After 3 errors: delay = 1.0 * 2^2 = 4.0
        supervisor._consecutive_errors = 3
        assert supervisor._calculate_delay() == 4.0

        # After 4 errors: delay = 1.0 * 2^3 = 8.0
        supervisor._consecutive_errors = 4
        assert supervisor._calculate_delay() == 8.0

        # After 5 errors: delay = 1.0 * 2^4 = 16.0
        supervisor._consecutive_errors = 5
        assert supervisor._calculate_delay() == 16.0

    async def test_caps_delay_at_max(self):
        """Should cap delay at max_delay."""
        supervisor = LoopSupervisor(
            name="test_loop",
            base_delay=1.0,
            max_delay=10.0,
        )

        # After 10 errors: delay would be 1.0 * 2^9 = 512.0, but capped at 10.0
        supervisor._consecutive_errors = 10
        assert supervisor._calculate_delay() == 10.0

    async def test_alerts_after_threshold(self):
        """Should call alert callback after alert_after consecutive errors."""
        alert_callback = AsyncMock()

        supervisor = LoopSupervisor(
            name="test_loop",
            base_delay=0.001,
            alert_after=3,
            alert_callback=alert_callback,
        )

        error = ValueError("test error")

        # First two errors should not trigger alert
        await supervisor.handle_error(error)
        await supervisor.handle_error(error)
        alert_callback.assert_not_called()

        # Third error should trigger alert
        await supervisor.handle_error(error)
        alert_callback.assert_called_once_with("test_loop", error)

        # Subsequent errors should also trigger alert
        alert_callback.reset_mock()
        await supervisor.handle_error(error)
        alert_callback.assert_called_once_with("test_loop", error)

    async def test_resets_on_success(self):
        """Should reset error count when reset_errors is called."""
        supervisor = LoopSupervisor(
            name="test_loop",
            base_delay=0.001,
        )

        error = ValueError("test error")
        await supervisor.handle_error(error)
        await supervisor.handle_error(error)
        assert supervisor.consecutive_errors == 2

        supervisor.reset_errors()
        assert supervisor.consecutive_errors == 0

    async def test_stops_after_max_retries(self):
        """Should return False after max_retries exceeded."""
        supervisor = LoopSupervisor(
            name="test_loop",
            base_delay=0.001,
            max_retries=3,
        )

        error = ValueError("test error")

        # First three retries should return True
        assert await supervisor.handle_error(error) is True
        assert await supervisor.handle_error(error) is True
        assert await supervisor.handle_error(error) is True

        # Fourth retry exceeds max, should return False
        assert await supervisor.handle_error(error) is False

    async def test_stop_prevents_further_retries(self):
        """Should return False after stop() is called."""
        supervisor = LoopSupervisor(
            name="test_loop",
            base_delay=0.001,
        )

        supervisor.stop()

        error = ValueError("test error")
        should_continue = await supervisor.handle_error(error)

        assert should_continue is False

    async def test_infinite_retries_when_max_retries_zero(self):
        """Should retry indefinitely when max_retries is 0."""
        supervisor = LoopSupervisor(
            name="test_loop",
            base_delay=0.001,
            max_delay=0.001,
            max_retries=0,
        )

        error = ValueError("test error")

        # Should continue retrying even after many errors
        for _ in range(10):
            assert await supervisor.handle_error(error) is True

    async def test_alert_callback_failure_does_not_stop_supervisor(self):
        """Should continue even if alert callback raises an exception."""
        alert_callback = AsyncMock(side_effect=RuntimeError("callback failed"))

        supervisor = LoopSupervisor(
            name="test_loop",
            base_delay=0.001,
            alert_after=1,
            alert_callback=alert_callback,
        )

        error = ValueError("test error")

        # Should not raise, should continue retrying
        should_continue = await supervisor.handle_error(error)
        assert should_continue is True
        alert_callback.assert_called_once()

    async def test_no_alert_when_callback_not_set(self):
        """Should not fail when alert_callback is None."""
        supervisor = LoopSupervisor(
            name="test_loop",
            base_delay=0.001,
            alert_after=1,
            alert_callback=None,
        )

        error = ValueError("test error")

        # Should work fine without callback
        should_continue = await supervisor.handle_error(error)
        assert should_continue is True
