"""Unit tests for ML module."""

import math
from datetime import datetime, timedelta

import pytest

from axtrade.ml import (
    FeatureExtractor,
    FeatureSet,
    LinearModel,
    ModelConfig,
    ModelMetadata,
    ModelRegistry,
    ModelType,
    Prediction,
    PredictionDirection,
    PredictionEngine,
    TrainingResult,
)


def create_test_bars(
    count: int,
    base_price: float = 100.0,
    trend: str = "flat",
    base_volume: int = 10000,
) -> list[dict]:
    """Create test bar data."""
    bars = []
    now = datetime.now()

    for i in range(count):
        if trend == "up":
            close = base_price * (1 + 0.01 * i)
        elif trend == "down":
            close = base_price * (1 - 0.01 * i)
        else:
            close = base_price * (1 + 0.001 * math.sin(i * 0.5))

        spread = close * 0.005
        bars.append({
            "symbol": "AAPL",
            "time": (now - timedelta(minutes=count - i)).isoformat(),
            "open": close - spread * 0.3,
            "high": close + spread,
            "low": close - spread,
            "close": close,
            "volume": base_volume,
        })

    return bars


class TestModelType:
    """Tests for ModelType enum."""

    def test_model_types(self):
        """Test all model types exist."""
        assert ModelType.LINEAR.value == "linear"
        assert ModelType.LOGISTIC.value == "logistic"
        assert ModelType.ENSEMBLE.value == "ensemble"


class TestPredictionDirection:
    """Tests for PredictionDirection enum."""

    def test_directions(self):
        """Test all prediction directions."""
        assert PredictionDirection.LONG.value == "long"
        assert PredictionDirection.SHORT.value == "short"
        assert PredictionDirection.NEUTRAL.value == "neutral"


class TestModelConfig:
    """Tests for ModelConfig dataclass."""

    def test_create_config(self):
        """Test creating model config."""
        config = ModelConfig(
            model_type=ModelType.LINEAR,
            name="test_model",
            symbol="AAPL",
        )
        assert config.model_type == ModelType.LINEAR
        assert config.name == "test_model"
        assert config.symbol == "AAPL"
        assert config.interval == "1m"
        assert config.lookback_periods == 20
        assert config.threshold == 0.6

    def test_config_to_dict(self):
        """Test config to_dict."""
        config = ModelConfig(
            model_type=ModelType.LINEAR,
            name="test",
            symbol="AAPL",
        )
        data = config.to_dict()
        assert data["model_type"] == "linear"
        assert data["name"] == "test"
        assert data["symbol"] == "AAPL"


class TestPrediction:
    """Tests for Prediction dataclass."""

    def test_create_prediction(self):
        """Test creating a prediction."""
        pred = Prediction(
            model_id="test123",
            symbol="AAPL",
            direction=PredictionDirection.LONG,
            confidence=0.85,
            predicted_return=1.5,
            features_used={"returns": 0.5},
        )
        assert pred.model_id == "test123"
        assert pred.symbol == "AAPL"
        assert pred.direction == PredictionDirection.LONG
        assert pred.confidence == 0.85
        assert pred.predicted_return == 1.5

    def test_is_actionable_long(self):
        """Test actionable prediction for long."""
        pred = Prediction(
            model_id="test",
            symbol="AAPL",
            direction=PredictionDirection.LONG,
            confidence=0.7,
            predicted_return=1.0,
            features_used={},
        )
        assert pred.is_actionable is True

    def test_is_actionable_low_confidence(self):
        """Test non-actionable due to low confidence."""
        pred = Prediction(
            model_id="test",
            symbol="AAPL",
            direction=PredictionDirection.LONG,
            confidence=0.5,
            predicted_return=1.0,
            features_used={},
        )
        assert pred.is_actionable is False

    def test_is_actionable_neutral(self):
        """Test non-actionable for neutral."""
        pred = Prediction(
            model_id="test",
            symbol="AAPL",
            direction=PredictionDirection.NEUTRAL,
            confidence=0.9,
            predicted_return=0.0,
            features_used={},
        )
        assert pred.is_actionable is False

    def test_prediction_to_dict(self):
        """Test prediction to_dict."""
        pred = Prediction(
            model_id="test",
            symbol="AAPL",
            direction=PredictionDirection.SHORT,
            confidence=0.75,
            predicted_return=-1.0,
            features_used={"rsi": 25.0},
        )
        data = pred.to_dict()
        assert data["direction"] == "short"
        assert data["confidence"] == 0.75
        assert data["is_actionable"] is True


