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


class TestEnabledStrategiesSelection:
    def test_default_excludes_buy_hold_and_overnight_reversal(self) -> None:
        orch = _make_orchestrator()
        cfg = orch._build_isolated_config()
        enabled_types = {entry.type for entry in cfg.strategies.enabled}
        assert "buy_hold" not in enabled_types
        assert "overnight_reversal" not in enabled_types

    def test_default_includes_core_strategies(self) -> None:
        orch = _make_orchestrator()
        cfg = orch._build_isolated_config()
        enabled_types = {entry.type for entry in cfg.strategies.enabled}
        for stype in ("momentum", "mean_reversion", "multi_timeframe", "pairs", "discovery_momentum"):
            assert stype in enabled_types, f"{stype!r} missing from default enabled strategies"

    def test_explicit_buy_hold_gives_exactly_one_strategy(self) -> None:
        orch = _make_orchestrator()
        orch._bt_config.enabled_strategies = ["buy_hold"]
        cfg = orch._build_isolated_config()
        assert len(cfg.strategies.enabled) == 1
        assert cfg.strategies.enabled[0].type == "buy_hold"

    def test_explicit_buy_hold_gets_allowed_symbols(self) -> None:
        # buy_hold is in narrowed_types, so allowed_symbols must be injected.
        orch = _make_orchestrator(symbols=["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"])
        orch._bt_config.enabled_strategies = ["buy_hold"]
        cfg = orch._build_isolated_config()
        entry = cfg.strategies.enabled[0]
        assert entry.config["allowed_symbols"] == ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]

    def test_unknown_strategy_raises_value_error(self) -> None:
        orch = _make_orchestrator()
        orch._bt_config.enabled_strategies = ["nonexistent"]
        with pytest.raises(ValueError, match="nonexistent"):
            orch._build_isolated_config()

    def test_buy_hold_and_momentum_gives_exactly_two(self) -> None:
        orch = _make_orchestrator()
        orch._bt_config.enabled_strategies = ["buy_hold", "momentum"]
        cfg = orch._build_isolated_config()
        assert len(cfg.strategies.enabled) == 2
        enabled_types = {entry.type for entry in cfg.strategies.enabled}
        assert enabled_types == {"buy_hold", "momentum"}
