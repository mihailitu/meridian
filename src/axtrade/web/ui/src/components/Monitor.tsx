import React from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import OrdersTable from './OrdersTable';
import FillsTable from './FillsTable';

const Monitor: React.FC = () => {
    const { status, lastMessage } = useWebSocket();

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

    return (
        <div className="space-y-6">
            <h2 className="text-xl font-semibold">Live Monitor</h2>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Recent Orders */}
                <div className="bg-slate-800 rounded-xl border border-slate-700 p-5">
                    <h3 className="font-semibold mb-4">Recent Orders</h3>
                    <OrdersTable />
                </div>

                {/* Recent Fills */}
                <div className="bg-slate-800 rounded-xl border border-slate-700 p-5">
                    <h3 className="font-semibold mb-4">Recent Fills</h3>
                    <FillsTable />
                </div>

                {/* WebSocket Feed */}
                <div className="lg:col-span-2 bg-slate-800 rounded-xl border border-slate-700 p-5">
                    <h3 className="font-semibold mb-4">Live Feed</h3>
                    <div className="bg-slate-900 rounded-lg p-4 font-mono text-sm max-h-64 overflow-auto">
                        {lastMessage ? (
                            <pre className="text-slate-300">
                                {JSON.stringify(lastMessage, null, 2)}
                            </pre>
                        ) : (
                            <span className="text-slate-500">Waiting for data...</span>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default Monitor;
