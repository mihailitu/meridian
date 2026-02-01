import { ChevronDown } from 'lucide-react';
import type { MarketId } from '../types/market';
import { MARKET_LABELS, MARKET_COLORS } from '../types/market';

interface MarketSelectorProps {
    value: MarketId | 'all';
    onChange: (market: MarketId | 'all') => void;
    showAllOption?: boolean;
}

const MARKETS: MarketId[] = ['us', 'eu', 'asia', 'crypto', 'forex'];

const MarketSelector: React.FC<MarketSelectorProps> = ({
    value,
    onChange,
    showAllOption = true,
}) => {
    return (
        <div className="relative">
            <select
                value={value}
                onChange={(e) => onChange(e.target.value as MarketId | 'all')}
                className="appearance-none bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 pr-8 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500 cursor-pointer"
            >
                {showAllOption && (
                    <option value="all">All Markets</option>
                )}
                {MARKETS.map((market) => (
                    <option key={market} value={market}>
                        {MARKET_LABELS[market]}
                    </option>
                ))}
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" />
        </div>
    );
};

interface MarketChipsProps {
    value: MarketId | 'all';
    onChange: (market: MarketId | 'all') => void;
    showAllOption?: boolean;
}

export const MarketChips: React.FC<MarketChipsProps> = ({
    value,
    onChange,
    showAllOption = true,
}) => {
    return (
        <div className="flex gap-2">
            {showAllOption && (
                <button
                    onClick={() => onChange('all')}
                    className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-colors ${
                        value === 'all'
                            ? 'bg-blue-600 text-white'
                            : 'bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-700'
                    }`}
                >
                    All
                </button>
            )}
            {MARKETS.map((market) => (
                <button
                    key={market}
                    onClick={() => onChange(market)}
                    className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-colors ${
                        value === market
                            ? `bg-slate-700 ${MARKET_COLORS[market]}`
                            : 'bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-700'
                    }`}
                >
                    {MARKET_LABELS[market]}
                </button>
            ))}
        </div>
    );
};

export default MarketSelector;
