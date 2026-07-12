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

export interface AddSymbolRequest {
    symbol: string;
    price?: number;
    notes?: string;
}

/** Ack shape for discovery control commands (scan / add_symbols / remove_symbols).
 * Discovery scanning runs in the strategy-runner process (audit P1-3); these
 * endpoints publish a command and return immediately rather than the
 * command's eventual result -- poll /discovery/state or /discovery/symbols. */
export interface DiscoveryCommandAccepted {
    status: string;
    command: string;
    message: string;
}
