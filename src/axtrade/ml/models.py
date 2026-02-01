"""ML model implementations."""

import json
import math
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional

from .features import FeatureSet
from .types import (
    ModelConfig,
    ModelMetadata,
    ModelType,
    Prediction,
    PredictionDirection,
    TrainingResult,
)


class BaseModel(ABC):
    """Base class for ML models."""

    def __init__(self, config: ModelConfig):
        """Initialize model.

        Args:
            config: Model configuration
        """
        self.config = config
        self.model_id = str(uuid.uuid4())[:8]
        self.weights: dict[str, float] = {}
        self.bias: float = 0.0
        self.is_trained = False
        self.train_samples = 0
        self.accuracy = 0.0
        self.feature_importance: dict[str, float] = {}
        self.created_at = datetime.now()
        self.last_trained: Optional[datetime] = None

    @abstractmethod
    def train(self, features: list[FeatureSet], targets: list[int]) -> TrainingResult:
        """Train the model.

        Args:
            features: List of feature sets
            targets: List of target values (1 for up, -1 for down, 0 for neutral)

        Returns:
            TrainingResult with training metrics
        """
        pass

    @abstractmethod
    def predict(self, features: FeatureSet) -> Prediction:
        """Make a prediction.

        Args:
            features: Feature set for prediction

        Returns:
            Prediction with direction and confidence
        """
        pass

    def get_metadata(self) -> ModelMetadata:
        """Get model metadata."""
        return ModelMetadata(
            model_id=self.model_id,
            name=self.config.name,
            model_type=self.config.model_type,
            symbol=self.config.symbol,
            interval=self.config.interval,
            created_at=self.created_at,
            last_trained=self.last_trained or self.created_at,
            train_samples=self.train_samples,
            accuracy=self.accuracy,
            feature_importance=self.feature_importance,
            is_active=self.is_trained,
        )

    def save(self, path: Path) -> None:
        """Save model to disk."""
        model_data = {
            "model_id": self.model_id,
            "config": self.config.to_dict(),
            "weights": self.weights,
            "bias": self.bias,
            "is_trained": self.is_trained,
            "train_samples": self.train_samples,
            "accuracy": self.accuracy,
            "feature_importance": self.feature_importance,
            "created_at": self.created_at.isoformat(),
            "last_trained": self.last_trained.isoformat() if self.last_trained else None,
        }
        path.write_text(json.dumps(model_data, indent=2))

    def load(self, path: Path) -> None:
        """Load model from disk."""
        model_data = json.loads(path.read_text())
        self.model_id = model_data["model_id"]
        self.weights = model_data["weights"]
        self.bias = model_data["bias"]
        self.is_trained = model_data["is_trained"]
        self.train_samples = model_data["train_samples"]
        self.accuracy = model_data["accuracy"]
        self.feature_importance = model_data["feature_importance"]
        self.created_at = datetime.fromisoformat(model_data["created_at"])
        if model_data["last_trained"]:
            self.last_trained = datetime.fromisoformat(model_data["last_trained"])


