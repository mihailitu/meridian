import { useState } from 'react';
import {
    Search,
    RefreshCw,
    TrendingUp,
    TrendingDown,
    AlertCircle,
    Clock,
    Filter,
    Trash2,
    Activity,
} from 'lucide-react';
import {
    useDiscoveryState,
    useDiscoveredSymbols,
    useScreeners,
    useScan,
    useClearDiscovered,
} from '../hooks/useDiscovery';
import type { DiscoveredSymbol } from '../types/discovery';
import { getSignalDirection } from '../types/discovery';

const Discovery = () => {
    const { state } = useDiscoveryState();
    const { screeners } = useScreeners();
    const { runScan, loading: scanLoading } = useScan();
    const { clearDiscovered, loading: clearLoading } = useClearDiscovered();

    // Filter state
    const [filter, setFilter] = useState<'all' | 'bullish' | 'bearish'>('all');
    const [selectedSource, setSelectedSource] = useState<string>('');

    const {
        symbols,
        loading: symbolsLoading,
        error: symbolsError,
        refetch: refetchSymbols,
    } = useDiscoveredSymbols({
        bullishOnly: filter === 'bullish',
        bearishOnly: filter === 'bearish',
        source: selectedSource || undefined,
        limit: 50,
    });

    const handleRunScan = async () => {
        await runScan();
        refetchSymbols();
    };

    const handleClear = async () => {
        await clearDiscovered();
        refetchSymbols();
    };

    const formatTime = (isoString: string | null) => {
        if (!isoString) return 'Never';
        const date = new Date(isoString);
        return date.toLocaleTimeString();
    };

    return (
        <div className="space-y-6">
            {/* Header with State */}
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-2xl font-bold text-slate-100">Symbol Discovery</h2>
                    <p className="text-slate-400 text-sm mt-1">
                        Scan markets for trading opportunities using technical screeners
                    </p>
                </div>

                <div className="flex items-center gap-4">
                    {/* Discovery State */}
                    <div className="flex items-center gap-4 bg-slate-800 rounded-lg px-4 py-2 border border-slate-700">
                        <div className="flex items-center gap-2">
                            <Activity className="w-4 h-4 text-slate-400" />
                            <span className="text-sm text-slate-400">Screeners:</span>
                            <span className="text-sm font-medium text-slate-200">
                                {state?.active_screeners.length ?? 0}
                            </span>
                        </div>
                        <div className="w-px h-4 bg-slate-700" />
                        <div className="flex items-center gap-2">
                            <Search className="w-4 h-4 text-slate-400" />
                            <span className="text-sm text-slate-400">Discovered:</span>
                            <span className="text-sm font-medium text-slate-200">
                                {state?.total_discovered ?? 0}
                            </span>
                        </div>
                        <div className="w-px h-4 bg-slate-700" />
                        <div className="flex items-center gap-2">
                            <Clock className="w-4 h-4 text-slate-400" />
                            <span className="text-sm text-slate-400">Last Scan:</span>
                            <span className="text-sm font-medium text-slate-200">
                                {formatTime(state?.last_scan ?? null)}
                            </span>
                        </div>
                    </div>

                    {/* Actions */}
                    <button
                        onClick={handleRunScan}
                        disabled={scanLoading || state?.is_scanning}
                        className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-700 disabled:text-slate-500 text-white rounded-lg transition-colors font-medium"
                    >
                        <RefreshCw className={`w-4 h-4 ${scanLoading ? 'animate-spin' : ''}`} />
                        {scanLoading ? 'Scanning...' : 'Run Scan'}
                    </button>
                </div>
            </div>

            {/* Filters and Screeners */}
            <div className="flex items-center justify-between bg-slate-800 rounded-lg p-4 border border-slate-700">
                <div className="flex items-center gap-4">
                    <div className="flex items-center gap-2">
                        <Filter className="w-4 h-4 text-slate-400" />
                        <span className="text-sm text-slate-400">Signal:</span>
                    </div>
                    <div className="flex gap-2">
                        <FilterButton
                            active={filter === 'all'}
                            onClick={() => setFilter('all')}
                        >
                            All
                        </FilterButton>
                        <FilterButton
                            active={filter === 'bullish'}
                            onClick={() => setFilter('bullish')}
                            variant="bullish"
                        >
                            <TrendingUp className="w-3 h-3" />
                            Bullish
                        </FilterButton>
                        <FilterButton
                            active={filter === 'bearish'}
                            onClick={() => setFilter('bearish')}
                            variant="bearish"
                        >
                            <TrendingDown className="w-3 h-3" />
                            Bearish
                        </FilterButton>
                    </div>

                    <div className="w-px h-6 bg-slate-700" />

                    <div className="flex items-center gap-2">
                        <span className="text-sm text-slate-400">Source:</span>
                        <select
                            value={selectedSource}
                            onChange={(e) => setSelectedSource(e.target.value)}
                            className="bg-slate-900 border border-slate-700 rounded px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
                        >
                            <option value="">All Screeners</option>
                            {screeners.map((s) => (
                                <option key={s.name} value={s.name}>
                                    {s.name} ({s.type})
                                </option>
                            ))}
                        </select>
                    </div>
                </div>

                <button
                    onClick={handleClear}
                    disabled={clearLoading || symbols.length === 0}
                    className="flex items-center gap-2 px-3 py-1.5 text-sm text-red-400 hover:text-red-300 hover:bg-red-900/20 disabled:text-slate-600 disabled:hover:bg-transparent rounded transition-colors"
                >
                    <Trash2 className="w-4 h-4" />
                    Clear All
                </button>
            </div>

            {/* Discovered Symbols Table */}
            <div className="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
                {symbolsError ? (
                    <div className="p-8 text-center">
                        <AlertCircle className="w-8 h-8 text-red-400 mx-auto mb-2" />
                        <p className="text-red-400">{symbolsError}</p>
                    </div>
                ) : symbolsLoading && symbols.length === 0 ? (
                    <div className="p-8 text-center">
                        <RefreshCw className="w-8 h-8 text-slate-500 mx-auto mb-2 animate-spin" />
                        <p className="text-slate-400">Loading discoveries...</p>
                    </div>
                ) : symbols.length === 0 ? (
                    <div className="p-8 text-center">
                        <Search className="w-8 h-8 text-slate-500 mx-auto mb-2" />
                        <p className="text-slate-400">No discoveries yet</p>
                        <p className="text-slate-500 text-sm mt-1">
                            Run a scan to discover trading opportunities
                        </p>
                    </div>
                ) : (
                    <table className="w-full">
                        <thead>
                            <tr className="border-b border-slate-700 bg-slate-900/50">
                                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                                    Symbol
                                </th>
                                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                                    Signal
                                </th>
                                <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                                    Score
                                </th>
                                <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                                    Price
                                </th>
                                <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                                    Change
                                </th>
                                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                                    Source
                                </th>
                                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                                    Discovered
                                </th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-700/50">
                            {symbols.map((symbol, idx) => (
                                <SymbolRow key={`${symbol.symbol}-${symbol.source}-${idx}`} symbol={symbol} />
                            ))}
                        </tbody>
                    </table>
                )}
            </div>

            {/* Active Screeners */}
            <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
                <h3 className="text-sm font-semibold text-slate-300 mb-3">Active Screeners</h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {screeners.map((screener) => (
                        <ScreenerCard key={screener.name} screener={screener} />
                    ))}
                    {screeners.length === 0 && (
                        <p className="text-slate-500 text-sm col-span-4">No screeners configured</p>
                    )}
                </div>
            </div>
        </div>
    );
};

