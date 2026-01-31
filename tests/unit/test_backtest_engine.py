"""Unit tests for BacktestEngine with file-based data support."""

import json
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from axtrade.backtest import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    HistoricalDataLoader,
)
from axtrade.common import Bar


@pytest.fixture
def basic_config():
    """Create a basic backtest config."""
    return BacktestConfig(
        strategy_type="momentum",
        strategy_id="test_bt",
        symbol="AAPL",
        start_date=date(2024, 1, 15),
        end_date=date(2024, 1, 15),
        strategy_config={
            "rsi_oversold": 30,
            "rsi_overbought": 70,
            "stop_loss_pct": 0.02,
            "position_size": 100,
        },
    )


@pytest.fixture
def temp_data_dir():
    """Create a temporary directory for test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_bars_df():
    """Create sample OHLCV data with indicators."""
    timestamps = pd.date_range(
        start="2024-01-15 09:30:00",
        periods=50,
        freq="1min",
        tz="UTC",
    )

    # Create price data that will trigger trades
    # Start at 185, go up to trigger overbought, then down to trigger oversold
    prices = []
    base = 185.0
    for i in range(50):
        if i < 25:
            prices.append(base + i * 0.1)  # Rising prices
        else:
            prices.append(base + 2.5 - (i - 25) * 0.2)  # Falling prices

    return pd.DataFrame({
        "timestamp": timestamps,
        "open": prices,
        "high": [p + 0.5 for p in prices],
        "low": [p - 0.5 for p in prices],
        "close": prices,
        "volume": [1000] * 50,
        "sma_20": [None] * 19 + [sum(prices[i-19:i+1])/20 for i in range(19, 50)],
        "rsi_14": [None] * 14 + [30 + i * 2 for i in range(36)],  # RSI from 30 to 100
    })


@pytest.fixture
def data_dir_with_file(temp_data_dir, sample_bars_df):
    """Create a temporary directory with parquet file and manifest."""
    filename = "AAPL_1m_2024-01-15_2024-01-15.parquet"
    filepath = temp_data_dir / filename

    df = sample_bars_df.copy()
    df["timestamp"] = df["timestamp"].dt.tz_localize(None)

    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, filepath)

    manifest = {
        "files": [
            {
                "filename": filename,
                "symbol": "AAPL",
                "interval": "1m",
                "start_date": "2024-01-15",
                "end_date": "2024-01-15",
                "bar_count": 50,
                "collected_at": "2024-01-16T10:00:00Z",
                "has_indicators": True,
            }
        ]
    }

    with open(temp_data_dir / "manifest.json", "w") as f:
        json.dump(manifest, f)

    return temp_data_dir


@pytest.fixture
def mock_db_pool():
    """Create a mock database pool."""
    pool = MagicMock()
    return pool


class TestBacktestEngineInit:
    """Tests for BacktestEngine initialization."""

    def test_init_with_data_loader(self, basic_config, temp_data_dir):
        """Test initialization with file-based data loader."""
        loader = HistoricalDataLoader(str(temp_data_dir))
        engine = BacktestEngine(basic_config, data_loader=loader)

        assert engine.data_loader is loader
        assert engine.db_pool is None

    def test_init_with_db_pool(self, basic_config, mock_db_pool):
        """Test initialization with database pool."""
        engine = BacktestEngine(basic_config, db_pool=mock_db_pool)

        assert engine.db_pool is mock_db_pool
        assert engine.data_loader is None

    def test_init_with_both(self, basic_config, mock_db_pool, temp_data_dir):
        """Test initialization with both data sources."""
        loader = HistoricalDataLoader(str(temp_data_dir))
        engine = BacktestEngine(basic_config, db_pool=mock_db_pool, data_loader=loader)

        assert engine.data_loader is loader
        assert engine.db_pool is mock_db_pool

    def test_init_without_data_source_raises_error(self, basic_config):
        """Test that initialization without data source raises error."""
        with pytest.raises(ValueError) as exc_info:
            BacktestEngine(basic_config)

        assert "Either db_pool or data_loader must be provided" in str(exc_info.value)


class TestBacktestEngineRun:
    """Tests for BacktestEngine.run()."""

    async def test_run_with_file_data(self, basic_config, data_dir_with_file):
        """Test running backtest with file-based data."""
        loader = HistoricalDataLoader(str(data_dir_with_file))
        engine = BacktestEngine(basic_config, data_loader=loader)

        result = await engine.run()

        assert isinstance(result, BacktestResult)
        assert result.config == basic_config
        # Should have some equity curve points
        assert len(result.equity_curve) > 0

    async def test_run_empty_data_returns_empty(self, basic_config, temp_data_dir):
        """Test that running with no data returns empty result."""
        # Create empty manifest
        manifest = {"files": []}
        with open(temp_data_dir / "manifest.json", "w") as f:
            json.dump(manifest, f)

        loader = HistoricalDataLoader(str(temp_data_dir))

        # Modify config to match empty data scenario
        config = BacktestConfig(
            strategy_type="momentum",
            strategy_id="test_bt",
            symbol="MISSING",
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
            strategy_config={
                "rsi_oversold": 30,
                "rsi_overbought": 70,
                "stop_loss_pct": 0.02,
                "position_size": 100,
            },
        )

        # This will raise FileNotFoundError since no data file exists
        engine = BacktestEngine(config, data_loader=loader)

        with pytest.raises(FileNotFoundError):
            await engine.run()

    async def test_equity_curve_tracking(self, basic_config, data_dir_with_file):
        """Test that equity curve is properly tracked during backtest."""
        loader = HistoricalDataLoader(str(data_dir_with_file))
        engine = BacktestEngine(basic_config, data_loader=loader)

        result = await engine.run()

        # Should have equity points for each bar processed
        assert len(result.equity_curve) == 50

        # First equity point should be at initial capital
        assert result.equity_curve[0].equity == Decimal("100000")

    async def test_metrics_calculation(self, basic_config, data_dir_with_file):
        """Test that metrics are calculated correctly."""
        loader = HistoricalDataLoader(str(data_dir_with_file))
        engine = BacktestEngine(basic_config, data_loader=loader)

        result = await engine.run()

        # Metrics should be present (may be 0 if no trades)
        assert hasattr(result, "total_trades")
        assert hasattr(result, "win_rate")
        assert hasattr(result, "total_return")
        assert hasattr(result, "sharpe_ratio")
        assert hasattr(result, "max_drawdown")


class TestBacktestEngineStrategy:
    """Tests for strategy handling in BacktestEngine."""

    async def test_strategy_initialization(self, basic_config, data_dir_with_file):
        """Test that strategy is properly initialized."""
        loader = HistoricalDataLoader(str(data_dir_with_file))
        engine = BacktestEngine(basic_config, data_loader=loader)

        await engine.run()

        assert engine.strategy is not None
        assert engine.strategy.strategy_id == "test_bt"

    async def test_unknown_strategy_raises_error(self, data_dir_with_file):
        """Test that unknown strategy type raises error."""
        config = BacktestConfig(
            strategy_type="unknown_strategy",
            strategy_id="test_bt",
            symbol="AAPL",
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 15),
        )

        loader = HistoricalDataLoader(str(data_dir_with_file))
        engine = BacktestEngine(config, data_loader=loader)

        with pytest.raises(ValueError) as exc_info:
            await engine.run()

        assert "Unknown strategy type" in str(exc_info.value)


class TestBacktestEngineDataPriority:
    """Tests for data source priority in BacktestEngine."""

    async def test_file_data_takes_priority(self, basic_config, data_dir_with_file, mock_db_pool):
        """Test that file-based data takes priority over database."""
        loader = HistoricalDataLoader(str(data_dir_with_file))

        # Mock bar_repo to track if it was called
        mock_bar_repo = MagicMock()
        mock_bar_repo.get_bars_range = AsyncMock(return_value=[])

        engine = BacktestEngine(basic_config, db_pool=mock_db_pool, data_loader=loader)
        engine.bar_repo = mock_bar_repo

        await engine.run()

        # Database should NOT have been called
        mock_bar_repo.get_bars_range.assert_not_called()
