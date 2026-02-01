import { useState, useEffect, useCallback } from 'react';
import type {
    MLModel,
    MLPrediction,
    MLSummary,
    CreateModelRequest,
} from '../types/ml';

const API_BASE = '/api';

async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE}${endpoint}`, options);
    if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
    }
    return response.json();
}

export function useMLModels(pollInterval: number = 30000) {
    const [models, setModels] = useState<MLModel[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchModels = useCallback(async () => {
        try {
            const data = await fetchApi<MLModel[]>('/ml/models');
            setModels(data);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch models');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchModels();
        const intervalId = setInterval(fetchModels, pollInterval);
        return () => clearInterval(intervalId);
    }, [fetchModels, pollInterval]);

    return { models, loading, error, refetch: fetchModels };
}

export function useMLModel(modelId: string) {
    const [model, setModel] = useState<MLModel | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchModel = useCallback(async () => {
        if (!modelId) return;
        try {
            const data = await fetchApi<MLModel>(`/ml/models/${modelId}`);
            setModel(data);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch model');
        } finally {
            setLoading(false);
        }
    }, [modelId]);

    useEffect(() => {
        fetchModel();
    }, [fetchModel]);

    return { model, loading, error, refetch: fetchModel };
}

export function useCreateModel() {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const createModel = useCallback(async (request: CreateModelRequest): Promise<MLModel | null> => {
        setLoading(true);
        setError(null);
        try {
            const data = await fetchApi<MLModel>('/ml/models', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(request),
            });
            return data;
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Failed to create model';
            setError(message);
            return null;
        } finally {
            setLoading(false);
        }
    }, []);

    return { createModel, loading, error };
}

export function useDeleteModel() {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const deleteModel = useCallback(async (modelId: string): Promise<boolean> => {
        setLoading(true);
        setError(null);
        try {
            await fetchApi<{ status: string }>(`/ml/models/${modelId}`, {
                method: 'DELETE',
            });
            return true;
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Failed to delete model';
            setError(message);
            return false;
        } finally {
            setLoading(false);
        }
    }, []);

    return { deleteModel, loading, error };
}

export function useMLPredictions(symbol: string, limit: number = 20, pollInterval: number = 10000) {
    const [predictions, setPredictions] = useState<MLPrediction[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchPredictions = useCallback(async () => {
        if (!symbol) return;
        try {
            const data = await fetchApi<MLPrediction[]>(
                `/ml/predictions/${encodeURIComponent(symbol)}?limit=${limit}`
            );
            setPredictions(data);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch predictions');
        } finally {
            setLoading(false);
        }
    }, [symbol, limit]);

    useEffect(() => {
        fetchPredictions();
        const intervalId = setInterval(fetchPredictions, pollInterval);
        return () => clearInterval(intervalId);
    }, [fetchPredictions, pollInterval]);

    return { predictions, loading, error, refetch: fetchPredictions };
}

export function useMLSummary(pollInterval: number = 30000) {
    const [summary, setSummary] = useState<MLSummary | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchSummary = useCallback(async () => {
        try {
            const data = await fetchApi<MLSummary>('/ml/summary');
            setSummary(data);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch ML summary');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchSummary();
        const intervalId = setInterval(fetchSummary, pollInterval);
        return () => clearInterval(intervalId);
    }, [fetchSummary, pollInterval]);

    return { summary, loading, error, refetch: fetchSummary };
}
