"""Tests for fulltest orchestrator `_build_isolated_config`: confirms
`allowed_symbols` is injected for narrowed strategy types, `strategy_overrides`
patches the per-strategy config dict, and discovery/pairs strategies are left
untouched.
"""

from datetime import date

import pytest

from axtrade.common import Config
from axtrade.fulltest.orchestrator import FullBacktestOrchestrator
from axtrade.fulltest.types import FullBacktestConfig


def _make_orchestrator(strategy_overrides=None, symbols=None) -> FullBacktestOrchestrator:
    bt = FullBacktestConfig(
        start=date(2025, 8, 1),
        end=date(2026, 2, 1),
        symbols=symbols or ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"],
        strategy_overrides=strategy_overrides or {},
    )
    return FullBacktestOrchestrator(bt_config=bt, base_config=Config())


def _strategy_by_type(config, stype: str):
    for entry in config.strategies.enabled:
        if entry.type == stype:
            return entry
    raise AssertionError(f"strategy type {stype!r} not in enabled list")


class TestAllowedSymbolsInjection:
    def test_multi_timeframe_gets_allowed_symbols(self) -> None:
        orch = _make_orchestrator(symbols=["AAPL", "MSFT"])
        cfg = orch._build_isolated_config()
        entry = _strategy_by_type(cfg, "multi_timeframe")
        assert entry.config["allowed_symbols"] == ["AAPL", "MSFT"]

    def test_mean_reversion_gets_allowed_symbols(self) -> None:
        orch = _make_orchestrator(symbols=["AAPL", "MSFT"])
        cfg = orch._build_isolated_config()
        entry = _strategy_by_type(cfg, "mean_reversion")
        assert entry.config["allowed_symbols"] == ["AAPL", "MSFT"]

    def test_momentum_gets_allowed_symbols(self) -> None:
        orch = _make_orchestrator(symbols=["AAPL", "MSFT"])
        cfg = orch._build_isolated_config()
        entry = _strategy_by_type(cfg, "momentum")
        assert entry.config["allowed_symbols"] == ["AAPL", "MSFT"]

    def test_discovery_momentum_unchanged(self) -> None:
        orch = _make_orchestrator(symbols=["AAPL", "MSFT"])
        cfg = orch._build_isolated_config()
        entry = _strategy_by_type(cfg, "discovery_momentum")
        # discovery_momentum gates by score — adding allowed_symbols would
        # double-restrict it and break the score-gating semantics.
        assert "allowed_symbols" not in entry.config

    def test_pairs_unchanged(self) -> None:
        orch = _make_orchestrator(symbols=["AAPL", "MSFT"])
        cfg = orch._build_isolated_config()
        entry = _strategy_by_type(cfg, "pairs")
        # Pairs already self-restricts via symbol_a/symbol_b config.
        assert "allowed_symbols" not in entry.config


class TestStrategyOverrides:
    def test_override_patches_strategy_config(self) -> None:
        orch = _make_orchestrator(
            strategy_overrides={"mean_reversion": {"rsi_oversold": 25}},
        )
        cfg = orch._build_isolated_config()
        entry = _strategy_by_type(cfg, "mean_reversion")
        assert entry.config["rsi_oversold"] == 25
        # Defaults still present
        assert entry.config["position_size"] > 0
        assert entry.config["max_positions"] > 0
        # Universe still narrowed
        assert "allowed_symbols" in entry.config

    def test_override_can_replace_allowed_symbols(self) -> None:
        orch = _make_orchestrator(
            symbols=["AAPL", "MSFT", "GOOGL"],
            strategy_overrides={"multi_timeframe": {"allowed_symbols": ["TSLA"]}},
        )
        cfg = orch._build_isolated_config()
        entry = _strategy_by_type(cfg, "multi_timeframe")
        # Override wins over orchestrator default (last-write semantics).
        assert entry.config["allowed_symbols"] == ["TSLA"]

    def test_override_for_unknown_type_silently_ignored(self) -> None:
        orch = _make_orchestrator(
            strategy_overrides={"nonexistent_strategy": {"x": 1}},
        )
        # Should not raise; the unknown override is just never applied.
        cfg = orch._build_isolated_config()
        assert len(cfg.strategies.enabled) > 0

    def test_no_overrides_yields_defaults(self) -> None:
        orch = _make_orchestrator()
        cfg = orch._build_isolated_config()
        for entry in cfg.strategies.enabled:
            assert "position_size" in entry.config
            assert "max_positions" in entry.config
