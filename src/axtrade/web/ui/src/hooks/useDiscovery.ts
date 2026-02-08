import { useState, useEffect, useCallback } from 'react';
import type {
    AddSymbolRequest,
    DiscoveredSymbol,
    DiscoveryState,
    ScreenerResult,
    ScreenerSummary,
} from '../types/discovery';

const API_BASE = '/api';

async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE}${endpoint}`, options);
    if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
    }
    return response.json();
}

export function useDiscoveryState(pollInterval: number = 5000) {
    const [state, setState] = useState<DiscoveryState | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchState = useCallback(async () => {
        try {
            const data = await fetchApi<DiscoveryState>('/discovery/state');
            setState(data);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch discovery state');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchState();
        const intervalId = setInterval(fetchState, pollInterval);
        return () => clearInterval(intervalId);
    }, [fetchState, pollInterval]);

    return { state, loading, error, refetch: fetchState };
}

export interface DiscoveredSymbolsParams {
    minScore?: number;
    source?: string;
    bullishOnly?: boolean;
    bearishOnly?: boolean;
    limit?: number;
}

export function useDiscoveredSymbols(
    params: DiscoveredSymbolsParams = {},
    pollInterval: number = 10000
) {
    const [symbols, setSymbols] = useState<DiscoveredSymbol[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchSymbols = useCallback(async () => {
        try {
            const searchParams = new URLSearchParams();
            if (params.minScore !== undefined) {
                searchParams.set('min_score', params.minScore.toString());
            }
            if (params.source) {
                searchParams.set('source', params.source);
            }
            if (params.bullishOnly) {
                searchParams.set('bullish_only', 'true');
            }
            if (params.bearishOnly) {
                searchParams.set('bearish_only', 'true');
            }
            if (params.limit !== undefined) {
                searchParams.set('limit', params.limit.toString());
            }

            const queryString = searchParams.toString();
            const endpoint = `/discovery/symbols${queryString ? `?${queryString}` : ''}`;
            const data = await fetchApi<DiscoveredSymbol[]>(endpoint);
            setSymbols(data);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch discovered symbols');
        } finally {
            setLoading(false);
        }
    }, [params.minScore, params.source, params.bullishOnly, params.bearishOnly, params.limit]);

    useEffect(() => {
        fetchSymbols();
        const intervalId = setInterval(fetchSymbols, pollInterval);
        return () => clearInterval(intervalId);
    }, [fetchSymbols, pollInterval]);

    return { symbols, loading, error, refetch: fetchSymbols };
}

export function useScreeners() {
    const [screeners, setScreeners] = useState<ScreenerSummary[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchScreeners = useCallback(async () => {
        try {
            const data = await fetchApi<ScreenerSummary[]>('/discovery/screeners');
            setScreeners(data);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch screeners');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchScreeners();
    }, [fetchScreeners]);

    return { screeners, loading, error, refetch: fetchScreeners };
}

export function useScan() {
    const [results, setResults] = useState<ScreenerResult[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const runScan = useCallback(async (options?: {
        screeners?: string[];
        interval?: string;
        barLimit?: number;
    }) => {
        setLoading(true);
        setError(null);
        try {
            const searchParams = new URLSearchParams();
            if (options?.screeners?.length) {
                searchParams.set('screeners', options.screeners.join(','));
            }
            if (options?.interval) {
                searchParams.set('interval', options.interval);
            }
            if (options?.barLimit !== undefined) {
                searchParams.set('bar_limit', options.barLimit.toString());
            }

            const queryString = searchParams.toString();
            const endpoint = `/discovery/scan${queryString ? `?${queryString}` : ''}`;
            const data = await fetchApi<ScreenerResult[]>(endpoint, { method: 'POST' });
            setResults(data);
            return data;
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Failed to run scan';
            setError(message);
            throw err;
        } finally {
            setLoading(false);
        }
    }, []);

    const clearResults = useCallback(() => {
        setResults([]);
        setError(null);
    }, []);

    return { results, loading, error, runScan, clearResults };
}

export function useClearDiscovered() {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const clearDiscovered = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            await fetchApi<{ status: string; message: string }>('/discovery/symbols', {
                method: 'DELETE',
            });
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Failed to clear discoveries';
            setError(message);
            throw err;
        } finally {
            setLoading(false);
        }
    }, []);

    return { loading, error, clearDiscovered };
}

export function useAddSymbol() {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const addSymbol = useCallback(async (request: AddSymbolRequest) => {
        setLoading(true);
        setError(null);
        try {
            const data = await fetchApi<DiscoveredSymbol>('/discovery/symbols', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(request),
            });
            return data;
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Failed to add symbol';
            setError(message);
            throw err;
        } finally {
            setLoading(false);
        }
    }, []);

    return { loading, error, addSymbol };
}
