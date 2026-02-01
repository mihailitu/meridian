export type ModelType = 'linear' | 'logistic' | 'ensemble';
export type PredictionDirection = 'long' | 'short' | 'neutral';

export interface MLModel {
    model_id: string;
    name: string;
    model_type: ModelType;
    symbol: string;
    interval: string;
    created_at: string;
    last_trained: string;
    train_samples: number;
    accuracy: number;
    feature_importance: Record<string, number>;
    is_active: boolean;
}

export interface MLPrediction {
    model_id: string;
    symbol: string;
    direction: PredictionDirection;
    confidence: number;
    predicted_return: number;
    features_used: Record<string, number>;
    timestamp: string;
    is_actionable: boolean;
}

export interface MLSummary {
    total_models: number;
    active_models: number;
    average_accuracy: number;
    symbols_covered: string[];
    models_by_symbol: Record<string, string[]>;
}

export interface CreateModelRequest {
    name: string;
    symbol: string;
    model_type?: ModelType;
    interval?: string;
    lookback_periods?: number;
    features?: string[];
    threshold?: number;
}

export const DIRECTION_LABELS: Record<PredictionDirection, string> = {
    long: 'Long',
    short: 'Short',
    neutral: 'Neutral',
};

export const DIRECTION_COLORS: Record<PredictionDirection, string> = {
    long: 'text-emerald-400',
    short: 'text-red-400',
    neutral: 'text-slate-400',
};

export const MODEL_TYPE_LABELS: Record<ModelType, string> = {
    linear: 'Linear',
    logistic: 'Logistic',
    ensemble: 'Ensemble',
};
