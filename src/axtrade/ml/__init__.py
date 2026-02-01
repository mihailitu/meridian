"""Machine learning module for trading predictions."""

from .features import FeatureExtractor, FeatureSet
from .inference import PredictionEngine
from .models import LinearModel, ModelRegistry
from .types import (
    ModelConfig,
    ModelMetadata,
    ModelType,
    Prediction,
    PredictionDirection,
    TrainingResult,
)

__all__ = [
    "FeatureExtractor",
    "FeatureSet",
    "LinearModel",
    "ModelConfig",
    "ModelMetadata",
    "ModelRegistry",
    "ModelType",
    "Prediction",
    "PredictionDirection",
    "PredictionEngine",
    "TrainingResult",
]
