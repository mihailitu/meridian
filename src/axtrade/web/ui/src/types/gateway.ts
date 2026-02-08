export type AdapterId = 'mock' | 'ibkr' | 'alpaca' | 'yahoo';

export interface GatewayStatus {
    current_adapter: AdapterId;
    preferred_adapter: AdapterId | null;
    available_adapters: AdapterId[];
    requires_restart: boolean;
}

export interface GatewayPreferenceRequest {
    adapter: AdapterId;
}
