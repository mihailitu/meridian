import React, { useState } from 'react';
import { useAlerts } from '../hooks/useApi';
import type { AlertResponse } from '../types/api';
import { AlertCircle, AlertTriangle, Info, XCircle, Check, ChevronDown, ChevronUp } from 'lucide-react';

interface AlertsPanelProps {
    maxAlerts?: number;
}

const AlertsPanel: React.FC<AlertsPanelProps> = ({ maxAlerts = 10 }) => {
    const { alerts, loading, error, acknowledgeAlert } = useAlerts();
    const [expandedId, setExpandedId] = useState<string | null>(null);

    if (loading && alerts.length === 0) {
        return (
            <div className="text-slate-500 text-sm">Loading alerts...</div>
        );
    }

    if (error) {
        return (
            <div className="text-rose-400 text-sm">Error: {error}</div>
        );
    }

    const displayAlerts = alerts.slice(0, maxAlerts);

    if (displayAlerts.length === 0) {
        return (
            <div className="text-slate-500 text-sm flex items-center gap-2">
                <Info className="w-4 h-4" />
                No recent alerts
            </div>
        );
    }

    return (
        <div className="space-y-2">
            {displayAlerts.map((alert) => (
                <AlertItem
                    key={alert.id}
                    alert={alert}
                    expanded={expandedId === alert.id}
                    onToggle={() => setExpandedId(expandedId === alert.id ? null : alert.id)}
                    onAcknowledge={() => acknowledgeAlert(alert.id)}
                />
            ))}
        </div>
    );
};

interface AlertItemProps {
    alert: AlertResponse;
    expanded: boolean;
    onToggle: () => void;
    onAcknowledge: () => void;
}

const AlertItem: React.FC<AlertItemProps> = ({ alert, expanded, onToggle, onAcknowledge }) => {
    const time = new Date(alert.timestamp).toLocaleTimeString();
    const { icon: Icon, colorClass, bgClass } = getSeverityStyle(alert.severity);

    return (
        <div className={`rounded-lg border ${bgClass} ${alert.acknowledged ? 'opacity-60' : ''}`}>
            <div
                className="flex items-center gap-3 p-3 cursor-pointer"
                onClick={onToggle}
            >
                <Icon className={`w-5 h-5 flex-shrink-0 ${colorClass}`} />
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                        <span className="font-medium text-sm truncate">{alert.title}</span>
                        <span className="text-xs text-slate-500">{time}</span>
                    </div>
                    {!expanded && (
                        <p className="text-xs text-slate-400 truncate">{alert.message}</p>
                    )}
                </div>
                <div className="flex items-center gap-2">
                    {!alert.acknowledged && (
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                onAcknowledge();
                            }}
                            className="p-1.5 hover:bg-slate-600 rounded transition-colors"
                            title="Acknowledge"
                        >
                            <Check className="w-4 h-4 text-slate-400 hover:text-emerald-400" />
                        </button>
                    )}
                    {expanded ? (
                        <ChevronUp className="w-4 h-4 text-slate-400" />
                    ) : (
                        <ChevronDown className="w-4 h-4 text-slate-400" />
                    )}
                </div>
            </div>
            {expanded && (
                <div className="px-3 pb-3 pt-0 border-t border-slate-700">
                    <p className="text-sm text-slate-300 mt-2">{alert.message}</p>
                    <div className="flex gap-4 mt-2 text-xs text-slate-500">
                        <span>Source: {alert.source}</span>
                        <span>Category: {alert.category}</span>
                        {alert.acknowledged && alert.acknowledged_at && (
                            <span>
                                Acked: {new Date(alert.acknowledged_at).toLocaleTimeString()}
                            </span>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
};

function getSeverityStyle(severity: string) {
    switch (severity.toLowerCase()) {
        case 'critical':
            return {
                icon: XCircle,
                colorClass: 'text-purple-400',
                bgClass: 'bg-purple-900/20 border-purple-800/50',
            };
        case 'error':
            return {
                icon: AlertCircle,
                colorClass: 'text-rose-400',
                bgClass: 'bg-rose-900/20 border-rose-800/50',
            };
        case 'warning':
            return {
                icon: AlertTriangle,
                colorClass: 'text-yellow-400',
                bgClass: 'bg-yellow-900/20 border-yellow-800/50',
            };
        default:
            return {
                icon: Info,
                colorClass: 'text-blue-400',
                bgClass: 'bg-blue-900/20 border-blue-800/50',
            };
    }
}

export default AlertsPanel;
