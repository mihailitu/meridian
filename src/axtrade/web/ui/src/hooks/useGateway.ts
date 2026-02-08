import { useState, useEffect, useCallback } from 'react';
import type { AdapterId, GatewayStatus } from '../types/gateway';

const API_BASE = '/api';

async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE}${endpoint}`, options);
    if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
    }
    return response.json();
}

export function useGatewayStatus(pollInterval: number = 10000) {
    const [status, setStatus] = useState<GatewayStatus | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchStatus = useCallback(async () => {
        try {
            const data = await fetchApi<GatewayStatus>('/gateway/status');
            setStatus(data);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch gateway status');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchStatus();
        const intervalId = setInterval(fetchStatus, pollInterval);
        return () => clearInterval(intervalId);
    }, [fetchStatus, pollInterval]);

    return { status, loading, error, refetch: fetchStatus };
}

export function useSetGatewayPreference() {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const setPreference = useCallback(async (adapter: AdapterId) => {
        setLoading(true);
        setError(null);
        try {
            const data = await fetchApi<GatewayStatus>('/gateway/preference', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ adapter }),
            });
            return data;
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Failed to set preference';
            setError(message);
            throw err;
        } finally {
            setLoading(false);
        }
    }, []);

    return { loading, error, setPreference };
}
