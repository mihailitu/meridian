import React from 'react';
import type { MarketRegime, MarketTrend, VolatilityState } from '../types/regime';
import { TrendingUp, TrendingDown, Minus, Activity, Zap } from 'lucide-react';

interface RegimeIndicatorProps {
    regime: MarketRegime | null;
    trend: MarketTrend | null;
    volatility: VolatilityState | null;
    trendStrength?: number | null;
    volatilityPercentile?: number | null;
    size?: 'sm' | 'md' | 'lg';
    showLabels?: boolean;
}

const regimeConfig: Record<MarketRegime, { label: string; color: string; bg: string }> = {
    trending_up: { label: 'Trending Up', color: 'text-emerald-400', bg: 'bg-emerald-900/30' },
    trending_down: { label: 'Trending Down', color: 'text-rose-400', bg: 'bg-rose-900/30' },
    ranging_quiet: { label: 'Ranging Quiet', color: 'text-slate-400', bg: 'bg-slate-700/50' },
    ranging_volatile: { label: 'Ranging Volatile', color: 'text-amber-400', bg: 'bg-amber-900/30' },
    breakout: { label: 'Breakout', color: 'text-cyan-400', bg: 'bg-cyan-900/30' },
    breakdown: { label: 'Breakdown', color: 'text-purple-400', bg: 'bg-purple-900/30' },
};

const trendConfig: Record<MarketTrend, { icon: typeof TrendingUp; color: string }> = {
    bullish: { icon: TrendingUp, color: 'text-emerald-400' },
    bearish: { icon: TrendingDown, color: 'text-rose-400' },
    neutral: { icon: Minus, color: 'text-slate-400' },
};

const volatilityConfig: Record<VolatilityState, { label: string; color: string }> = {
    low: { label: 'Low', color: 'text-slate-400' },
    normal: { label: 'Normal', color: 'text-blue-400' },
    high: { label: 'High', color: 'text-amber-400' },
    extreme: { label: 'Extreme', color: 'text-rose-400' },
};

export const RegimeIndicator: React.FC<RegimeIndicatorProps> = ({
    regime,
    trend,
    volatility,
    trendStrength,
    volatilityPercentile,
    size = 'md',
    showLabels = true,
}) => {
    const sizeClasses = {
        sm: 'text-xs px-2 py-1',
        md: 'text-sm px-3 py-1.5',
        lg: 'text-base px-4 py-2',
    };

    const iconSizes = {
        sm: 'w-3 h-3',
        md: 'w-4 h-4',
        lg: 'w-5 h-5',
    };

    if (!regime) {
        return (
            <div className={`inline-flex items-center gap-1.5 rounded-lg bg-slate-700/50 ${sizeClasses[size]}`}>
                <Activity className={`${iconSizes[size]} text-slate-500`} />
                <span className="text-slate-500">No data</span>
            </div>
        );
    }

    const config = regimeConfig[regime];
    const TrendIcon = trend ? trendConfig[trend].icon : Minus;
    const trendColor = trend ? trendConfig[trend].color : 'text-slate-400';

    return (
        <div className="flex flex-col gap-2">
            {/* Regime Badge */}
            <div className={`inline-flex items-center gap-2 rounded-lg ${config.bg} ${sizeClasses[size]}`}>
                <TrendIcon className={`${iconSizes[size]} ${trendColor}`} />
                <span className={`font-medium ${config.color}`}>{config.label}</span>
            </div>

            {/* Additional Details */}
            {showLabels && (
                <div className="flex flex-wrap gap-2 text-xs">
                    {/* Trend Strength */}
                    {trendStrength !== null && trendStrength !== undefined && (
                        <div className="flex items-center gap-1 bg-slate-700/50 rounded px-2 py-0.5">
                            <span className="text-slate-500">Strength:</span>
                            <span className={trendColor}>{trendStrength.toFixed(0)}%</span>
                        </div>
                    )}

                    {/* Volatility */}
                    {volatility && (
                        <div className="flex items-center gap-1 bg-slate-700/50 rounded px-2 py-0.5">
                            <Zap className={`w-3 h-3 ${volatilityConfig[volatility].color}`} />
                            <span className={volatilityConfig[volatility].color}>
                                {volatilityConfig[volatility].label}
                            </span>
                            {volatilityPercentile !== null && volatilityPercentile !== undefined && (
                                <span className="text-slate-500">({volatilityPercentile.toFixed(0)}%)</span>
                            )}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

interface TrendBadgeProps {
    trend: MarketTrend | null;
    size?: 'sm' | 'md' | 'lg';
}

export const TrendBadge: React.FC<TrendBadgeProps> = ({ trend, size = 'md' }) => {
    if (!trend) return null;

    const config = trendConfig[trend];
    const Icon = config.icon;
    const iconSizes = { sm: 'w-3 h-3', md: 'w-4 h-4', lg: 'w-5 h-5' };

    return (
        <div className={`inline-flex items-center gap-1 ${config.color}`}>
            <Icon className={iconSizes[size]} />
            <span className="capitalize">{trend}</span>
        </div>
    );
};

interface VolatilityBadgeProps {
    volatility: VolatilityState | null;
    size?: 'sm' | 'md' | 'lg';
}

export const VolatilityBadge: React.FC<VolatilityBadgeProps> = ({ volatility, size = 'md' }) => {
    if (!volatility) return null;

    const config = volatilityConfig[volatility];

    return (
        <div className={`inline-flex items-center gap-1 ${config.color}`}>
            <Zap className={size === 'sm' ? 'w-3 h-3' : size === 'md' ? 'w-4 h-4' : 'w-5 h-5'} />
            <span>{config.label}</span>
        </div>
    );
};

export default RegimeIndicator;