class LinearModel(BaseModel):
    """Simple linear model for price direction prediction.

    Uses a linear combination of features to predict price direction.
    Training uses gradient descent to optimize weights.
    """

    def __init__(self, config: ModelConfig):
        """Initialize linear model."""
        super().__init__(config)
        self.learning_rate = 0.01
        self.iterations = 100

    def train(self, features: list[FeatureSet], targets: list[int]) -> TrainingResult:
        """Train the model using gradient descent.

        Args:
            features: List of feature sets
            targets: List of target values (1 for up, -1 for down, 0 for neutral)

        Returns:
            TrainingResult with training metrics
        """
        import time

        start_time = time.time()

        if len(features) < 10:
            return TrainingResult(
                model_id=self.model_id,
                success=False,
                train_samples=0,
                test_samples=0,
                train_accuracy=0.0,
                test_accuracy=0.0,
                feature_importance={},
                training_time_seconds=time.time() - start_time,
                error_message="Insufficient training data (need at least 10 samples)",
            )

        # Split into train/test (80/20)
        split_idx = int(len(features) * 0.8)
        train_features = features[:split_idx]
        train_targets = targets[:split_idx]
        test_features = features[split_idx:]
        test_targets = targets[split_idx:]

        # Initialize weights
        feature_names = self.config.features
        self.weights = {name: 0.0 for name in feature_names}
        self.bias = 0.0

        # Gradient descent training
        for _ in range(self.iterations):
            for feat, target in zip(train_features, train_targets):
                # Forward pass
                x = feat.to_vector(feature_names)
                prediction = self._forward(x)

                # Calculate error
                error = target - prediction

                # Update weights
                for i, name in enumerate(feature_names):
                    self.weights[name] += self.learning_rate * error * x[i]
                self.bias += self.learning_rate * error

        # Calculate accuracy
        train_correct = sum(
            1
            for f, t in zip(train_features, train_targets)
            if self._classify(f.to_vector(feature_names)) == t
        )
        train_accuracy = train_correct / len(train_features) if train_features else 0

        test_correct = sum(
            1
            for f, t in zip(test_features, test_targets)
            if self._classify(f.to_vector(feature_names)) == t
        )
        test_accuracy = test_correct / len(test_features) if test_features else 0

        # Calculate feature importance (absolute weights)
        total_weight = sum(abs(w) for w in self.weights.values()) or 1
        self.feature_importance = {
            name: abs(weight) / total_weight for name, weight in self.weights.items()
        }

        self.is_trained = True
        self.train_samples = len(features)
        self.accuracy = test_accuracy
        self.last_trained = datetime.now()

        return TrainingResult(
            model_id=self.model_id,
            success=True,
            train_samples=len(train_features),
            test_samples=len(test_features),
            train_accuracy=train_accuracy,
            test_accuracy=test_accuracy,
            feature_importance=self.feature_importance,
            training_time_seconds=time.time() - start_time,
        )

    def predict(self, features: FeatureSet) -> Prediction:
        """Make a prediction.

        Args:
            features: Feature set for prediction

        Returns:
            Prediction with direction and confidence
        """
        if not self.is_trained:
            return Prediction(
                model_id=self.model_id,
                symbol=self.config.symbol,
                direction=PredictionDirection.NEUTRAL,
                confidence=0.0,
                predicted_return=0.0,
                features_used=features.to_dict(),
            )

        x = features.to_vector(self.config.features)
        raw_prediction = self._forward(x)

        # Convert to direction and confidence
        if raw_prediction > self.config.threshold:
            direction = PredictionDirection.LONG
            confidence = min(raw_prediction, 1.0)
        elif raw_prediction < -self.config.threshold:
            direction = PredictionDirection.SHORT
            confidence = min(abs(raw_prediction), 1.0)
        else:
            direction = PredictionDirection.NEUTRAL
            confidence = 1.0 - abs(raw_prediction)

        # Estimate predicted return based on momentum and trend
        predicted_return = raw_prediction * 0.5  # Scale down

        return Prediction(
            model_id=self.model_id,
            symbol=self.config.symbol,
            direction=direction,
            confidence=confidence,
            predicted_return=predicted_return,
            features_used=features.to_dict(),
        )

    def _forward(self, x: list[float]) -> float:
        """Forward pass through the model."""
        if not self.weights:
            return 0.0

        weighted_sum = self.bias
        for i, name in enumerate(self.config.features):
            if i < len(x):
                weighted_sum += self.weights.get(name, 0) * x[i]

        # Apply sigmoid-like activation for bounded output
        return math.tanh(weighted_sum)

    def _classify(self, x: list[float]) -> int:
        """Classify input into direction."""
        pred = self._forward(x)
        if pred > self.config.threshold:
            return 1
        elif pred < -self.config.threshold:
            return -1
        return 0


class ModelRegistry:
    """Registry for managing ML models."""

    def __init__(self, models_dir: Optional[Path] = None):
        """Initialize model registry.

        Args:
            models_dir: Directory for storing models
        """
        self.models_dir = models_dir
        self._models: dict[str, BaseModel] = {}

    def create_model(self, config: ModelConfig) -> BaseModel:
        """Create a new model from config.

        Args:
            config: Model configuration

        Returns:
            Created model instance
        """
        if config.model_type == ModelType.LINEAR:
            model = LinearModel(config)
        else:
            # Default to linear for now
            model = LinearModel(config)

        self._models[model.model_id] = model
        return model

    def get_model(self, model_id: str) -> Optional[BaseModel]:
        """Get a model by ID."""
        return self._models.get(model_id)

    def list_models(self) -> list[ModelMetadata]:
        """List all models."""
        return [model.get_metadata() for model in self._models.values()]

    def remove_model(self, model_id: str) -> bool:
        """Remove a model."""
        if model_id in self._models:
            del self._models[model_id]
            return True
        return False

    def save_all(self) -> None:
        """Save all models to disk."""
        if not self.models_dir:
            return

        self.models_dir.mkdir(parents=True, exist_ok=True)
        for model_id, model in self._models.items():
            model.save(self.models_dir / f"{model_id}.json")

    def load_all(self) -> None:
        """Load all models from disk."""
        if not self.models_dir or not self.models_dir.exists():
            return

        for model_file in self.models_dir.glob("*.json"):
            try:
                model_data = json.loads(model_file.read_text())
                config = ModelConfig(
                    model_type=ModelType(model_data["config"]["model_type"]),
                    name=model_data["config"]["name"],
                    symbol=model_data["config"]["symbol"],
                    interval=model_data["config"]["interval"],
                    lookback_periods=model_data["config"]["lookback_periods"],
                    features=model_data["config"]["features"],
                    threshold=model_data["config"]["threshold"],
                )
                model = self.create_model(config)
                model.load(model_file)
            except Exception:
                # Skip invalid model files
                pass
