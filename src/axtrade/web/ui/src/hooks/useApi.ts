import { useState, useEffect, useCallback } from 'react';
import type {
    OrderResponse,
    FillResponse,
    AlertResponse,
    AlertCounts,
    PnLHistoryPoint,
    DetailedHealth,
} from '../types/api';

const API_BASE = '/api';

async function fetchApi<T>(endpoint: string): Promise<T> {
    const response = await fetch(`${API_BASE}${endpoint}`);
    if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
    }
    return response.json();
}

async function postApi<T>(endpoint: string): Promise<T> {
    const response = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
    });
    if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
    }
    return response.json();
}

export function useOrders(limit: number = 50, pollInterval: number = 5000) {
    const [orders, setOrders] = useState<OrderResponse[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchOrders = useCallback(async () => {
        try {
            const data = await fetchApi<OrderResponse[]>(`/orders?limit=${limit}`);
            setOrders(data);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch orders');
        } finally {
            setLoading(false);
        }
    }, [limit]);

    useEffect(() => {
        fetchOrders();
        const interval = setInterval(fetchOrders, pollInterval);
        return () => clearInterval(interval);
    }, [fetchOrders, pollInterval]);

    return { orders, loading, error, refetch: fetchOrders };
}

export function useFills(limit: number = 50, pollInterval: number = 5000) {
    const [fills, setFills] = useState<FillResponse[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchFills = useCallback(async () => {
        try {
            const data = await fetchApi<FillResponse[]>(`/fills?limit=${limit}`);
            setFills(data);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch fills');
        } finally {
            setLoading(false);
        }
    }, [limit]);

    useEffect(() => {
        fetchFills();
        const interval = setInterval(fetchFills, pollInterval);
        return () => clearInterval(interval);
    }, [fetchFills, pollInterval]);

    return { fills, loading, error, refetch: fetchFills };
}

export function useAlerts(pollInterval: number = 5000) {
    const [alerts, setAlerts] = useState<AlertResponse[]>([]);
    const [counts, setCounts] = useState<AlertCounts | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchAlerts = useCallback(async () => {
        try {
            const [alertsData, countsData] = await Promise.all([
                fetchApi<AlertResponse[]>('/alerts?limit=50'),
                fetchApi<AlertCounts>('/alerts/counts'),
            ]);
            setAlerts(alertsData);
            setCounts(countsData);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch alerts');
        } finally {
            setLoading(false);
        }
    }, []);

    const acknowledgeAlert = useCallback(async (alertId: string) => {
        try {
            await postApi(`/alerts/${alertId}/acknowledge`);
            await fetchAlerts();
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to acknowledge alert');
        }
    }, [fetchAlerts]);

    useEffect(() => {
        fetchAlerts();
        const interval = setInterval(fetchAlerts, pollInterval);
        return () => clearInterval(interval);
    }, [fetchAlerts, pollInterval]);

    return { alerts, counts, loading, error, acknowledgeAlert, refetch: fetchAlerts };
}

export function useHealth(pollInterval: number = 10000) {
    const [health, setHealth] = useState<DetailedHealth | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchHealth = useCallback(async () => {
        try {
            const data = await fetchApi<DetailedHealth>('/health/detailed');
            setHealth(data);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch health');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchHealth();
        const interval = setInterval(fetchHealth, pollInterval);
        return () => clearInterval(interval);
    }, [fetchHealth, pollInterval]);

    return { health, loading, error, refetch: fetchHealth };
}

export function usePnLHistory(hours: number = 24, pollInterval: number = 30000) {
    const [history, setHistory] = useState<PnLHistoryPoint[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchHistory = useCallback(async () => {
        try {
            // Generate flat $0 history - will be replaced with real API data
            // when /api/pnl/history endpoint is implemented
            const now = new Date();
            const points: PnLHistoryPoint[] = [];

            // Create points at start and end showing $0
            for (let i = hours; i >= 0; i -= Math.max(1, Math.floor(hours / 12))) {
                const timestamp = new Date(now.getTime() - i * 60 * 60 * 1000);
                points.push({
                    timestamp: timestamp.toISOString(),
                    cumulative_pnl: 0,
                });
            }

            setHistory(points);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch P&L history');
        } finally {
            setLoading(false);
        }
    }, [hours]);

    useEffect(() => {
        fetchHistory();
        const interval = setInterval(fetchHistory, pollInterval);
        return () => clearInterval(interval);
    }, [fetchHistory, pollInterval]);

    return { history, loading, error, refetch: fetchHistory };
}
