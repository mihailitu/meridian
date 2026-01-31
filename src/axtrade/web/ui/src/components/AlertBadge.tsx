import React from 'react';
import { useAlerts } from '../hooks/useApi';
import { Bell } from 'lucide-react';

interface AlertBadgeProps {
    onClick?: () => void;
}

const AlertBadge: React.FC<AlertBadgeProps> = ({ onClick }) => {
    const { counts } = useAlerts();
    const unacknowledged = counts?.unacknowledged ?? 0;

    return (
        <button
            onClick={onClick}
            className="relative p-2 hover:bg-slate-700 rounded-lg transition-colors"
            title={`${unacknowledged} unacknowledged alert${unacknowledged !== 1 ? 's' : ''}`}
        >
            <Bell className="w-5 h-5 text-slate-400" />
            {unacknowledged > 0 && (
                <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] flex items-center justify-center bg-rose-500 text-white text-xs font-bold rounded-full px-1">
                    {unacknowledged > 99 ? '99+' : unacknowledged}
                </span>
            )}
        </button>
    );
};

export default AlertBadge;
