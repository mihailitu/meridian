import React from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import type { DashboardData } from '../types/websocket';
import PnLChart from './PnLChart';
import AlertsPanel from './AlertsPanel';
import RegimePanel from './RegimePanel';

const Overview: React.FC = () => {
    const { status, lastMessage } = useWebSocket();

    // Parse dashboard data from WebSocket message
    const dashboardData = lastMessage?.type === 'dashboard'
        ? lastMessage.data as DashboardData
        : null;

    const pnl = dashboardData?.pnl;

    return (
        <div className="space-y-6">
            {/* PnL Cards */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <PnLCard title="Daily Total" value={pnl?.daily_total} />
                <PnLCard title="Realized" value={pnl?.daily_realized} />
                <PnLCard title="Unrealized" value={pnl?.daily_unrealized} />
                <PnLCard title="Cumulative" value={pnl?.cumulative_realized} />
            </div>

            {/* P&L Chart */}
            <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
                <h2 className="text-lg font-semibold mb-4">P&L Performance (24h)</h2>
                <PnLChart hours={24} />
            </div>

            {/* Main Dashboard Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2 bg-slate-800 rounded-xl border border-slate-700 p-6">
                    <h2 className="text-lg font-semibold mb-4">Open Positions</h2>
                    {status !== 'connected' ? (
                        <div className="text-center py-8">
                            <div className="text-slate-500 mb-2">Waiting for connection...</div>
                            <div className="text-slate-600 text-sm">Start the backend with: make run-api</div>
                        </div>
                    ) : dashboardData?.positions && dashboardData.positions.length > 0 ? (
                        <div className="space-y-2">
                            {dashboardData.positions.map((pos, i) => (
                                <div key={i} className="flex justify-between items-center p-3 bg-slate-700/50 rounded-lg">
                                    <div>
                                        <span className="font-medium">{pos.symbol}</span>
                                        <span className={`ml-2 text-sm ${pos.side === 'long' ? 'text-emerald-400' : 'text-rose-400'}`}>
                                            {pos.side.toUpperCase()}
                                        </span>
                                    </div>
                                    <div className="text-right">
                                        <div className="text-sm text-slate-400">{pos.quantity} shares</div>
                                        {pos.unrealized_pnl && (
                                            <div className={parseFloat(pos.unrealized_pnl) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                                                ${parseFloat(pos.unrealized_pnl).toFixed(2)}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="text-slate-500 text-sm">No open positions</div>
                    )}
                </div>

                <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
                    <h2 className="text-lg font-semibold mb-4">Market Status</h2>
                    <div className="space-y-4">
                        <div className="flex justify-between items-center text-sm">
                            <span className="text-slate-400">US Market</span>
                            <MarketStatusBadge />
                        </div>
                        {dashboardData?.timestamp && (
                            <div className="text-xs text-slate-500 mt-4">
                                Last update: {new Date(dashboardData.timestamp).toLocaleTimeString()}
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {/* Market Regime Panel */}
            <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
                <h2 className="text-lg font-semibold mb-4">Market Regime</h2>
                <RegimePanel interval="1m" compact={false} />
            </div>

            {/* Alerts Panel */}
            <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
                <h2 className="text-lg font-semibold mb-4">Recent Alerts</h2>
                <AlertsPanel maxAlerts={5} />
            </div>
        </div>
    );
};

const MarketStatusBadge: React.FC = () => {
    // Simple market hours check (9:30 AM - 4:00 PM ET, Mon-Fri)
    const now = new Date();
    const etOffset = -5; // EST (simplified, doesn't account for DST)
    const etHour = (now.getUTCHours() + etOffset + 24) % 24;
    const etMinute = now.getUTCMinutes();
    const day = now.getUTCDay();

    const isWeekday = day >= 1 && day <= 5;
    const afterOpen = etHour > 9 || (etHour === 9 && etMinute >= 30);
    const beforeClose = etHour < 16;
    const isOpen = isWeekday && afterOpen && beforeClose;

    return (
        <span className={`font-medium ${isOpen ? 'text-emerald-400' : 'text-slate-500'}`}>
            {isOpen ? 'OPEN' : 'CLOSED'}
        </span>
    );
};

const PnLCard = ({ title, value }: { title: string; value?: string }) => {
    const numValue = value ? parseFloat(value) : 0;
    const isPositive = numValue >= 0;
    const formatted = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(numValue);

    return (
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-5 shadow-sm hover:border-slate-600 transition-colors">
            <h3 className="text-slate-400 text-sm font-medium mb-1">{title}</h3>
            <p className={`text-2xl font-bold tracking-tight ${isPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
                {formatted}
            </p>
        </div>
    );
};

export default Overview;
