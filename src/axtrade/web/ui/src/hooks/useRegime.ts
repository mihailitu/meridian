import { useState, useEffect, useCallback } from 'react';
import type {
    RegimeCurrentResponse,
    RegimeHistoryResponse,
    RegimeSummaryResponse,
} from '../types/regime';

const API_BASE = '/api';

async function fetchApi<T>(endpoint: string): Promise<T> {
    const response = await fetch(`${API_BASE}${endpoint}`);
    if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
    }
    return response.json();
}

export function useCurrentRegime(symbol: string, interval: string = '1m', pollInterval: number = 5000) {
    const [regime, setRegime] = useState<RegimeCurrentResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchRegime = useCallback(async () => {
        if (!symbol) return;
        try {
            const data = await fetchApi<RegimeCurrentResponse>(
                `/regime/current?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}`
            );
            setRegime(data);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch regime');
        } finally {
            setLoading(false);
        }
    }, [symbol, interval]);

    useEffect(() => {
        fetchRegime();
        const intervalId = setInterval(fetchRegime, pollInterval);
        return () => clearInterval(intervalId);
    }, [fetchRegime, pollInterval]);

    return { regime, loading, error, refetch: fetchRegime };
}

export function useRegimeHistory(
    symbol: string,
    interval: string = '1m',
    hours: number = 24,
    pollInterval: number = 30000
) {
    const [history, setHistory] = useState<RegimeHistoryResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchHistory = useCallback(async () => {
        if (!symbol) return;
        try {
            const data = await fetchApi<RegimeHistoryResponse>(
                `/regime/history?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}&hours=${hours}`
            );
            setHistory(data);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch regime history');
        } finally {
            setLoading(false);
        }
    }, [symbol, interval, hours]);

    useEffect(() => {
        fetchHistory();
        const intervalId = setInterval(fetchHistory, pollInterval);
        return () => clearInterval(intervalId);
    }, [fetchHistory, pollInterval]);

    return { history, loading, error, refetch: fetchHistory };
}

export function useRegimeSummary(interval: string = '1m', pollInterval: number = 5000) {
    const [summary, setSummary] = useState<RegimeSummaryResponse[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchSummary = useCallback(async () => {
        try {
            const data = await fetchApi<RegimeSummaryResponse[]>(
                `/regime/summary?interval=${encodeURIComponent(interval)}`
            );
            setSummary(data);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch regime summary');
        } finally {
            setLoading(false);
        }
    }, [interval]);

    useEffect(() => {
        fetchSummary();
        const intervalId = setInterval(fetchSummary, pollInterval);
        return () => clearInterval(intervalId);
    }, [fetchSummary, pollInterval]);

    return { summary, loading, error, refetch: fetchSummary };
}
