import React from 'react';
import {
    LineChart,
    Line,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
    ReferenceLine,
} from 'recharts';
import { usePnLHistory } from '../hooks/useApi';

interface PnLChartProps {
    hours?: number;
}

const PnLChart: React.FC<PnLChartProps> = ({ hours = 24 }) => {
    const { history, loading, error } = usePnLHistory(hours);

    if (loading && history.length === 0) {
        return (
            <div className="h-64 flex items-center justify-center text-slate-500">
                Loading chart data...
            </div>
        );
    }

    if (error) {
        return (
            <div className="h-64 flex items-center justify-center text-rose-400">
                Error: {error}
            </div>
        );
    }

    if (history.length === 0) {
        return (
            <div className="h-64 flex items-center justify-center text-slate-500">
                No P&L data available
            </div>
        );
    }

    // Determine if overall positive or negative
    const lastValue = history[history.length - 1]?.cumulative_pnl ?? 0;
    const lineColor = lastValue >= 0 ? '#10b981' : '#f43f5e';

    // Format data for chart
    const chartData = history.map((point) => ({
        time: new Date(point.timestamp).toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
        }),
        pnl: point.cumulative_pnl,
    }));

    return (
        <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
                <LineChart
                    data={chartData}
                    margin={{ top: 5, right: 20, left: 10, bottom: 5 }}
                >
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis
                        dataKey="time"
                        stroke="#64748b"
                        fontSize={12}
                        tickLine={false}
                        interval="preserveStartEnd"
                    />
                    <YAxis
                        stroke="#64748b"
                        fontSize={12}
                        tickLine={false}
                        tickFormatter={(value) => `$${value}`}
                    />
                    <Tooltip
                        contentStyle={{
                            backgroundColor: '#1e293b',
                            border: '1px solid #334155',
                            borderRadius: '8px',
                        }}
                        labelStyle={{ color: '#94a3b8' }}
                        formatter={(value: number) => [
                            `$${value.toFixed(2)}`,
                            'P&L',
                        ]}
                    />
                    <ReferenceLine y={0} stroke="#475569" strokeDasharray="3 3" />
                    <Line
                        type="monotone"
                        dataKey="pnl"
                        stroke={lineColor}
                        strokeWidth={2}
                        dot={false}
                        activeDot={{ r: 4, fill: lineColor }}
                    />
                </LineChart>
            </ResponsiveContainer>
        </div>
    );
};

export default PnLChart;
