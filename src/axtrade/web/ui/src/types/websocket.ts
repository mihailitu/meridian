export type ConnectionStatus = 'connected' | 'disconnected' | 'connecting';

export interface PnLData {
    daily_total: string;
    daily_realized: string;
    daily_unrealized: string;
    cumulative_realized: string;
}

export interface Position {
    symbol: string;
    side: string;
    quantity: string;
    avg_entry_price: string;
    current_price: string | null;
    unrealized_pnl: string | null;
    strategy_id: string | null;
}

export interface DashboardData {
    positions: Position[];
    pnl: PnLData;
    timestamp: string;
}

export interface WebSocketMessage {
    type: 'dashboard' | 'alert' | string;
    data: DashboardData | Record<string, unknown>;
}

export interface WebSocketContextType {
    status: ConnectionStatus;
    lastMessage: WebSocketMessage | null;
    sendMessage: (msg: Record<string, unknown>) => void;
}