class TestFeatureSet:
    """Tests for FeatureSet dataclass."""

    def test_create_feature_set(self):
        """Test creating feature set."""
        features = FeatureSet(
            returns=0.5,
            volatility=1.2,
            momentum=3.5,
            rsi=45.0,
            trend_strength=60.0,
            volume_ratio=1.5,
            price_position=0.7,
            sma_distance=0.5,
        )
        assert features.returns == 0.5
        assert features.rsi == 45.0

    def test_to_vector(self):
        """Test converting to vector."""
        features = FeatureSet(
            returns=0.5,
            volatility=1.2,
            momentum=3.5,
            rsi=45.0,
            trend_strength=60.0,
            volume_ratio=1.5,
            price_position=0.7,
            sma_distance=0.5,
        )
        vector = features.to_vector(["returns", "rsi", "momentum"])
        assert vector == [0.5, 45.0, 3.5]


class TestFeatureExtractor:
    """Tests for FeatureExtractor."""

    def test_create_extractor(self):
        """Test creating feature extractor."""
        extractor = FeatureExtractor(lookback_periods=20)
        assert extractor.lookback_periods == 20

    def test_extract_insufficient_data(self):
        """Test extraction with insufficient data."""
        extractor = FeatureExtractor(lookback_periods=20)
        bars = create_test_bars(10)  # Less than 20
        features = extractor.extract(bars)
        assert features is None

    def test_extract_flat_market(self):
        """Test extraction in flat market."""
        extractor = FeatureExtractor(lookback_periods=15)
        bars = create_test_bars(20, trend="flat")
        features = extractor.extract(bars)
        assert features is not None
        assert -5 < features.returns < 5
        assert 40 < features.rsi < 60  # Should be around neutral

    def test_extract_trending_up(self):
        """Test extraction in uptrending market."""
        extractor = FeatureExtractor(lookback_periods=15)
        bars = create_test_bars(20, trend="up")
        features = extractor.extract(bars)
        assert features is not None
        assert features.momentum > 0
        assert features.trend_strength > 50

    def test_extract_trending_down(self):
        """Test extraction in downtrending market."""
        extractor = FeatureExtractor(lookback_periods=15)
        bars = create_test_bars(20, trend="down")
        features = extractor.extract(bars)
        assert features is not None
        assert features.momentum < 0
        assert features.trend_strength < 50


class TestLinearModel:
    """Tests for LinearModel."""

    def test_create_model(self):
        """Test creating linear model."""
        config = ModelConfig(
            model_type=ModelType.LINEAR,
            name="test_model",
            symbol="AAPL",
        )
        model = LinearModel(config)
        assert model.config == config
        assert model.is_trained is False

    def test_train_insufficient_data(self):
        """Test training with insufficient data."""
        config = ModelConfig(
            model_type=ModelType.LINEAR,
            name="test",
            symbol="AAPL",
        )
        model = LinearModel(config)

        features = [
            FeatureSet(0.5, 1.0, 2.0, 50.0, 50.0, 1.0, 0.5, 0.0)
            for _ in range(5)
        ]
        targets = [1, -1, 1, -1, 1]

        result = model.train(features, targets)
        assert result.success is False
        assert "Insufficient" in result.error_message

    def test_train_success(self):
        """Test successful training."""
        config = ModelConfig(
            model_type=ModelType.LINEAR,
            name="test",
            symbol="AAPL",
            features=["returns", "momentum", "rsi"],
        )
        model = LinearModel(config)

        # Create training data
        features = []
        targets = []
        for i in range(50):
            # Up trend features -> target 1
            if i % 2 == 0:
                features.append(FeatureSet(1.0, 0.5, 5.0, 65.0, 70.0, 1.2, 0.8, 1.0))
                targets.append(1)
            else:
                # Down trend features -> target -1
                features.append(FeatureSet(-1.0, 0.5, -5.0, 35.0, 30.0, 1.2, 0.2, -1.0))
                targets.append(-1)

        result = model.train(features, targets)
        assert result.success is True
        assert result.train_samples > 0
        assert result.test_samples > 0
        assert model.is_trained is True

    def test_predict_untrained(self):
        """Test prediction with untrained model."""
        config = ModelConfig(
            model_type=ModelType.LINEAR,
            name="test",
            symbol="AAPL",
        )
        model = LinearModel(config)

        features = FeatureSet(0.5, 1.0, 2.0, 50.0, 50.0, 1.0, 0.5, 0.0)
        prediction = model.predict(features)

        assert prediction.direction == PredictionDirection.NEUTRAL
        assert prediction.confidence == 0.0

    def test_get_metadata(self):
        """Test getting model metadata."""
        config = ModelConfig(
            model_type=ModelType.LINEAR,
            name="test_model",
            symbol="AAPL",
        )
        model = LinearModel(config)

        metadata = model.get_metadata()
        assert isinstance(metadata, ModelMetadata)
        assert metadata.name == "test_model"
        assert metadata.symbol == "AAPL"
        assert metadata.model_type == ModelType.LINEAR


