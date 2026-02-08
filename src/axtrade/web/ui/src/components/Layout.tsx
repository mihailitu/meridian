import React from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import { Activity, Wifi, WifiOff, Loader2 } from 'lucide-react';
import AlertBadge from './AlertBadge';
import MarketStatusBar from './MarketStatusBar';
import ProviderSelector from './ProviderSelector';

export type ActiveTab = 'overview' | 'strategies' | 'discovery' | 'ml' | 'monitor';

interface LayoutProps {
    children: React.ReactNode;
    activeTab: ActiveTab;
    onTabChange: (tab: ActiveTab) => void;
}

const Layout: React.FC<LayoutProps> = ({ children, activeTab, onTabChange }) => {
    const { status } = useWebSocket();

    const getStatusIcon = () => {
        switch (status) {
            case 'connected':
                return <Wifi className="w-4 h-4" />;
            case 'connecting':
                return <Loader2 className="w-4 h-4 animate-spin" />;
            default:
                return <WifiOff className="w-4 h-4" />;
        }
    };

    const getStatusStyle = () => {
        switch (status) {
            case 'connected':
                return 'bg-green-900/30 text-green-400';
            case 'connecting':
                return 'bg-yellow-900/30 text-yellow-400';
            default:
                return 'bg-red-900/30 text-red-400';
        }
    };

    return (
        <div className="min-h-screen bg-slate-900 text-slate-100 font-sans">
            {/* Header */}
            <header className="bg-slate-800 border-b border-slate-700 px-6 py-4 flex items-center justify-between shadow-sm">
                <div className="flex items-center gap-3">
                    <Activity className="text-blue-500 w-6 h-6" />
                    <h1 className="text-xl font-bold tracking-tight">axtrade <span className="text-slate-500 font-light">Pro</span></h1>
                </div>

                <div className="flex items-center gap-6">
                    {/* Market Status Indicators */}
                    <MarketStatusBar compact />

                    {/* Provider Selector */}
                    <ProviderSelector />

                    {/* Health Indicators - reflect WebSocket status */}
                    <div className="flex gap-2">
                        <HealthDot label="Redis" status={status} />
                        <HealthDot label="DB" status={status} />
                        <HealthDot label="Gateway" status={status} />
                    </div>

                    {/* Alert Badge */}
                    <AlertBadge />

                    {/* Connection Status */}
                    <div className={`flex items-center gap-2 px-3 py-1 rounded-full text-sm font-medium ${getStatusStyle()}`}>
                        {getStatusIcon()}
                        <span className="capitalize">{status}</span>
                    </div>
                </div>
            </header>

            {/* Navigation */}
            <nav className="bg-slate-800/50 border-b border-slate-700 px-6">
                <div className="flex gap-6">
                    <NavTab label="Overview" active={activeTab === 'overview'} onClick={() => onTabChange('overview')} />
                    <NavTab label="Strategies" active={activeTab === 'strategies'} onClick={() => onTabChange('strategies')} />
                    <NavTab label="Discovery" active={activeTab === 'discovery'} onClick={() => onTabChange('discovery')} />
                    <NavTab label="ML Models" active={activeTab === 'ml'} onClick={() => onTabChange('ml')} />
                    <NavTab label="Live Monitor" active={activeTab === 'monitor'} onClick={() => onTabChange('monitor')} />
                </div>
            </nav>

            {/* Main Content */}
            <main className="p-6 max-w-7xl mx-auto">
                {children}
            </main>
        </div>
    );
};

type ConnectionStatus = 'connected' | 'disconnected' | 'connecting';

const HealthDot = ({ label, status }: { label: string; status: ConnectionStatus }) => {
    const dotColor = status === 'connected'
        ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]'
        : status === 'connecting'
        ? 'bg-yellow-500 shadow-[0_0_8px_rgba(234,179,8,0.5)]'
        : 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.5)]';

    return (
        <div className="flex items-center gap-1.5 px-2 py-1 bg-slate-800 rounded border border-slate-700">
            <div className={`w-2 h-2 rounded-full ${dotColor}`}></div>
            <span className="text-xs font-medium text-slate-400">{label}</span>
        </div>
    );
};

const NavTab = ({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) => (
    <button
        onClick={onClick}
        className={`py-4 px-2 text-sm font-medium transition-colors border-b-2 relative ${active
            ? 'text-blue-400 border-blue-500'
            : 'text-slate-400 border-transparent hover:text-slate-200'
            }`}
    >
        {label}
    </button>
);

export default Layout;
