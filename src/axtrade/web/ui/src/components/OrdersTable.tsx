import React from 'react';
import { useOrders } from '../hooks/useApi';
import type { OrderResponse } from '../types/api';

const OrdersTable: React.FC = () => {
    const { orders, loading, error } = useOrders(20);

    if (loading && orders.length === 0) {
        return (
            <div className="text-slate-500 text-sm">Loading orders...</div>
        );
    }

    if (error) {
        return (
            <div className="text-rose-400 text-sm">Error: {error}</div>
        );
    }

    if (orders.length === 0) {
        return (
            <div className="text-slate-500 text-sm">No recent orders</div>
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
                        <th className="pb-2 font-medium">Type</th>
                        <th className="pb-2 font-medium text-right">Qty</th>
                        <th className="pb-2 font-medium text-right">Price</th>
                        <th className="pb-2 font-medium">Status</th>
                    </tr>
                </thead>
                <tbody>
                    {orders.map((order) => (
                        <OrderRow key={order.id} order={order} />
                    ))}
                </tbody>
            </table>
        </div>
    );
};

const OrderRow: React.FC<{ order: OrderResponse }> = ({ order }) => {
    const time = new Date(order.created_at).toLocaleTimeString();
    const price = order.avg_fill_price || order.limit_price || '-';
    const isBuy = order.side.toLowerCase() === 'buy';

    return (
        <tr className="border-b border-slate-700/50 hover:bg-slate-700/30">
            <td className="py-2 text-slate-400">{time}</td>
            <td className="py-2 font-medium">{order.symbol}</td>
            <td className={`py-2 font-medium ${isBuy ? 'text-emerald-400' : 'text-rose-400'}`}>
                {order.side.toUpperCase()}
            </td>
            <td className="py-2 text-slate-300">{order.order_type}</td>
            <td className="py-2 text-right">{order.quantity}</td>
            <td className="py-2 text-right">{price}</td>
            <td className="py-2">
                <StatusBadge status={order.status} />
            </td>
        </tr>
    );
};

const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
    const statusLower = status.toLowerCase();
    let colorClass = 'bg-slate-600 text-slate-300';

    if (statusLower === 'filled') {
        colorClass = 'bg-emerald-900/50 text-emerald-400';
    } else if (statusLower === 'pending' || statusLower === 'submitted') {
        colorClass = 'bg-yellow-900/50 text-yellow-400';
    } else if (statusLower === 'cancelled' || statusLower === 'canceled') {
        colorClass = 'bg-slate-700 text-slate-400';
    } else if (statusLower === 'rejected') {
        colorClass = 'bg-rose-900/50 text-rose-400';
    } else if (statusLower === 'partial') {
        colorClass = 'bg-blue-900/50 text-blue-400';
    }

    return (
        <span className={`px-2 py-0.5 rounded text-xs font-medium ${colorClass}`}>
            {status}
        </span>
    );
};

export default OrdersTable;
