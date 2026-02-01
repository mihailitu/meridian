// Market regime types

export type MarketRegime =
    | 'trending_up'
    | 'trending_down'
    | 'ranging_quiet'
    | 'ranging_volatile'
    | 'breakout'
    | 'breakdown';

export type MarketTrend = 'bullish' | 'bearish' | 'neutral';

export type VolatilityState = 'low' | 'normal' | 'high' | 'extreme';

export interface RegimeCurrentResponse {
    symbol: string;
    interval: string;
    regime: MarketRegime | null;
    trend: MarketTrend | null;
    volatility: VolatilityState | null;
    trend_strength: number | null;
    volatility_percentile: number | null;
    timestamp: string;
}

export interface RegimeHistoryPoint {
    timestamp: string;
    regime: MarketRegime;
    trend: MarketTrend;
    volatility: VolatilityState;
    trend_strength: number;
    volatility_percentile: number;
}

export interface RegimeHistoryResponse {
    symbol: string;
    interval: string;
    history: RegimeHistoryPoint[];
}

export interface RegimeSummaryResponse {
    symbol: string;
    regime: MarketRegime | null;
    trend: MarketTrend | null;
    volatility: VolatilityState | null;
    last_price: number | null;
    timestamp: string | null;
}

export interface RegimeWebSocketUpdate {
    type: 'regime_update';
    data: {
        symbol: string;
        regime: MarketRegime;
        trend: MarketTrend;
        volatility: VolatilityState;
        trend_strength: number;
        volatility_percentile: number;
        timestamp: string;
    };
}
