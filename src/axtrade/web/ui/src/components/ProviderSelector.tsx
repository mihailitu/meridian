import React from 'react';
import { ChevronDown, AlertTriangle, Check, Database, Cloud, Wifi, TestTube } from 'lucide-react';
import { useGatewayStatus, useSetGatewayPreference } from '../hooks/useGateway';
import type { AdapterId } from '../types/gateway';

const ADAPTER_INFO: Record<AdapterId, { label: string; icon: React.ReactNode; description: string }> = {
    mock: {
        label: 'Mock',
        icon: <TestTube className="w-4 h-4" />,
        description: 'Simulated data for testing',
    },
    ibkr: {
        label: 'IBKR',
        icon: <Wifi className="w-4 h-4" />,
        description: 'Interactive Brokers',
    },
    alpaca: {
        label: 'Alpaca',
        icon: <Cloud className="w-4 h-4" />,
        description: 'Alpaca Markets API',
    },
    yahoo: {
        label: 'Yahoo',
        icon: <Database className="w-4 h-4" />,
        description: 'Yahoo Finance (delayed)',
    },
};

interface ProviderSelectorProps {
    compact?: boolean;
}

const ProviderSelector: React.FC<ProviderSelectorProps> = ({ compact = false }) => {
    const { status, refetch } = useGatewayStatus();
    const { setPreference, loading: settingPreference } = useSetGatewayPreference();
    const [isOpen, setIsOpen] = React.useState(false);

    const handleSelect = async (adapter: AdapterId) => {
        if (adapter === status?.current_adapter) {
            setIsOpen(false);
            return;
        }

        try {
            await setPreference(adapter);
            refetch();
        } catch {
            // Error handled by hook
        }
        setIsOpen(false);
    };

    if (!status) {
        return (
            <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-800 rounded border border-slate-700">
                <div className="w-4 h-4 bg-slate-600 rounded animate-pulse" />
                <span className="text-sm text-slate-500">Loading...</span>
            </div>
        );
    }

    const currentInfo = ADAPTER_INFO[status.current_adapter];

    return (
        <div className="relative">
            <button
                onClick={() => setIsOpen(!isOpen)}
                className={`flex items-center gap-2 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 rounded border transition-colors ${
                    status.requires_restart
                        ? 'border-yellow-600/50'
                        : 'border-slate-700'
                }`}
                disabled={settingPreference}
            >
                <span className="text-blue-400">{currentInfo.icon}</span>
                {!compact && (
                    <span className="text-sm font-medium text-slate-200">
                        {currentInfo.label}
                    </span>
                )}
                {status.requires_restart && (
                    <AlertTriangle className="w-3.5 h-3.5 text-yellow-500" />
                )}
                <ChevronDown className={`w-3.5 h-3.5 text-slate-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
            </button>

            {isOpen && (
                <>
                    <div
                        className="fixed inset-0 z-10"
                        onClick={() => setIsOpen(false)}
                    />
                    <div className="absolute right-0 top-full mt-1 z-20 w-56 bg-slate-800 rounded-lg border border-slate-700 shadow-xl overflow-hidden">
                        <div className="px-3 py-2 border-b border-slate-700">
                            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                                Data Provider
                            </span>
                        </div>

                        <div className="py-1">
                            {status.available_adapters.map((adapter) => {
                                const info = ADAPTER_INFO[adapter];
                                const isCurrent = adapter === status.current_adapter;
                                const isPreferred = adapter === status.preferred_adapter;

                                return (
                                    <button
                                        key={adapter}
                                        onClick={() => handleSelect(adapter)}
                                        className={`w-full flex items-center gap-3 px-3 py-2 text-left transition-colors ${
                                            isCurrent
                                                ? 'bg-blue-900/30 text-blue-300'
                                                : 'hover:bg-slate-700/50 text-slate-300'
                                        }`}
                                    >
                                        <span className={isCurrent ? 'text-blue-400' : 'text-slate-400'}>
                                            {info.icon}
                                        </span>
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2">
                                                <span className="text-sm font-medium">{info.label}</span>
                                                {isCurrent && (
                                                    <span className="text-xs px-1.5 py-0.5 bg-blue-600/30 text-blue-300 rounded">
                                                        Active
                                                    </span>
                                                )}
                                                {isPreferred && !isCurrent && (
                                                    <span className="text-xs px-1.5 py-0.5 bg-yellow-600/30 text-yellow-300 rounded">
                                                        Pending
                                                    </span>
                                                )}
                                            </div>
                                            <span className="text-xs text-slate-500">{info.description}</span>
                                        </div>
                                        {isCurrent && (
                                            <Check className="w-4 h-4 text-blue-400" />
                                        )}
                                    </button>
                                );
                            })}
                        </div>

                        {status.requires_restart && (
                            <div className="px-3 py-2 bg-yellow-900/20 border-t border-yellow-700/30">
                                <div className="flex items-start gap-2">
                                    <AlertTriangle className="w-4 h-4 text-yellow-500 mt-0.5" />
                                    <div className="text-xs text-yellow-300">
                                        <span className="font-medium">Restart required</span>
                                        <p className="text-yellow-400/80 mt-0.5">
                                            Run <code className="bg-yellow-900/50 px-1 rounded">make run-{status.preferred_adapter}</code> to switch
                                        </p>
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                </>
            )}
        </div>
    );
};

export default ProviderSelector;
