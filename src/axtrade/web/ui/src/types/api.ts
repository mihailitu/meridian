// API response types for REST endpoints

export interface OrderResponse {
    id: string;
    symbol: string;
    side: string;
    quantity: string;
    order_type: string;
    status: string;
    limit_price: string | null;
    filled_quantity: string;
    avg_fill_price: string | null;
    strategy_id: string;
    created_at: string;
    updated_at: string;
}

export interface FillResponse {
    id: string;
    order_id: string;
    symbol: string;
    side: string;
    quantity: string;
    price: string;
    commission: string;
    strategy_id: string;
    filled_at: string;
}

export interface AlertResponse {
    id: string;
    timestamp: string;
    severity: 'info' | 'warning' | 'error' | 'critical';
    category: string;
    title: string;
    message: string;
    source: string;
    metadata: Record<string, unknown>;
    acknowledged: boolean;
    acknowledged_at: string | null;
    acknowledged_by: string | null;
}

export interface AlertCounts {
    by_severity: Record<string, number>;
    unacknowledged: number;
    total: number;
}

export interface PnLSummary {
    daily_realized: string;
    daily_unrealized: string;
    daily_total: string;
    cumulative_realized: string;
}

export interface PnLHistoryPoint {
    timestamp: string;
    cumulative_pnl: number;
}

export interface ComponentHealth {
    name: string;
    status: 'healthy' | 'degraded' | 'unhealthy';
    latency_ms: number | null;
    last_check: string;
    error: string | null;
}

export interface DetailedHealth {
    status: string;
    components: ComponentHealth[];
    timestamp: string;
}
