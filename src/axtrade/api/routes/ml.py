"""ML API endpoints."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from axtrade.ml import (
    FeatureExtractor,
    LinearModel,
    ModelConfig,
    ModelRegistry,
    ModelType,
    PredictionDirection,
    PredictionEngine,
)

router = APIRouter()

# Global instances
_registry: Optional[ModelRegistry] = None
_engine: Optional[PredictionEngine] = None


def get_registry() -> ModelRegistry:
    """Get or create model registry."""
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry


def get_engine() -> PredictionEngine:
    """Get or create prediction engine."""
    global _engine
    if _engine is None:
        _engine = PredictionEngine(registry=get_registry())
    return _engine


# Request/Response models
class CreateModelRequest(BaseModel):
    """Request to create a new model."""

    name: str
    symbol: str
    model_type: str = "linear"
    interval: str = "1m"
    lookback_periods: int = 20
    features: list[str] = ["returns", "volatility", "momentum", "rsi", "trend_strength"]
    threshold: float = 0.6


class ModelResponse(BaseModel):
    """Model metadata response."""

    model_id: str
    name: str
    model_type: str
    symbol: str
    interval: str
    created_at: str
    last_trained: str
    train_samples: int
    accuracy: float
    feature_importance: dict[str, float]
    is_active: bool


class PredictionResponse(BaseModel):
    """Prediction response."""

    model_id: str
    symbol: str
    direction: str
    confidence: float
    predicted_return: float
    features_used: dict[str, float]
    timestamp: str
    is_actionable: bool


class TrainingResponse(BaseModel):
    """Training result response."""

    model_id: str
    success: bool
    train_samples: int
    test_samples: int
    train_accuracy: float
    test_accuracy: float
    feature_importance: dict[str, float]
    training_time_seconds: float
    error_message: Optional[str]


@router.get("/ml/models", response_model=list[ModelResponse])
async def list_models() -> list[ModelResponse]:
    """List all ML models."""
    registry = get_registry()
    models = []
    for metadata in registry.list_models():
        models.append(
            ModelResponse(
                model_id=metadata.model_id,
                name=metadata.name,
                model_type=metadata.model_type.value,
                symbol=metadata.symbol,
                interval=metadata.interval,
                created_at=metadata.created_at.isoformat(),
                last_trained=metadata.last_trained.isoformat(),
                train_samples=metadata.train_samples,
                accuracy=metadata.accuracy,
                feature_importance=metadata.feature_importance,
                is_active=metadata.is_active,
            )
        )
    return models


@router.post("/ml/models", response_model=ModelResponse)
async def create_model(request: CreateModelRequest) -> ModelResponse:
    """Create a new ML model."""
    registry = get_registry()

    try:
        model_type = ModelType(request.model_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid model type: {request.model_type}. Valid types: {[t.value for t in ModelType]}",
        )

    config = ModelConfig(
        model_type=model_type,
        name=request.name,
        symbol=request.symbol,
        interval=request.interval,
        lookback_periods=request.lookback_periods,
        features=request.features,
        threshold=request.threshold,
    )

    model = registry.create_model(config)
    metadata = model.get_metadata()

    return ModelResponse(
        model_id=metadata.model_id,
        name=metadata.name,
        model_type=metadata.model_type.value,
        symbol=metadata.symbol,
        interval=metadata.interval,
        created_at=metadata.created_at.isoformat(),
        last_trained=metadata.last_trained.isoformat(),
        train_samples=metadata.train_samples,
        accuracy=metadata.accuracy,
        feature_importance=metadata.feature_importance,
        is_active=metadata.is_active,
    )


@router.get("/ml/models/{model_id}", response_model=ModelResponse)
async def get_model(model_id: str) -> ModelResponse:
    """Get a specific model by ID."""
    registry = get_registry()
    model = registry.get_model(model_id)

    if not model:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")

    metadata = model.get_metadata()
    return ModelResponse(
        model_id=metadata.model_id,
        name=metadata.name,
        model_type=metadata.model_type.value,
        symbol=metadata.symbol,
        interval=metadata.interval,
        created_at=metadata.created_at.isoformat(),
        last_trained=metadata.last_trained.isoformat(),
        train_samples=metadata.train_samples,
        accuracy=metadata.accuracy,
        feature_importance=metadata.feature_importance,
        is_active=metadata.is_active,
    )


@router.delete("/ml/models/{model_id}")
async def delete_model(model_id: str) -> dict:
    """Delete a model."""
    registry = get_registry()

    if not registry.remove_model(model_id):
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")

    return {"status": "ok", "message": f"Model {model_id} deleted"}


@router.get("/ml/predictions/{symbol}", response_model=list[PredictionResponse])
async def get_predictions(
    symbol: str,
    limit: int = Query(20, ge=1, le=100),
) -> list[PredictionResponse]:
    """Get recent predictions for a symbol."""
    engine = get_engine()
    predictions = engine.get_recent_predictions(symbol, limit)

    return [
        PredictionResponse(
            model_id=p.model_id,
            symbol=p.symbol,
            direction=p.direction.value,
            confidence=p.confidence,
            predicted_return=p.predicted_return,
            features_used=p.features_used,
            timestamp=p.timestamp.isoformat(),
            is_actionable=p.is_actionable,
        )
        for p in predictions
    ]


@router.get("/ml/summary")
async def get_ml_summary() -> dict:
    """Get ML system summary."""
    registry = get_registry()
    models = registry.list_models()

    active_models = [m for m in models if m.is_active]
    avg_accuracy = (
        sum(m.accuracy for m in active_models) / len(active_models)
        if active_models
        else 0.0
    )

    # Group by symbol
    symbols = {}
    for m in models:
        if m.symbol not in symbols:
            symbols[m.symbol] = []
        symbols[m.symbol].append(m.name)

    return {
        "total_models": len(models),
        "active_models": len(active_models),
        "average_accuracy": round(avg_accuracy * 100, 2),
        "symbols_covered": list(symbols.keys()),
        "models_by_symbol": symbols,
    }
