export interface DiscoveredSymbol {
    symbol: string;
    source: string;
    score: number;
    price: number | null;
    volume: number | null;
    change_pct: number | null;
    discovered_at: string;
    metadata: Record<string, unknown>;
}

export interface ScreenerResult {
    screener_name: string;
    screener_type: string;
    match_count: number;
    total_scanned: number;
    scan_time_ms: number;
    timestamp: string;
    symbols: DiscoveredSymbol[];
}

export interface ScreenerSummary {
    name: string;
    type: string;
    params: Record<string, unknown>;
}

export interface DiscoveryState {
    active_screeners: string[];
    last_scan: string | null;
    total_discovered: number;
    is_scanning: boolean;
}

export type SignalDirection = 'bullish' | 'bearish' | 'neutral';

export function getSignalDirection(score: number): SignalDirection {
    if (score > 0) return 'bullish';
    if (score < 0) return 'bearish';
    return 'neutral';
}
