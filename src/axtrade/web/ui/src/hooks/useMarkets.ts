import { useState, useEffect, useCallback } from 'react';
import type { AllMarketsStatus, MarketStatus, MarketId } from '../types/market';

const API_BASE = '/api';

async function fetchApi<T>(endpoint: string): Promise<T> {
    const response = await fetch(`${API_BASE}${endpoint}`);
    if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
    }
    return response.json();
}

export function useAllMarkets(pollInterval: number = 30000) {
    const [markets, setMarkets] = useState<MarketStatus[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchMarkets = useCallback(async () => {
        try {
            const data = await fetchApi<AllMarketsStatus>('/markets');
            setMarkets(data.markets);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch markets');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchMarkets();
        const intervalId = setInterval(fetchMarkets, pollInterval);
        return () => clearInterval(intervalId);
    }, [fetchMarkets, pollInterval]);

    return { markets, loading, error, refetch: fetchMarkets };
}

export function useMarketStatus(marketId: MarketId, pollInterval: number = 30000) {
    const [status, setStatus] = useState<MarketStatus | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchStatus = useCallback(async () => {
        try {
            const data = await fetchApi<MarketStatus>(`/markets/${marketId}`);
            setStatus(data);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch market status');
        } finally {
            setLoading(false);
        }
    }, [marketId]);

    useEffect(() => {
        fetchStatus();
        const intervalId = setInterval(fetchStatus, pollInterval);
        return () => clearInterval(intervalId);
    }, [fetchStatus, pollInterval]);

    return { status, loading, error, refetch: fetchStatus };
}

export function useOpenMarkets(pollInterval: number = 30000) {
    const [openMarkets, setOpenMarkets] = useState<MarketId[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchOpenMarkets = useCallback(async () => {
        try {
            const data = await fetchApi<MarketId[]>('/markets/open');
            setOpenMarkets(data);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch open markets');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchOpenMarkets();
        const intervalId = setInterval(fetchOpenMarkets, pollInterval);
        return () => clearInterval(intervalId);
    }, [fetchOpenMarkets, pollInterval]);

    return { openMarkets, loading, error, refetch: fetchOpenMarkets };
}
