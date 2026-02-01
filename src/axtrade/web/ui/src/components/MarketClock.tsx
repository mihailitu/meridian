import { useState, useEffect } from 'react';
import { Clock, Sun, Moon, AlertCircle } from 'lucide-react';
import { useMarketStatus } from '../hooks/useMarkets';
import type { MarketId } from '../types/market';
import { MARKET_LABELS, MARKET_COLORS } from '../types/market';

interface MarketClockProps {
    market: MarketId;
    showCountdown?: boolean;
}

const MarketClock: React.FC<MarketClockProps> = ({ market, showCountdown = true }) => {
    const { status, loading, error } = useMarketStatus(market, 30000);
    const [countdown, setCountdown] = useState<string>('');

    useEffect(() => {
        if (!status || !showCountdown) return;

        const updateCountdown = () => {
            const timeStr = status.is_open ? status.time_until_close : status.time_until_open;
            if (timeStr) {
                setCountdown(formatCountdown(timeStr));
            } else {
                setCountdown('--:--:--');
            }
        };

        updateCountdown();
        const interval = setInterval(updateCountdown, 1000);
        return () => clearInterval(interval);
    }, [status, showCountdown]);

    if (loading) {
        return (
            <div className="bg-slate-800 rounded-lg p-4 border border-slate-700 animate-pulse">
                <div className="h-6 w-24 bg-slate-700 rounded mb-2" />
                <div className="h-8 w-32 bg-slate-700 rounded" />
            </div>
        );
    }

    if (error || !status) {
        return (
            <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
                <div className="flex items-center gap-2 text-red-400">
                    <AlertCircle className="w-4 h-4" />
                    <span className="text-sm">Failed to load</span>
                </div>
            </div>
        );
    }

    const colorClass = MARKET_COLORS[market] || 'text-slate-400';
    const label = MARKET_LABELS[market] || market.toUpperCase();

    return (
        <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="flex items-center justify-between mb-2">
                <span className={`text-lg font-bold ${colorClass}`}>{label}</span>
                {status.is_open ? (
                    <div className="flex items-center gap-1.5 text-emerald-400">
                        <Sun className="w-4 h-4" />
                        <span className="text-sm font-medium">Open</span>
                    </div>
                ) : status.is_extended_hours ? (
                    <div className="flex items-center gap-1.5 text-yellow-400">
                        <Clock className="w-4 h-4" />
                        <span className="text-sm font-medium">Extended</span>
                    </div>
                ) : (
                    <div className="flex items-center gap-1.5 text-slate-500">
                        <Moon className="w-4 h-4" />
                        <span className="text-sm font-medium">Closed</span>
                    </div>
                )}
            </div>

            <div className="flex items-baseline gap-2">
                <span className="text-2xl font-mono font-bold text-slate-100">
                    {status.local_time.slice(0, 5)}
                </span>
                <span className="text-sm text-slate-500">{status.timezone}</span>
            </div>

            {showCountdown && (
                <div className="mt-3 pt-3 border-t border-slate-700">
                    <div className="flex items-center justify-between text-sm">
                        <span className="text-slate-400">
                            {status.is_open ? 'Closes in' : 'Opens in'}
                        </span>
                        <span className="font-mono text-slate-200">{countdown}</span>
                    </div>
                    <div className="mt-2 text-xs text-slate-500">
                        Hours: {status.open_time} - {status.close_time}
                    </div>
                </div>
            )}
        </div>
    );
};

function formatCountdown(timeStr: string): string {
    // timeStr is in HH:MM:SS format
    return timeStr;
}

interface MarketClocksGridProps {
    markets?: MarketId[];
}

export const MarketClocksGrid: React.FC<MarketClocksGridProps> = ({
    markets = ['us', 'eu', 'asia', 'crypto'],
}) => {
    return (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {markets.map((market) => (
                <MarketClock key={market} market={market} />
            ))}
        </div>
    );
};

export default MarketClock;
