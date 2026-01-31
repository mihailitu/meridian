import React from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import { TrendingUp, TrendingDown, Pause } from 'lucide-react';

interface StrategyCardProps {
    name: string;
    status: 'active' | 'paused' | 'stopped';
    pnl: number;
    trades: number;
}

const Strategies: React.FC = () => {
    const { status } = useWebSocket();

    if (status !== 'connected') {
        return (
            <div className="flex items-center justify-center h-64">
                <div className="text-center">
                    <div className="text-slate-500 text-lg mb-2">Waiting for connection...</div>
                    <div className="text-slate-600 text-sm">Start the backend with: make run-api</div>
                </div>
            </div>
        );
    }

    // Placeholder strategies - will be populated from API
    const strategies: StrategyCardProps[] = [
        { name: 'Momentum', status: 'active', pnl: 0, trades: 0 },
        { name: 'MeanReversion', status: 'active', pnl: 0, trades: 0 },
        { name: 'MultiTimeframe', status: 'active', pnl: 0, trades: 0 },
        { name: 'Pairs (AAPL/MSFT)', status: 'active', pnl: 0, trades: 0 },
    ];

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center">
                <h2 className="text-xl font-semibold">Strategy Management</h2>
            </div>

            <div className="grid gap-4">
                {strategies.map((strategy) => (
                    <StrategyCard key={strategy.name} {...strategy} />
                ))}
            </div>
        </div>
    );
};

const StrategyCard: React.FC<StrategyCardProps> = ({ name, status, pnl, trades }) => {
    const isPositive = pnl >= 0;
    const formatted = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(pnl);

    const statusConfig = {
        active: { icon: TrendingUp, color: 'text-emerald-400', bg: 'bg-emerald-900/30' },
        paused: { icon: Pause, color: 'text-yellow-400', bg: 'bg-yellow-900/30' },
        stopped: { icon: TrendingDown, color: 'text-red-400', bg: 'bg-red-900/30' },
    };

    const { icon: StatusIcon, color, bg } = statusConfig[status];

    return (
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-5 hover:border-slate-600 transition-colors">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                    <div className={`p-2 rounded-lg ${bg}`}>
                        <StatusIcon className={`w-5 h-5 ${color}`} />
                    </div>
                    <div>
                        <h3 className="font-semibold text-lg">{name}</h3>
                        <p className="text-slate-400 text-sm capitalize">{status}</p>
                    </div>
                </div>

                <div className="text-right">
                    <p className={`text-xl font-bold ${isPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {formatted}
                    </p>
                    <p className="text-slate-400 text-sm">{trades} trades</p>
                </div>
            </div>
        </div>
    );
};

export default Strategies;
