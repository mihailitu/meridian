"""ML module types and data structures."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ModelType(Enum):
    """Types of ML models."""

    LINEAR = "linear"
    LOGISTIC = "logistic"
    ENSEMBLE = "ensemble"


class PredictionDirection(Enum):
    """Direction of a prediction."""

    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


@dataclass
class ModelConfig:
    """Configuration for an ML model."""

    model_type: ModelType
    name: str
    symbol: str
    interval: str = "1m"
    lookback_periods: int = 20
    features: list[str] = field(default_factory=lambda: [
        "returns", "volatility", "momentum", "rsi", "trend_strength"
    ])
    threshold: float = 0.6  # Confidence threshold for signals
    retrain_interval_hours: int = 24

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "model_type": self.model_type.value,
            "name": self.name,
            "symbol": self.symbol,
            "interval": self.interval,
            "lookback_periods": self.lookback_periods,
            "features": self.features,
            "threshold": self.threshold,
            "retrain_interval_hours": self.retrain_interval_hours,
        }


@dataclass
class ModelMetadata:
    """Metadata about a trained model."""

    model_id: str
    name: str
    model_type: ModelType
    symbol: str
    interval: str
    created_at: datetime
    last_trained: datetime
    train_samples: int
    accuracy: float
    feature_importance: dict[str, float]
    is_active: bool = True

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "model_id": self.model_id,
            "name": self.name,
            "model_type": self.model_type.value,
            "symbol": self.symbol,
            "interval": self.interval,
            "created_at": self.created_at.isoformat(),
            "last_trained": self.last_trained.isoformat(),
            "train_samples": self.train_samples,
            "accuracy": self.accuracy,
            "feature_importance": self.feature_importance,
            "is_active": self.is_active,
        }


@dataclass
class Prediction:
    """A prediction from an ML model."""

    model_id: str
    symbol: str
    direction: PredictionDirection
    confidence: float  # 0.0 to 1.0
    predicted_return: float  # Expected return (percentage)
    features_used: dict[str, float]
    timestamp: datetime = field(default_factory=lambda: datetime.now())

    @property
    def is_actionable(self) -> bool:
        """Check if prediction is strong enough to act on."""
        return self.confidence >= 0.6 and self.direction != PredictionDirection.NEUTRAL

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "model_id": self.model_id,
            "symbol": self.symbol,
            "direction": self.direction.value,
            "confidence": self.confidence,
            "predicted_return": self.predicted_return,
            "features_used": self.features_used,
            "timestamp": self.timestamp.isoformat(),
            "is_actionable": self.is_actionable,
        }


@dataclass
class TrainingResult:
    """Result of model training."""

    model_id: str
    success: bool
    train_samples: int
    test_samples: int
    train_accuracy: float
    test_accuracy: float
    feature_importance: dict[str, float]
    training_time_seconds: float
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "model_id": self.model_id,
            "success": self.success,
            "train_samples": self.train_samples,
            "test_samples": self.test_samples,
            "train_accuracy": self.train_accuracy,
            "test_accuracy": self.test_accuracy,
            "feature_importance": self.feature_importance,
            "training_time_seconds": self.training_time_seconds,
            "error_message": self.error_message,
        }
