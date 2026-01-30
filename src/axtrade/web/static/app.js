// Dashboard WebSocket client

class Dashboard {
    constructor() {
        this.ws = null;
        this.reconnectTimeout = null;
        this.reconnectDelay = 1000;
        this.maxReconnectDelay = 30000;
        this.alerts = [];
        this.maxAlerts = 50;

        this.elements = {
            connectionStatus: document.getElementById('connection-status'),
            lastUpdate: document.getElementById('last-update'),
            dailyRealized: document.getElementById('daily-realized'),
            dailyUnrealized: document.getElementById('daily-unrealized'),
            dailyTotal: document.getElementById('daily-total'),
            cumulative: document.getElementById('cumulative'),
            positionsTable: document.getElementById('positions-table').querySelector('tbody'),
            ordersTable: document.getElementById('orders-table').querySelector('tbody'),
            alertsList: document.getElementById('alerts-list'),
            alertBadge: document.getElementById('alert-badge'),
            toggleAlerts: document.getElementById('toggle-alerts'),
            healthRedis: document.getElementById('health-redis'),
            healthDatabase: document.getElementById('health-database'),
            healthBroker: document.getElementById('health-broker'),
            sharpeRatio: document.getElementById('sharpe-ratio'),
            sortinoRatio: document.getElementById('sortino-ratio'),
            winRate: document.getElementById('win-rate'),
            tradeCount: document.getElementById('trade-count'),
            maxDrawdown: document.getElementById('max-drawdown'),
            currentDrawdown: document.getElementById('current-drawdown'),
            profitFactor: document.getElementById('profit-factor'),
            expectancy: document.getElementById('expectancy'),
        };

        this.setupAlertToggle();
        this.connect();
        this.loadOrders();
        this.loadAlerts();
        this.loadHealth();
        this.loadAnalytics();
    }

