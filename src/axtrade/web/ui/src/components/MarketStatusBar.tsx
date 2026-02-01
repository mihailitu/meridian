import { useAllMarkets } from '../hooks/useMarkets';
import type { MarketStatus, MarketId } from '../types/market';
import { MARKET_LABELS, MARKET_COLORS } from '../types/market';
import { Clock, Sun, Moon } from 'lucide-react';

interface MarketStatusBarProps {
    compact?: boolean;
}

const MarketStatusBar: React.FC<MarketStatusBarProps> = ({ compact = false }) => {
    const { markets, loading } = useAllMarkets(30000);

    if (loading && markets.length === 0) {
        return (
            <div className="flex items-center gap-2 text-slate-500 text-sm">
                <Clock className="w-4 h-4 animate-pulse" />
                <span>Loading markets...</span>
            </div>
        );
    }

    return (
        <div className="flex items-center gap-3">
            {markets.map((market) => (
                <MarketStatusIndicator
                    key={market.market}
                    market={market}
                    compact={compact}
                />
            ))}
        </div>
    );
};

interface MarketStatusIndicatorProps {
    market: MarketStatus;
    compact?: boolean;
}

const MarketStatusIndicator: React.FC<MarketStatusIndicatorProps> = ({
    market,
    compact = false,
}) => {
    const marketId = market.market as MarketId;
    const label = MARKET_LABELS[marketId] || market.market.toUpperCase();
    const colorClass = MARKET_COLORS[marketId] || 'text-slate-400';

    const getStatusDot = () => {
        if (market.is_open) {
            return 'bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.6)]';
        }
        if (market.is_extended_hours) {
            return 'bg-yellow-500 shadow-[0_0_6px_rgba(234,179,8,0.6)]';
        }
        return 'bg-slate-500';
    };

    const getStatusIcon = () => {
        if (market.is_open) {
            return <Sun className="w-3 h-3 text-emerald-400" />;
        }
        return <Moon className="w-3 h-3 text-slate-500" />;
    };

    if (compact) {
        return (
            <div
                className="flex items-center gap-1.5 px-2 py-1 bg-slate-800 rounded border border-slate-700"
                title={`${label}: ${market.is_open ? 'Open' : market.is_extended_hours ? 'Extended Hours' : 'Closed'}`}
            >
                <div className={`w-2 h-2 rounded-full ${getStatusDot()}`} />
                <span className={`text-xs font-medium ${colorClass}`}>{label}</span>
            </div>
        );
    }

    return (
        <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-800 rounded-lg border border-slate-700">
            <div className="flex items-center gap-1.5">
                <div className={`w-2 h-2 rounded-full ${getStatusDot()}`} />
                <span className={`text-sm font-medium ${colorClass}`}>{label}</span>
            </div>
            <div className="flex items-center gap-1 text-xs text-slate-400">
                {getStatusIcon()}
                {market.is_open ? (
                    <span>
                        Closes in{' '}
                        <span className="text-slate-300">{formatTimeRemaining(market.time_until_close)}</span>
                    </span>
                ) : market.time_until_open ? (
                    <span>
                        Opens in{' '}
                        <span className="text-slate-300">{formatTimeRemaining(market.time_until_open)}</span>
                    </span>
                ) : (
                    <span>Closed</span>
                )}
            </div>
        </div>
    );
};

function formatTimeRemaining(timeStr: string | null): string {
    if (!timeStr) return '--:--';
    // timeStr is in HH:MM:SS format
    const [hours, minutes] = timeStr.split(':').map(Number);
    if (hours > 0) {
        return `${hours}h ${minutes}m`;
    }
    return `${minutes}m`;
}

export default MarketStatusBar;