interface FilterButtonProps {
    active: boolean;
    onClick: () => void;
    variant?: 'default' | 'bullish' | 'bearish';
    children: React.ReactNode;
}

const FilterButton: React.FC<FilterButtonProps> = ({
    active,
    onClick,
    variant = 'default',
    children,
}) => {
    const baseStyles = 'flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded transition-colors';

    const variantStyles = {
        default: active
            ? 'bg-slate-700 text-slate-100'
            : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/50',
        bullish: active
            ? 'bg-emerald-900/50 text-emerald-400 border border-emerald-700'
            : 'text-slate-400 hover:text-emerald-400 hover:bg-emerald-900/20',
        bearish: active
            ? 'bg-red-900/50 text-red-400 border border-red-700'
            : 'text-slate-400 hover:text-red-400 hover:bg-red-900/20',
    };

    return (
        <button
            onClick={onClick}
            className={`${baseStyles} ${variantStyles[variant]}`}
        >
            {children}
        </button>
    );
};

interface SymbolRowProps {
    symbol: DiscoveredSymbol;
}

const SymbolRow: React.FC<SymbolRowProps> = ({ symbol }) => {
    const direction = getSignalDirection(symbol.score);

    const signalStyles = {
        bullish: 'bg-emerald-900/30 text-emerald-400',
        bearish: 'bg-red-900/30 text-red-400',
        neutral: 'bg-slate-700/30 text-slate-400',
    };

    const signalIcons = {
        bullish: <TrendingUp className="w-3 h-3" />,
        bearish: <TrendingDown className="w-3 h-3" />,
        neutral: null,
    };

    const formatPrice = (price: number | null) => {
        if (price === null) return '-';
        return `$${price.toFixed(2)}`;
    };

    const formatChange = (change: number | null) => {
        if (change === null) return '-';
        const prefix = change >= 0 ? '+' : '';
        return `${prefix}${change.toFixed(2)}%`;
    };

    const formatTime = (isoString: string) => {
        const date = new Date(isoString);
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    };

    return (
        <tr className="hover:bg-slate-700/30 transition-colors">
            <td className="px-4 py-3">
                <span className="font-mono font-semibold text-slate-100">{symbol.symbol}</span>
            </td>
            <td className="px-4 py-3">
                <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium ${signalStyles[direction]}`}>
                    {signalIcons[direction]}
                    <span className="capitalize">{direction}</span>
                </span>
            </td>
            <td className="px-4 py-3 text-right">
                <span className={`font-mono font-medium ${direction === 'bullish' ? 'text-emerald-400' : direction === 'bearish' ? 'text-red-400' : 'text-slate-400'}`}>
                    {Math.abs(symbol.score).toFixed(1)}
                </span>
            </td>
            <td className="px-4 py-3 text-right">
                <span className="font-mono text-slate-200">{formatPrice(symbol.price)}</span>
            </td>
            <td className="px-4 py-3 text-right">
                <span className={`font-mono ${symbol.change_pct && symbol.change_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {formatChange(symbol.change_pct)}
                </span>
            </td>
            <td className="px-4 py-3">
                <span className="text-sm text-slate-400">{symbol.source}</span>
            </td>
            <td className="px-4 py-3">
                <span className="text-sm text-slate-500">{formatTime(symbol.discovered_at)}</span>
            </td>
        </tr>
    );
};

interface ScreenerCardProps {
    screener: { name: string; type: string; params: Record<string, unknown> };
}

const ScreenerCard: React.FC<ScreenerCardProps> = ({ screener }) => {
    const typeColors: Record<string, string> = {
        momentum: 'text-purple-400',
        volatility: 'text-orange-400',
        volume: 'text-blue-400',
        trend: 'text-emerald-400',
        breakout: 'text-yellow-400',
    };

    return (
        <div className="bg-slate-900/50 rounded-lg p-3 border border-slate-700/50">
            <div className="flex items-center justify-between mb-2">
                <span className="font-medium text-slate-200 text-sm">{screener.name}</span>
                <span className={`text-xs font-medium ${typeColors[screener.type] || 'text-slate-400'}`}>
                    {screener.type}
                </span>
            </div>
            <div className="text-xs text-slate-500">
                {Object.entries(screener.params).slice(0, 3).map(([key, value]) => (
                    <div key={key} className="flex justify-between">
                        <span>{key.replace(/_/g, ' ')}:</span>
                        <span className="text-slate-400">{String(value)}</span>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default Discovery;