    setupAlertToggle() {
        this.elements.toggleAlerts.addEventListener('click', () => {
            const list = this.elements.alertsList;
            const btn = this.elements.toggleAlerts;
            if (list.classList.contains('collapsed')) {
                list.classList.remove('collapsed');
                btn.textContent = 'Hide';
            } else {
                list.classList.add('collapsed');
                btn.textContent = 'Show';
            }
        });
    }

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            this.setConnected(true);
            this.reconnectDelay = 1000;
        };

        this.ws.onclose = () => {
            this.setConnected(false);
            this.scheduleReconnect();
        };

        this.ws.onerror = () => {
            this.setConnected(false);
        };

        this.ws.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                this.handleMessage(message);
            } catch (e) {
                console.error('Failed to parse WebSocket message:', e);
            }
        };
    }

    handleMessage(message) {
        if (message.type === 'dashboard') {
            this.updateDashboard(message.data);
        } else if (message.type === 'alert') {
            this.addAlert(message.data);
        } else {
            // Legacy format (no type wrapper)
            this.updateDashboard(message);
        }
    }

    scheduleReconnect() {
        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout);
        }

        this.reconnectTimeout = setTimeout(() => {
            this.connect();
        }, this.reconnectDelay);

        // Exponential backoff
        this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
    }

    setConnected(connected) {
        const status = this.elements.connectionStatus;
        if (connected) {
            status.textContent = 'Connected';
            status.className = 'connected';
        } else {
            status.textContent = 'Disconnected';
            status.className = 'disconnected';
        }
    }

    formatCurrency(value) {
        const num = parseFloat(value);
        const formatted = new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD',
            minimumFractionDigits: 2,
        }).format(Math.abs(num));

        return num < 0 ? `-${formatted}` : formatted;
    }

    formatNumber(value, decimals = 2) {
        const num = parseFloat(value);
        return num.toFixed(decimals);
    }

    formatTime(isoString) {
        const date = new Date(isoString);
        return date.toLocaleTimeString();
    }

    formatDateTime(isoString) {
        const date = new Date(isoString);
        return date.toLocaleString();
    }

    formatRelativeTime(isoString) {
        const date = new Date(isoString);
        const now = new Date();
        const diffMs = now - date;
        const diffSec = Math.floor(diffMs / 1000);
        const diffMin = Math.floor(diffSec / 60);
        const diffHour = Math.floor(diffMin / 60);

        if (diffSec < 60) return 'just now';
        if (diffMin < 60) return `${diffMin}m ago`;
        if (diffHour < 24) return `${diffHour}h ago`;
        return date.toLocaleDateString();
    }

    setPnLValue(element, value) {
        const num = parseFloat(value);
        element.textContent = this.formatCurrency(value);
        element.classList.remove('positive', 'negative');
        if (num > 0) {
            element.classList.add('positive');
        } else if (num < 0) {
            element.classList.add('negative');
        }
    }

    updateDashboard(data) {
        // Update timestamp
        this.elements.lastUpdate.textContent = `Last update: ${this.formatTime(data.timestamp)}`;

        // Update P&L cards
        this.setPnLValue(this.elements.dailyRealized, data.pnl.daily_realized);
        this.setPnLValue(this.elements.dailyUnrealized, data.pnl.daily_unrealized);
        this.setPnLValue(this.elements.dailyTotal, data.pnl.daily_total);
        this.setPnLValue(this.elements.cumulative, data.pnl.cumulative_realized);

        // Update positions table
        this.updatePositionsTable(data.positions);
    }

    updatePositionsTable(positions) {
        if (positions.length === 0) {
            this.elements.positionsTable.innerHTML = `
                <tr class="empty-row">
                    <td colspan="7">No open positions</td>
                </tr>
            `;
            return;
        }

        this.elements.positionsTable.innerHTML = positions.map(pos => `
            <tr>
                <td>${pos.symbol}</td>
                <td class="side-${pos.side}">${pos.side.toUpperCase()}</td>
                <td>${this.formatNumber(pos.quantity, 0)}</td>
                <td>$${this.formatNumber(pos.avg_entry_price)}</td>
                <td>${pos.current_price ? '$' + this.formatNumber(pos.current_price) : '-'}</td>
                <td class="${parseFloat(pos.unrealized_pnl || 0) >= 0 ? 'positive' : 'negative'}">
                    ${pos.unrealized_pnl ? this.formatCurrency(pos.unrealized_pnl) : '-'}
                </td>
                <td>${pos.strategy_id}</td>
            </tr>
        `).join('');
    }

    async loadOrders() {
        try {
            const response = await fetch('/api/orders?limit=20');
            if (response.ok) {
                const orders = await response.json();
                this.updateOrdersTable(orders);
            }
        } catch (e) {
            console.error('Failed to load orders:', e);
        }

        // Refresh orders every 5 seconds
        setTimeout(() => this.loadOrders(), 5000);
    }

    updateOrdersTable(orders) {
        if (orders.length === 0) {
            this.elements.ordersTable.innerHTML = `
                <tr class="empty-row">
                    <td colspan="8">No recent orders</td>
                </tr>
            `;
            return;
        }

        this.elements.ordersTable.innerHTML = orders.map(order => `
            <tr>
                <td>${this.formatDateTime(order.created_at)}</td>
                <td>${order.symbol}</td>
                <td class="side-${order.side}">${order.side.toUpperCase()}</td>
                <td>${this.formatNumber(order.quantity, 0)}</td>
                <td>${order.order_type}</td>
                <td class="status-${order.status}">${order.status}</td>
                <td>${order.avg_fill_price ? '$' + this.formatNumber(order.avg_fill_price) : '-'}</td>
                <td>${order.strategy_id}</td>
            </tr>
        `).join('');
    }

    // Alerts handling

    async loadAlerts() {
        try {
            const response = await fetch('/api/alerts?limit=50');
            if (response.ok) {
                this.alerts = await response.json();
                this.renderAlerts();
            }
        } catch (e) {
            console.error('Failed to load alerts:', e);
        }
    }

    addAlert(alert) {
        // Add to front of list
        this.alerts.unshift(alert);
        // Keep only maxAlerts
        if (this.alerts.length > this.maxAlerts) {
            this.alerts.pop();
        }
        this.renderAlerts();
    }

    renderAlerts() {
        const unacknowledged = this.alerts.filter(a => !a.acknowledged).length;

        // Update badge
        if (unacknowledged > 0) {
            this.elements.alertBadge.textContent = unacknowledged;
            this.elements.alertBadge.style.display = 'inline';
        } else {
            this.elements.alertBadge.style.display = 'none';
        }

        // Render list
        if (this.alerts.length === 0) {
            this.elements.alertsList.innerHTML = '<div class="empty-alerts">No alerts</div>';
            return;
        }

        this.elements.alertsList.innerHTML = this.alerts.map(alert => `
            <div class="alert-item ${alert.acknowledged ? 'acknowledged' : ''}" data-id="${alert.id}">
                <div class="alert-severity ${alert.severity}"></div>
                <div class="alert-content">
                    <div class="alert-title">${this.escapeHtml(alert.title)}</div>
                    <div class="alert-message">${this.escapeHtml(alert.message)}</div>
                    <div class="alert-meta">
                        ${alert.source} - ${this.formatRelativeTime(alert.timestamp)}
                    </div>
                </div>
                ${!alert.acknowledged ? `
                    <div class="alert-actions">
                        <button class="ack-btn" onclick="dashboard.acknowledgeAlert('${alert.id}')" title="Acknowledge">
                            &#10003;
                        </button>
                    </div>
                ` : ''}
            </div>
        `).join('');
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    async acknowledgeAlert(alertId) {
        try {
            const response = await fetch(`/api/alerts/${alertId}/acknowledge`, {
                method: 'POST',
            });
            if (response.ok) {
                // Update local state
                const alert = this.alerts.find(a => a.id === alertId);
                if (alert) {
                    alert.acknowledged = true;
                    this.renderAlerts();
                }
            }
        } catch (e) {
            console.error('Failed to acknowledge alert:', e);
        }
    }

    // Health monitoring

    async loadHealth() {
        try {
            const response = await fetch('/api/health/detailed');
            if (response.ok) {
                const health = await response.json();
                this.updateHealthIndicators(health);
            }
        } catch (e) {
            // API not available, show unknown status
            this.setHealthStatus('redis', 'unknown');
            this.setHealthStatus('database', 'unknown');
            this.setHealthStatus('broker', 'unknown');
        }

        // Refresh health every 10 seconds
        setTimeout(() => this.loadHealth(), 10000);
    }

    updateHealthIndicators(health) {
        const components = health.components || {};

        // Update each indicator
        if (components.redis) {
            this.setHealthStatus('redis', components.redis.status);
        }
        if (components.database) {
            this.setHealthStatus('database', components.database.status);
        }
        if (components.broker) {
            this.setHealthStatus('broker', components.broker.status);
        }
    }

    setHealthStatus(component, status) {
        const element = this.elements[`health${component.charAt(0).toUpperCase() + component.slice(1)}`];
        if (!element) return;

        // Remove all status classes
        element.classList.remove('healthy', 'degraded', 'unhealthy');

        // Add new status class
        if (status === 'healthy' || status === 'degraded' || status === 'unhealthy') {
            element.classList.add(status);
        }

        // Update title
        element.title = `${component.charAt(0).toUpperCase() + component.slice(1)}: ${status}`;
    }

    // Analytics

    async loadAnalytics() {
        try {
            // Load rolling metrics, trade stats, and drawdown in parallel
            const [rolling, trades, drawdown] = await Promise.all([
                fetch('/api/analytics/rolling?window=30').then(r => r.ok ? r.json() : null),
                fetch('/api/analytics/trades').then(r => r.ok ? r.json() : null),
                fetch('/api/analytics/drawdown').then(r => r.ok ? r.json() : null),
            ]);

            this.updateAnalytics(rolling, trades, drawdown);
        } catch (e) {
            console.error('Failed to load analytics:', e);
        }

        // Refresh analytics every 30 seconds
        setTimeout(() => this.loadAnalytics(), 30000);
    }

    updateAnalytics(rolling, trades, drawdown) {
        // Rolling metrics
        if (rolling) {
            this.elements.sharpeRatio.textContent = rolling.sharpe_ratio !== null
                ? rolling.sharpe_ratio.toFixed(2)
                : '-';
            this.elements.sortinoRatio.textContent = rolling.sortino_ratio !== null
                ? rolling.sortino_ratio.toFixed(2)
                : '-';
        }

        // Trade stats
        if (trades) {
            this.elements.winRate.textContent = trades.total_trades > 0
                ? `${trades.win_rate.toFixed(1)}%`
                : '-';
            this.elements.tradeCount.textContent = `${trades.total_trades} trades`;

            this.elements.profitFactor.textContent = trades.profit_factor !== null && isFinite(trades.profit_factor)
                ? trades.profit_factor.toFixed(2)
                : '-';

            const expectancy = parseFloat(trades.expectancy);
            this.elements.expectancy.textContent = !isNaN(expectancy)
                ? this.formatCurrency(expectancy)
                : '-';
            this.setValueColor(this.elements.expectancy, expectancy);
        }

        // Drawdown
        if (drawdown) {
            this.elements.maxDrawdown.textContent = drawdown.max_drawdown_pct > 0
                ? `-${drawdown.max_drawdown_pct.toFixed(1)}%`
                : '-';
            this.elements.maxDrawdown.classList.add('negative');

            this.elements.currentDrawdown.textContent = drawdown.in_drawdown
                ? `Current: -${drawdown.current_drawdown_pct.toFixed(1)}%`
                : 'Not in drawdown';
        }
    }

    setValueColor(element, value) {
        element.classList.remove('positive', 'negative');
        if (value > 0) {
            element.classList.add('positive');
        } else if (value < 0) {
            element.classList.add('negative');
        }
    }
}

// Initialize dashboard when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.dashboard = new Dashboard();
});
