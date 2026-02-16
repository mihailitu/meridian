"""ML-based prediction strategy."""

from collections import deque
from decimal import Decimal
from typing import Optional

from axtrade.common import get_logger
from axtrade.ml import (
    FeatureExtractor,
    LinearModel,
    ModelConfig,
    ModelRegistry,
    ModelType,
    PredictionDirection,
    PredictionEngine,
)
from axtrade.oms import Order, OrderSide, OrderType

from .base import BarWithIndicators, BaseStrategy, Signal


class MLPredictionStrategy(BaseStrategy):
    """Strategy that uses ML models for trading decisions.

    This strategy:
    1. Extracts features from recent bar data
    2. Uses trained ML models to predict price direction
    3. Generates buy/sell signals based on predictions
    4. Manages positions with configurable size and stop-loss
    """

    def __init__(self, strategy_id: str, config: dict):
        """Initialize ML prediction strategy.

        Args:
            strategy_id: Unique strategy identifier
            config: Strategy configuration with keys:
                - lookback_periods: Periods for feature extraction (default: 20)
                - confidence_threshold: Min confidence for signals (default: 0.6)
                - position_size: Number of shares per trade (default: 100)
                - stop_loss_pct: Stop loss percentage (default: 0.02)
                - take_profit_pct: Take profit percentage (default: 0.04)
                - model_type: Type of ML model (default: "linear")
                - auto_train: Auto-train model when data available (default: True)
                - train_samples: Samples needed before training (default: 100)
        """
        super().__init__(strategy_id, config)
        self.logger = get_logger(f"strategy.{strategy_id}")

        # Configuration
        self.lookback_periods = config.get("lookback_periods", 20)
        self.confidence_threshold = config.get("confidence_threshold", 0.6)
        self.position_size = config.get("position_size", 100)
        self.stop_loss_pct = config.get("stop_loss_pct", 0.02)
        self.take_profit_pct = config.get("take_profit_pct", 0.04)
        self.model_type = config.get("model_type", "linear")
        self.auto_train = config.get("auto_train", True)
        self.train_samples = config.get("train_samples", 100)

        # ML components
        self.registry = ModelRegistry()
        self.engine = PredictionEngine(registry=self.registry)
        self.feature_extractor = FeatureExtractor(self.lookback_periods)

        # Data buffers per symbol
        self._bar_buffers: dict[str, deque] = {}
        self._models: dict[str, str] = {}  # symbol -> model_id

        # Training data collection.
        # Use bounded deques to cap memory usage. We keep up to 5x the
        # required training samples so there is enough history for
        # retraining while old observations are automatically evicted.
        self._max_training_samples = self.train_samples * 5
        self._training_features: dict[str, deque] = {}
        self._training_targets: dict[str, deque] = {}
        self._last_prices: dict[str, float] = {}

        # Flag to avoid scheduling duplicate background training runs.
        self._training_in_progress: dict[str, bool] = {}

    @property
    def name(self) -> str:
        """Strategy name."""
        return "ML Prediction"

    def _get_or_create_model(self, symbol: str) -> Optional[str]:
        """Get or create ML model for a symbol.

        Args:
            symbol: Symbol to get model for

        Returns:
            Model ID if available
        """
        if symbol in self._models:
            return self._models[symbol]

        # Create a new model
        config = ModelConfig(
            model_type=ModelType(self.model_type),
            name=f"{self.strategy_id}_{symbol}",
            symbol=symbol,
            lookback_periods=self.lookback_periods,
            threshold=self.confidence_threshold,
        )

        model = self.registry.create_model(config)
        self._models[symbol] = model.model_id

        self.logger.info(
            "Created ML model",
            symbol=symbol,
            model_id=model.model_id,
        )

        return model.model_id

    def _update_bar_buffer(self, data: BarWithIndicators) -> list[dict]:
        """Update bar buffer and return recent bars.

        Args:
            data: New bar data

        Returns:
            List of recent bar dicts
        """
        symbol = data.symbol

        if symbol not in self._bar_buffers:
            self._bar_buffers[symbol] = deque(maxlen=self.lookback_periods * 2)

        # Convert bar to dict format expected by feature extractor
        bar_dict = {
            "symbol": data.bar.symbol,
            "time": data.bar.timestamp.isoformat(),
            "open": data.bar.open,
            "high": data.bar.high,
            "low": data.bar.low,
            "close": data.bar.close,
            "volume": data.bar.volume,
            "rsi_14": data.rsi_14,
            "sma_20": data.sma_20,
        }

        self._bar_buffers[symbol].append(bar_dict)

        return list(self._bar_buffers[symbol])

    def _collect_training_data(
        self, symbol: str, features: "FeatureSet", current_price: float
    ) -> None:
        """Collect training data from market observations.

        Args:
            symbol: Symbol being observed
            features: Extracted features
            current_price: Current close price
        """
        from axtrade.ml.features import FeatureSet

        if symbol not in self._training_features:
            self._training_features[symbol] = deque(maxlen=self._max_training_samples)
            self._training_targets[symbol] = deque(maxlen=self._max_training_samples)

        # If we have a previous price, calculate target
        if symbol in self._last_prices:
            prev_price = self._last_prices[symbol]
            if prev_price > 0:
                returns = (current_price - prev_price) / prev_price

                # Target: 1 for up, -1 for down, 0 for flat
                if returns > 0.001:
                    target = 1
                elif returns < -0.001:
                    target = -1
                else:
                    target = 0

                # Store previous features with current target
                if self._training_features[symbol]:
                    self._training_targets[symbol].append(target)

        # Store current features for next iteration
        self._training_features[symbol].append(features)
        self._last_prices[symbol] = current_price

    def _maybe_train_model(self, symbol: str) -> None:
        """Schedule model training on a background thread if ready.

        Training is CPU-bound (gradient descent iterations), so running it
        on the event loop would block tick/bar processing for all strategies.
        Instead we snapshot the training data and hand it off to a thread via
        run_in_executor. The model's is_trained flag acts as the
        synchronisation point -- predict() checks it before using weights,
        and train() sets it atomically at the end. Python's GIL guarantees
        dict/float attribute assignments are atomic, so predict() will
        always see a consistent weights dict (either pre- or post-training).

        The _training_in_progress flag prevents duplicate concurrent runs
        for the same symbol.
        """
        features = self._training_features.get(symbol, deque())
        targets = self._training_targets.get(symbol, deque())

        if len(targets) < self.train_samples:
            return

        model_id = self._models.get(symbol)
        if not model_id:
            return

        model = self.registry.get_model(model_id)
        if not model:
            return

        # Already trained or training in progress -- nothing to do.
        if model.is_trained or self._training_in_progress.get(symbol, False):
            return

        # Snapshot current training data so the background thread works on
        # an immutable copy while the deques keep collecting new observations.
        train_features = list(features)[:len(targets)]
        train_targets = list(targets)

        self._training_in_progress[symbol] = True

        self.logger.info(
            "Training ML model",
            symbol=symbol,
            samples=len(train_targets),
        )

        # on_bar() is already running in a thread pool (via run_in_executor
        # in StrategyRunner), so run training synchronously here rather than
        # trying to schedule another executor from a non-event-loop thread.
        try:
            result = model.train(train_features, train_targets)
            if result.success:
                self.logger.info(
                    "Model trained successfully",
                    symbol=symbol,
                    accuracy=round(result.test_accuracy * 100, 1),
                )
            else:
                self.logger.warning(
                    "Model training failed",
                    symbol=symbol,
                    error=result.error_message,
                )
        except Exception as exc:
            self.logger.error(
                "Model training raised exception",
                symbol=symbol,
                error=str(exc),
            )
        finally:
            self._training_in_progress[symbol] = False

    def on_bar(self, data: BarWithIndicators) -> Optional[Order]:
        """Process bar and generate orders based on ML predictions.

        Args:
            data: Bar with indicators

        Returns:
            Order if signal generated
        """
        if not self.enabled:
            return None

        symbol = data.symbol

        # Update bar buffer
        bars = self._update_bar_buffer(data)

        # Ensure we have a model
        model_id = self._get_or_create_model(symbol)
        if not model_id:
            return None

        # Extract features
        features = self.feature_extractor.extract(bars)
        if not features:
            return None

        # Collect training data
        if self.auto_train:
            self._collect_training_data(symbol, features, data.close)
            self._maybe_train_model(symbol)

        # Get model and make prediction
        model = self.registry.get_model(model_id)
        if not model or not model.is_trained:
            return None

        prediction = model.predict(features)

        # Check existing position
        position = self.get_position(symbol)

        # Generate signal based on prediction
        signal = self._generate_signal(data, prediction, position)

        if signal == Signal.HOLD:
            return None

        # Create order based on signal
        return self._create_order(data, signal, position)

    def _generate_signal(
        self,
        data: BarWithIndicators,
        prediction: "Prediction",
        position: Optional["Position"],
    ) -> Signal:
        """Generate trading signal from ML prediction.

        Args:
            data: Current bar data
            prediction: ML prediction
            position: Current position if any

        Returns:
            Trading signal
        """
        from axtrade.ml import Prediction
        from axtrade.oms import Position

        # Check stop-loss / take-profit if in position
        if position:
            avg_entry = float(position.avg_entry_price)
            current_price = data.close

            if position.side == "long":
                pnl_pct = (current_price - avg_entry) / avg_entry
                if pnl_pct <= -self.stop_loss_pct:
                    self.logger.info(
                        "Stop loss triggered",
                        symbol=data.symbol,
                        pnl_pct=round(pnl_pct * 100, 2),
                    )
                    return Signal.CLOSE
                if pnl_pct >= self.take_profit_pct:
                    self.logger.info(
                        "Take profit triggered",
                        symbol=data.symbol,
                        pnl_pct=round(pnl_pct * 100, 2),
                    )
                    return Signal.CLOSE
            else:  # short
                pnl_pct = (avg_entry - current_price) / avg_entry
                if pnl_pct <= -self.stop_loss_pct:
                    self.logger.info(
                        "Stop loss triggered",
                        symbol=data.symbol,
                        pnl_pct=round(pnl_pct * 100, 2),
                    )
                    return Signal.CLOSE
                if pnl_pct >= self.take_profit_pct:
                    self.logger.info(
                        "Take profit triggered",
                        symbol=data.symbol,
                        pnl_pct=round(pnl_pct * 100, 2),
                    )
                    return Signal.CLOSE

        # Check if prediction is actionable
        if not prediction.is_actionable:
            return Signal.HOLD

        if prediction.confidence < self.confidence_threshold:
            return Signal.HOLD

        # Generate signal based on prediction direction
        if prediction.direction == PredictionDirection.LONG:
            if position is None:
                self.logger.info(
                    "ML buy signal",
                    symbol=data.symbol,
                    confidence=round(prediction.confidence, 2),
                    predicted_return=round(prediction.predicted_return, 2),
                )
                return Signal.BUY
            elif position.side == "short":
                return Signal.CLOSE

        elif prediction.direction == PredictionDirection.SHORT:
            if position is None:
                self.logger.info(
                    "ML sell signal",
                    symbol=data.symbol,
                    confidence=round(prediction.confidence, 2),
                    predicted_return=round(prediction.predicted_return, 2),
                )
                return Signal.SELL
            elif position.side == "long":
                return Signal.CLOSE

        return Signal.HOLD

    def _create_order(
        self,
        data: BarWithIndicators,
        signal: Signal,
        position: Optional["Position"],
    ) -> Optional[Order]:
        """Create order from signal.

        Args:
            data: Current bar data
            signal: Trading signal
            position: Current position

        Returns:
            Order to submit
        """
        from axtrade.oms import Position

        if signal == Signal.HOLD:
            return None

        if signal == Signal.CLOSE and position:
            # Close existing position
            side = OrderSide.SELL if position.side == "long" else OrderSide.BUY
            return Order(
                strategy_id=self.strategy_id,
                symbol=data.symbol,
                side=side,
                quantity=Decimal(str(abs(position.quantity))),
                order_type=OrderType.MARKET,
            )

        if signal == Signal.BUY:
            return Order(
                strategy_id=self.strategy_id,
                symbol=data.symbol,
                side=OrderSide.BUY,
                quantity=Decimal(str(self.position_size)),
                order_type=OrderType.MARKET,
            )

        if signal == Signal.SELL:
            return Order(
                strategy_id=self.strategy_id,
                symbol=data.symbol,
                side=OrderSide.SELL,
                quantity=Decimal(str(self.position_size)),
                order_type=OrderType.MARKET,
            )

        return None
