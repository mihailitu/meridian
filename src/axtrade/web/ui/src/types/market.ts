export type MarketId = 'us' | 'eu' | 'asia' | 'crypto' | 'forex';

export interface MarketStatus {
    market: MarketId;
    is_open: boolean;
    is_extended_hours: boolean;
    time_until_open: string | null;
    time_until_close: string | null;
    timezone: string;
    local_time: string;
    open_time: string;
    close_time: string;
}

export interface AllMarketsStatus {
    markets: MarketStatus[];
}

export const MARKET_LABELS: Record<MarketId, string> = {
    us: 'US',
    eu: 'EU',
    asia: 'Asia',
    crypto: 'Crypto',
    forex: 'Forex',
};

export const MARKET_COLORS: Record<MarketId, string> = {
    us: 'text-blue-400',
    eu: 'text-purple-400',
    asia: 'text-orange-400',
    crypto: 'text-yellow-400',
    forex: 'text-emerald-400',
};
