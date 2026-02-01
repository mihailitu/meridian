import React, { useMemo } from 'react';
import { useRegimeHistory } from '../hooks/useRegime';
import type { MarketRegime } from '../types/regime';
import { RefreshCw, Activity } from 'lucide-react';

interface RegimeChartProps {
    symbol: string;
    interval?: string;
    hours?: number;
    height?: number;
}

const regimeColors: Record<MarketRegime, string> = {
    trending_up: '#10b981',
    trending_down: '#f43f5e',
    ranging_quiet: '#64748b',
    ranging_volatile: '#f59e0b',
    breakout: '#06b6d4',
    breakdown: '#a855f7',
};

const regimeLabels: Record<MarketRegime, string> = {
    trending_up: 'Up',
    trending_down: 'Down',
    ranging_quiet: 'Quiet',
    ranging_volatile: 'Volatile',
    breakout: 'Breakout',
    breakdown: 'Breakdown',
};

export const RegimeChart: React.FC<RegimeChartProps> = ({
    symbol,
    interval = '1m',
    hours = 24,
    height = 120,
}) => {
    const { history, loading, error, refetch } = useRegimeHistory(symbol, interval, hours);

    const chartData = useMemo(() => {
        if (!history?.history?.length) return null;

        const points = history.history;
        const segments: { regime: MarketRegime; startIdx: number; endIdx: number }[] = [];

        let currentRegime = points[0].regime;
        let startIdx = 0;

        for (let i = 1; i < points.length; i++) {
            if (points[i].regime !== currentRegime) {
                segments.push({ regime: currentRegime, startIdx, endIdx: i - 1 });
                currentRegime = points[i].regime;
                startIdx = i;
            }
        }
        segments.push({ regime: currentRegime, startIdx, endIdx: points.length - 1 });

        return { points, segments, totalPoints: points.length };
    }, [history]);

    if (loading && !history) {
        return (
            <div className="flex items-center justify-center" style={{ height }}>
                <RefreshCw className="w-5 h-5 text-slate-500 animate-spin" />
            </div>
        );
    }

    if (error) {
        return (
            <div className="flex flex-col items-center justify-center" style={{ height }}>
                <div className="text-rose-400 text-sm mb-2">Failed to load</div>
                <button
                    onClick={refetch}
                    className="text-xs text-slate-400 hover:text-slate-200 underline"
                >
                    Retry
                </button>
            </div>
        );
    }

    if (!chartData) {
        return (
            <div className="flex flex-col items-center justify-center text-slate-500" style={{ height }}>
                <Activity className="w-6 h-6 mb-2" />
                <span className="text-sm">No history</span>
            </div>
        );
    }

    const { points, segments, totalPoints } = chartData;

    return (
        <div className="relative" style={{ height }}>
            {/* Regime bars */}
            <svg width="100%" height={height - 24} className="overflow-visible">
                {segments.map((segment, idx) => {
                    const x = (segment.startIdx / totalPoints) * 100;
                    const width = ((segment.endIdx - segment.startIdx + 1) / totalPoints) * 100;
                    return (
                        <rect
                            key={idx}
                            x={`${x}%`}
                            y={0}
                            width={`${width}%`}
                            height="100%"
                            fill={regimeColors[segment.regime]}
                            opacity={0.7}
                        />
                    );
                })}

                {/* Trend strength line overlay */}
                <path
                    d={points
                        .map((p, i) => {
                            const x = (i / (totalPoints - 1)) * 100;
                            const y = 100 - p.trend_strength;
                            return `${i === 0 ? 'M' : 'L'} ${x}% ${y}%`;
                        })
                        .join(' ')}
                    fill="none"
                    stroke="rgba(255,255,255,0.5)"
                    strokeWidth={1.5}
                />
            </svg>

            {/* Legend */}
            <div className="flex items-center justify-center gap-3 mt-2 flex-wrap">
                {Object.entries(regimeColors).map(([regime, color]) => (
                    <div key={regime} className="flex items-center gap-1 text-xs">
                        <div
                            className="w-3 h-3 rounded"
                            style={{ backgroundColor: color, opacity: 0.7 }}
                        />
                        <span className="text-slate-400">{regimeLabels[regime as MarketRegime]}</span>
                    </div>
                ))}
            </div>
        </div>
    );
};

interface RegimeTimelineProps {
    symbol: string;
    interval?: string;
    hours?: number;
}

export const RegimeTimeline: React.FC<RegimeTimelineProps> = ({
    symbol,
    interval = '1m',
    hours = 6,
}) => {
    const { history, loading } = useRegimeHistory(symbol, interval, hours);

    if (loading || !history?.history?.length) {
        return null;
    }

    // Group consecutive same-regime periods
    const periods: { regime: MarketRegime; start: string; end: string; count: number }[] = [];
    let current = history.history[0];
    let startTime = current.timestamp;
    let count = 1;

    for (let i = 1; i < history.history.length; i++) {
        if (history.history[i].regime === current.regime) {
            count++;
        } else {
            periods.push({
                regime: current.regime,
                start: startTime,
                end: current.timestamp,
                count,
            });
            current = history.history[i];
            startTime = current.timestamp;
            count = 1;
        }
    }
    periods.push({
        regime: current.regime,
        start: startTime,
        end: current.timestamp,
        count,
    });

    return (
        <div className="space-y-1">
            {periods.slice(-5).map((period, idx) => (
                <div
                    key={idx}
                    className="flex items-center gap-2 text-xs"
                >
                    <div
                        className="w-2 h-2 rounded-full"
                        style={{ backgroundColor: regimeColors[period.regime] }}
                    />
                    <span className="text-slate-400 w-16">
                        {new Date(period.start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                    <span className="text-slate-300">{regimeLabels[period.regime]}</span>
                    <span className="text-slate-500">({period.count} bars)</span>
                </div>
            ))}
        </div>
    );
};

export default RegimeChart;
