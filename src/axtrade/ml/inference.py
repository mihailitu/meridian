"""ML inference engine for real-time predictions."""

from datetime import datetime
from typing import Optional

from axtrade.common import get_logger

from .features import FeatureExtractor
from .models import BaseModel, ModelRegistry
from .types import ModelConfig, Prediction, PredictionDirection


class PredictionEngine:
    """Engine for making real-time predictions using ML models.

    Manages multiple models and provides a unified interface for predictions.
    """

    def __init__(self, registry: Optional[ModelRegistry] = None):
        """Initialize prediction engine.

        Args:
            registry: Model registry to use (creates new one if not provided)
        """
        self.logger = get_logger("ml.inference")
        self.registry = registry or ModelRegistry()
        self._extractors: dict[int, FeatureExtractor] = {}
        self._predictions: dict[str, list[Prediction]] = {}  # symbol -> recent predictions
        self._max_predictions = 100

    def get_extractor(self, lookback_periods: int) -> FeatureExtractor:
        """Get or create a feature extractor.

        Args:
            lookback_periods: Number of periods for feature extraction

        Returns:
            FeatureExtractor instance
        """
        if lookback_periods not in self._extractors:
            self._extractors[lookback_periods] = FeatureExtractor(lookback_periods)
        return self._extractors[lookback_periods]

    def predict(self, model_id: str, bars: list[dict]) -> Optional[Prediction]:
        """Make a prediction using a specific model.

        Args:
            model_id: ID of the model to use
            bars: List of bar data dictionaries

        Returns:
            Prediction if successful, None otherwise
        """
        model = self.registry.get_model(model_id)
        if not model:
            self.logger.warning("Model not found", model_id=model_id)
            return None

        if not model.is_trained:
            self.logger.warning("Model not trained", model_id=model_id)
            return None

        extractor = self.get_extractor(model.config.lookback_periods)
        features = extractor.extract(bars)

        if not features:
            self.logger.debug("Insufficient data for prediction", model_id=model_id)
            return None

        prediction = model.predict(features)

        # Store prediction
        self._store_prediction(prediction)

        return prediction

    def predict_all(self, symbol: str, bars: list[dict]) -> list[Prediction]:
        """Make predictions using all models for a symbol.

        Args:
            symbol: Symbol to predict for
            bars: List of bar data dictionaries

        Returns:
            List of predictions from all applicable models
        """
        predictions = []

        for metadata in self.registry.list_models():
            if metadata.symbol != symbol or not metadata.is_active:
                continue

            prediction = self.predict(metadata.model_id, bars)
            if prediction:
                predictions.append(prediction)

        return predictions

    def get_consensus(self, symbol: str, bars: list[dict]) -> Optional[Prediction]:
        """Get consensus prediction from all models.

        Aggregates predictions from all models for a symbol and returns
        a consensus prediction based on weighted voting.

        Args:
            symbol: Symbol to predict for
            bars: List of bar data dictionaries

        Returns:
            Consensus prediction if available
        """
        predictions = self.predict_all(symbol, bars)

        if not predictions:
            return None

        # Calculate weighted votes
        long_score = 0.0
        short_score = 0.0
        neutral_score = 0.0
        total_confidence = 0.0

        for pred in predictions:
            weight = pred.confidence
            total_confidence += weight

            if pred.direction == PredictionDirection.LONG:
                long_score += weight
            elif pred.direction == PredictionDirection.SHORT:
                short_score += weight
            else:
                neutral_score += weight

        # Normalize scores
        if total_confidence > 0:
            long_score /= total_confidence
            short_score /= total_confidence
            neutral_score /= total_confidence

        # Determine consensus
        if long_score > short_score and long_score > neutral_score:
            direction = PredictionDirection.LONG
            confidence = long_score
        elif short_score > long_score and short_score > neutral_score:
            direction = PredictionDirection.SHORT
            confidence = short_score
        else:
            direction = PredictionDirection.NEUTRAL
            confidence = neutral_score

        # Average predicted return
        avg_return = sum(p.predicted_return for p in predictions) / len(predictions)

        # Merge features from all predictions
        merged_features = {}
        for pred in predictions:
            merged_features.update(pred.features_used)

        return Prediction(
            model_id="consensus",
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            predicted_return=avg_return,
            features_used=merged_features,
        )

    def _store_prediction(self, prediction: Prediction) -> None:
        """Store a prediction for history tracking."""
        symbol = prediction.symbol
        if symbol not in self._predictions:
            self._predictions[symbol] = []

        self._predictions[symbol].append(prediction)

        # Trim to max size
        if len(self._predictions[symbol]) > self._max_predictions:
            self._predictions[symbol] = self._predictions[symbol][-self._max_predictions:]

    def get_recent_predictions(
        self, symbol: str, limit: int = 20
    ) -> list[Prediction]:
        """Get recent predictions for a symbol.

        Args:
            symbol: Symbol to get predictions for
            limit: Maximum number of predictions to return

        Returns:
            List of recent predictions
        """
        predictions = self._predictions.get(symbol, [])
        return predictions[-limit:]

    def get_prediction_accuracy(self, symbol: str, actual_returns: list[float]) -> float:
        """Calculate prediction accuracy based on actual returns.

        Args:
            symbol: Symbol to check accuracy for
            actual_returns: List of actual returns corresponding to predictions

        Returns:
            Accuracy as a percentage (0-100)
        """
        predictions = self._predictions.get(symbol, [])

        if not predictions or len(predictions) != len(actual_returns):
            return 0.0

        correct = 0
        for pred, actual in zip(predictions, actual_returns):
            if pred.direction == PredictionDirection.LONG and actual > 0:
                correct += 1
            elif pred.direction == PredictionDirection.SHORT and actual < 0:
                correct += 1
            elif pred.direction == PredictionDirection.NEUTRAL and abs(actual) < 0.1:
                correct += 1

        return (correct / len(predictions)) * 100
