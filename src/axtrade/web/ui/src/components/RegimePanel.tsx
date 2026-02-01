import React from 'react';
import { useRegimeSummary } from '../hooks/useRegime';
import { RegimeIndicator, TrendBadge, VolatilityBadge } from './RegimeIndicator';
import { Activity, RefreshCw } from 'lucide-react';

interface RegimePanelProps {
    interval?: string;
    compact?: boolean;
}

export const RegimePanel: React.FC<RegimePanelProps> = ({ interval = '1m', compact = false }) => {
    const { summary, loading, error, refetch } = useRegimeSummary(interval);

    if (loading && summary.length === 0) {
        return (
            <div className="flex items-center justify-center py-8">
                <RefreshCw className="w-5 h-5 text-slate-500 animate-spin" />
            </div>
        );
    }

    if (error) {
        return (
            <div className="text-center py-8">
                <div className="text-rose-400 text-sm mb-2">Failed to load regime data</div>
                <button
                    onClick={refetch}
                    className="text-xs text-slate-400 hover:text-slate-200 underline"
                >
                    Retry
                </button>
            </div>
        );
    }

    if (summary.length === 0) {
        return (
            <div className="text-center py-8">
                <Activity className="w-8 h-8 text-slate-600 mx-auto mb-2" />
                <div className="text-slate-500 text-sm">No regime data available</div>
                <div className="text-slate-600 text-xs mt-1">Start the aggregator to generate bars</div>
            </div>
        );
    }

    if (compact) {
        return (
            <div className="space-y-2">
                {summary.map((item) => (
                    <div
                        key={item.symbol}
                        className="flex items-center justify-between p-2 bg-slate-700/30 rounded-lg"
                    >
                        <div className="flex items-center gap-3">
                            <span className="font-medium text-sm">{item.symbol}</span>
                            {item.last_price && (
                                <span className="text-slate-400 text-xs">
                                    ${item.last_price.toFixed(2)}
                                </span>
                            )}
                        </div>
                        <div className="flex items-center gap-2">
                            <TrendBadge trend={item.trend} size="sm" />
                            <VolatilityBadge volatility={item.volatility} size="sm" />
                        </div>
                    </div>
                ))}
            </div>
        );
    }

    return (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {summary.map((item) => (
                <div
                    key={item.symbol}
                    className="bg-slate-700/30 rounded-xl border border-slate-600/50 p-4 hover:border-slate-500/50 transition-colors"
                >
                    <div className="flex items-center justify-between mb-3">
                        <span className="font-semibold text-lg">{item.symbol}</span>
                        {item.last_price && (
                            <span className="text-slate-300 font-mono">
                                ${item.last_price.toFixed(2)}
                            </span>
                        )}
                    </div>

                    <RegimeIndicator
                        regime={item.regime}
                        trend={item.trend}
                        volatility={item.volatility}
                        size="md"
                        showLabels={false}
                    />

                    <div className="mt-3 flex items-center gap-3 text-xs">
                        <TrendBadge trend={item.trend} size="sm" />
                        <VolatilityBadge volatility={item.volatility} size="sm" />
                    </div>

                    {item.timestamp && (
                        <div className="mt-2 text-xs text-slate-500">
                            {new Date(item.timestamp).toLocaleTimeString()}
                        </div>
                    )}
                </div>
            ))}
        </div>
    );
};

export default RegimePanel;