class TestModelRegistry:
    """Tests for ModelRegistry."""

    def test_create_registry(self):
        """Test creating registry."""
        registry = ModelRegistry()
        assert len(registry.list_models()) == 0

    def test_create_model(self):
        """Test creating model through registry."""
        registry = ModelRegistry()
        config = ModelConfig(
            model_type=ModelType.LINEAR,
            name="test",
            symbol="AAPL",
        )
        model = registry.create_model(config)
        assert model is not None
        assert len(registry.list_models()) == 1

    def test_get_model(self):
        """Test getting model by ID."""
        registry = ModelRegistry()
        config = ModelConfig(
            model_type=ModelType.LINEAR,
            name="test",
            symbol="AAPL",
        )
        model = registry.create_model(config)
        retrieved = registry.get_model(model.model_id)
        assert retrieved == model

    def test_get_model_not_found(self):
        """Test getting non-existent model."""
        registry = ModelRegistry()
        retrieved = registry.get_model("nonexistent")
        assert retrieved is None

    def test_remove_model(self):
        """Test removing model."""
        registry = ModelRegistry()
        config = ModelConfig(
            model_type=ModelType.LINEAR,
            name="test",
            symbol="AAPL",
        )
        model = registry.create_model(config)
        result = registry.remove_model(model.model_id)
        assert result is True
        assert len(registry.list_models()) == 0

    def test_list_models(self):
        """Test listing models."""
        registry = ModelRegistry()
        for i in range(3):
            config = ModelConfig(
                model_type=ModelType.LINEAR,
                name=f"model_{i}",
                symbol="AAPL",
            )
            registry.create_model(config)

        models = registry.list_models()
        assert len(models) == 3


class TestPredictionEngine:
    """Tests for PredictionEngine."""

    def test_create_engine(self):
        """Test creating prediction engine."""
        engine = PredictionEngine()
        assert engine is not None

    def test_predict_no_model(self):
        """Test prediction with no model."""
        engine = PredictionEngine()
        bars = create_test_bars(30)
        prediction = engine.predict("nonexistent", bars)
        assert prediction is None

    def test_predict_untrained_model(self):
        """Test prediction with untrained model."""
        registry = ModelRegistry()
        config = ModelConfig(
            model_type=ModelType.LINEAR,
            name="test",
            symbol="AAPL",
        )
        model = registry.create_model(config)

        engine = PredictionEngine(registry=registry)
        bars = create_test_bars(30)
        prediction = engine.predict(model.model_id, bars)
        assert prediction is None  # Model not trained

    def test_get_recent_predictions(self):
        """Test getting recent predictions."""
        engine = PredictionEngine()

        # Manually store some predictions
        for i in range(5):
            pred = Prediction(
                model_id=f"model_{i}",
                symbol="AAPL",
                direction=PredictionDirection.LONG,
                confidence=0.8,
                predicted_return=1.0,
                features_used={},
            )
            engine._store_prediction(pred)

        predictions = engine.get_recent_predictions("AAPL", limit=3)
        assert len(predictions) == 3

    def test_get_consensus_empty(self):
        """Test consensus with no models."""
        engine = PredictionEngine()
        bars = create_test_bars(30)
        consensus = engine.get_consensus("AAPL", bars)
        assert consensus is None


class TestTrainingResult:
    """Tests for TrainingResult dataclass."""

    def test_create_result(self):
        """Test creating training result."""
        result = TrainingResult(
            model_id="test123",
            success=True,
            train_samples=100,
            test_samples=20,
            train_accuracy=0.85,
            test_accuracy=0.80,
            feature_importance={"returns": 0.3, "rsi": 0.7},
            training_time_seconds=1.5,
        )
        assert result.success is True
        assert result.train_samples == 100
        assert result.train_accuracy == 0.85

    def test_result_to_dict(self):
        """Test training result to_dict."""
        result = TrainingResult(
            model_id="test",
            success=True,
            train_samples=50,
            test_samples=10,
            train_accuracy=0.75,
            test_accuracy=0.70,
            feature_importance={},
            training_time_seconds=0.5,
        )
        data = result.to_dict()
        assert data["success"] is True
        assert data["train_samples"] == 50


class TestModelMetadata:
    """Tests for ModelMetadata dataclass."""

    def test_create_metadata(self):
        """Test creating model metadata."""
        now = datetime.now()
        metadata = ModelMetadata(
            model_id="test123",
            name="test_model",
            model_type=ModelType.LINEAR,
            symbol="AAPL",
            interval="1m",
            created_at=now,
            last_trained=now,
            train_samples=100,
            accuracy=0.85,
            feature_importance={"returns": 0.5},
        )
        assert metadata.model_id == "test123"
        assert metadata.accuracy == 0.85

    def test_metadata_to_dict(self):
        """Test metadata to_dict."""
        now = datetime.now()
        metadata = ModelMetadata(
            model_id="test",
            name="test",
            model_type=ModelType.LINEAR,
            symbol="AAPL",
            interval="1m",
            created_at=now,
            last_trained=now,
            train_samples=50,
            accuracy=0.75,
            feature_importance={},
        )
        data = metadata.to_dict()
        assert data["model_type"] == "linear"
        assert data["accuracy"] == 0.75
