import React from 'react';
import { useFills } from '../hooks/useApi';
import type { FillResponse } from '../types/api';

const FillsTable: React.FC = () => {
    const { fills, loading, error } = useFills(20);

    if (loading && fills.length === 0) {
        return (
            <div className="text-slate-500 text-sm">Loading fills...</div>
        );
    }

    if (error) {
        return (
            <div className="text-rose-400 text-sm">Error: {error}</div>
        );
    }

    if (fills.length === 0) {
        return (
            <div className="text-slate-500 text-sm">No recent fills</div>
        );
    }

    return (
        <div className="overflow-x-auto">
            <table className="w-full text-sm">
                <thead>
                    <tr className="text-slate-400 text-left border-b border-slate-700">
                        <th className="pb-2 font-medium">Time</th>
                        <th className="pb-2 font-medium">Symbol</th>
                        <th className="pb-2 font-medium">Side</th>
                        <th className="pb-2 font-medium text-right">Qty</th>
                        <th className="pb-2 font-medium text-right">Price</th>
                        <th className="pb-2 font-medium text-right">Comm</th>
                        <th className="pb-2 font-medium">Strategy</th>
                    </tr>
                </thead>
                <tbody>
                    {fills.map((fill) => (
                        <FillRow key={fill.id} fill={fill} />
                    ))}
                </tbody>
            </table>
        </div>
    );
};

const FillRow: React.FC<{ fill: FillResponse }> = ({ fill }) => {
    const time = new Date(fill.filled_at).toLocaleTimeString();
    const isBuy = fill.side.toLowerCase() === 'buy';
    const commission = parseFloat(fill.commission).toFixed(2);
    const price = parseFloat(fill.price).toFixed(2);

    return (
        <tr className="border-b border-slate-700/50 hover:bg-slate-700/30">
            <td className="py-2 text-slate-400">{time}</td>
            <td className="py-2 font-medium">{fill.symbol}</td>
            <td className={`py-2 font-medium ${isBuy ? 'text-emerald-400' : 'text-rose-400'}`}>
                {fill.side.toUpperCase()}
            </td>
            <td className="py-2 text-right">{fill.quantity}</td>
            <td className="py-2 text-right">${price}</td>
            <td className="py-2 text-right text-slate-400">${commission}</td>
            <td className="py-2 text-slate-300 truncate max-w-[100px]" title={fill.strategy_id}>
                {formatStrategyId(fill.strategy_id)}
            </td>
        </tr>
    );
};

function formatStrategyId(id: string): string {
    // Shorten strategy ID for display
    if (id.length > 12) {
        return id.substring(0, 10) + '...';
    }
    return id;
}

export default FillsTable;
