"""Tests for fulltest config passthrough and strategy filtering."""

from datetime import date

import pytest

from axtrade.common import Config, StrategyInstanceConfig, StrategiesConfig
from axtrade.fulltest.orchestrator import FullBacktestOrchestrator
from axtrade.fulltest.types import FullBacktestConfig


def _make_base_config(**overrides) -> Config:
    """Create a base Config with realistic strategy settings."""
    config = Config()
    config.strategies = StrategiesConfig(
        enabled=[
            StrategyInstanceConfig(
                type="momentum",
                id="momentum_us_01",
                enabled=True,
                config={
                    "rsi_entry": 55,
                    "rsi_overbought": 70,
                    "stop_loss_pct": 0.02,
                    "target_position_value": 7500,
                },
            ),
            StrategyInstanceConfig(
                type="mean_reversion",
                id="mean_rev_01",
                enabled=True,
                config={
                    "bb_period": 20,
                    "bb_std": 2.0,
                    "rsi_oversold": 30,
                    "rsi_overbought": 70,
                    "stop_loss_pct": 0.03,
                    "target_position_value": 7500,
                },
            ),
            StrategyInstanceConfig(
                type="multi_timeframe",
                id="mtf_01",
                enabled=True,
                config={
                    "trend_period": 20,
                    "rsi_oversold": 35,
                    "stop_loss_pct": 0.025,
                    "take_profit_pct": 0.06,
                    "target_position_value": 7500,
                },
            ),
            StrategyInstanceConfig(
                type="pairs",
                id="pairs_aapl_msft",
                enabled=True,
                config={
                    "symbol_a": "AAPL",
                    "symbol_b": "MSFT",
                    "lookback": 20,
                    "entry_zscore": 2.0,
                    "stop_loss_pct": 0.03,
                    "target_position_value": 7500,
                },
            ),
        ]
    )
    return config


def _make_bt_config(**overrides) -> FullBacktestConfig:
    defaults = dict(
        start=date(2025, 8, 1),
        end=date(2026, 2, 1),
        symbols=["AAPL", "MSFT"],
    )
    defaults.update(overrides)
    return FullBacktestConfig(**defaults)


class TestConfigPassthrough:
    """Verify tuned params survive _build_isolated_config()."""

    def test_preserves_rsi_entry(self):
        base = _make_base_config()
        orch = FullBacktestOrchestrator(_make_bt_config(), base_config=base)
        config = orch._build_isolated_config()

        momentum = next(s for s in config.strategies.enabled if s.type == "momentum")
        assert momentum.config["rsi_entry"] == 55

    def test_preserves_stop_loss_pct(self):
        base = _make_base_config()
        orch = FullBacktestOrchestrator(_make_bt_config(), base_config=base)
        config = orch._build_isolated_config()

        mr = next(s for s in config.strategies.enabled if s.type == "mean_reversion")
        assert mr.config["stop_loss_pct"] == 0.03

    def test_preserves_target_position_value(self):
        base = _make_base_config()
        orch = FullBacktestOrchestrator(_make_bt_config(), base_config=base)
        config = orch._build_isolated_config()

        momentum = next(s for s in config.strategies.enabled if s.type == "momentum")
        assert momentum.config["target_position_value"] == 7500

    def test_preserves_take_profit_pct(self):
        base = _make_base_config()
        orch = FullBacktestOrchestrator(_make_bt_config(), base_config=base)
        config = orch._build_isolated_config()

        mtf = next(s for s in config.strategies.enabled if s.type == "multi_timeframe")
        assert mtf.config["take_profit_pct"] == 0.06

    def test_falls_back_to_position_size_without_target_value(self):
        """When a strategy has no target_position_value, position_size is set."""
        base = Config()
        base.strategies = StrategiesConfig(
            enabled=[
                StrategyInstanceConfig(
                    type="momentum",
                    id="momentum_us_01",
                    enabled=True,
                    config={"rsi_entry": 55},  # no target_position_value
                ),
            ]
        )
        orch = FullBacktestOrchestrator(_make_bt_config(), base_config=base)
        config = orch._build_isolated_config()

        momentum = next(s for s in config.strategies.enabled if s.type == "momentum")
        assert "position_size" in momentum.config
        assert momentum.config["rsi_entry"] == 55

    def test_does_not_add_position_size_when_target_value_set(self):
        base = _make_base_config()
        orch = FullBacktestOrchestrator(_make_bt_config(), base_config=base)
        config = orch._build_isolated_config()

        momentum = next(s for s in config.strategies.enabled if s.type == "momentum")
        assert "position_size" not in momentum.config

    def test_does_not_mutate_base_config(self):
        base = _make_base_config()
        original_rsi = base.strategies.enabled[0].config["rsi_entry"]
        orch = FullBacktestOrchestrator(_make_bt_config(), base_config=base)
        orch._build_isolated_config()

        assert base.strategies.enabled[0].config["rsi_entry"] == original_rsi


class TestStrategyFiltering:
    """Verify --strategies flag filters correctly."""

    def test_filter_single_strategy(self):
        base = _make_base_config()
        bt_config = _make_bt_config(strategies=["momentum"])
        orch = FullBacktestOrchestrator(bt_config, base_config=base)
        config = orch._build_isolated_config()

        types = [s.type for s in config.strategies.enabled]
        assert types == ["momentum"]

    def test_filter_multiple_strategies(self):
        base = _make_base_config()
        bt_config = _make_bt_config(strategies=["momentum", "mean_reversion"])
        orch = FullBacktestOrchestrator(bt_config, base_config=base)
        config = orch._build_isolated_config()

        types = sorted(s.type for s in config.strategies.enabled)
        assert types == ["mean_reversion", "momentum"]

    def test_no_filter_enables_all(self):
        base = _make_base_config()
        bt_config = _make_bt_config(strategies=None)
        orch = FullBacktestOrchestrator(bt_config, base_config=base)
        config = orch._build_isolated_config()

        types = sorted(s.type for s in config.strategies.enabled)
        # discovery_momentum has no base config but gets included from STRATEGY_TYPES
        assert "momentum" in types
        assert "mean_reversion" in types
        assert "multi_timeframe" in types
        assert "pairs" in types

    def test_ml_prediction_always_skipped(self):
        base = _make_base_config()
        bt_config = _make_bt_config(strategies=["ml_prediction", "momentum"])
        orch = FullBacktestOrchestrator(bt_config, base_config=base)
        config = orch._build_isolated_config()

        types = [s.type for s in config.strategies.enabled]
        assert "ml_prediction" not in types
        assert "momentum" in types

    def test_filtered_strategies_preserve_params(self):
        base = _make_base_config()
        bt_config = _make_bt_config(strategies=["mean_reversion"])
        orch = FullBacktestOrchestrator(bt_config, base_config=base)
        config = orch._build_isolated_config()

        assert len(config.strategies.enabled) == 1
        mr = config.strategies.enabled[0]
        assert mr.type == "mean_reversion"
        assert mr.config["bb_period"] == 20
        assert mr.config["stop_loss_pct"] == 0.03
        assert mr.config["target_position_value"] == 7500

    def test_strategy_ids_use_bt_suffix(self):
        base = _make_base_config()
        bt_config = _make_bt_config(strategies=["momentum"])
        orch = FullBacktestOrchestrator(bt_config, base_config=base)
        config = orch._build_isolated_config()

        assert config.strategies.enabled[0].id == "momentum-bt"
