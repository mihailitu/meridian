// Dashboard template functions
// Edit these functions to change the dashboard appearance

const Templates = {
    // Escape HTML to prevent XSS
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    // Format currency value
    formatCurrency(value) {
        const num = parseFloat(value);
        const formatted = new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD',
            minimumFractionDigits: 2,
        }).format(Math.abs(num));
        return num < 0 ? `-${formatted}` : formatted;
    },

    // Format number with decimals
    formatNumber(value, decimals = 2) {
        const num = parseFloat(value);
        return isNaN(num) ? '-' : num.toFixed(decimals);
    },

    // Format percentage
    formatPercent(value, decimals = 1) {
        const num = parseFloat(value);
        return isNaN(num) ? '-' : `${num.toFixed(decimals)}%`;
    },

    // Format datetime
    formatDateTime(isoString) {
        if (!isoString) return '-';
        const date = new Date(isoString);
        return date.toLocaleString();
    },

    // Get CSS class for P&L value
    getPnlClass(value) {
        const num = parseFloat(value);
        if (num > 0) return 'positive';
        if (num < 0) return 'negative';
        return '';
    },

    // Metric card template
    metricCard(title, value, subtitle = '', cssClass = '') {
        return `
            <div class="metric-card ${cssClass}">
                <h3>${this.escapeHtml(title)}</h3>
                <p class="value">${this.escapeHtml(String(value))}</p>
                ${subtitle ? `<span class="subtext">${this.escapeHtml(subtitle)}</span>` : ''}
            </div>
        `;
    },

    // Metric card with P&L coloring
    pnlCard(title, value, subtitle = '') {
        const pnlClass = this.getPnlClass(value);
        return `
            <div class="metric-card">
                <h3>${this.escapeHtml(title)}</h3>
                <p class="value ${pnlClass}">${this.formatCurrency(value)}</p>
                ${subtitle ? `<span class="subtext">${this.escapeHtml(subtitle)}</span>` : ''}
            </div>
        `;
    },

    // Strategy summary card for overview
    strategySummaryCard(strategy, onClick) {
        const pnlClass = this.getPnlClass(strategy.daily_pnl);
        const statusClass = strategy.enabled ? 'enabled' : 'disabled';

        return `
            <div class="strategy-summary-card ${statusClass}" data-strategy-id="${this.escapeHtml(strategy.strategy_id)}">
                <div class="strategy-summary-header">
                    <div class="strategy-summary-info">
                        <span class="strategy-summary-name">${this.escapeHtml(strategy.name)}</span>
                        <span class="strategy-summary-type">${this.escapeHtml(strategy.type)}</span>
                    </div>
                    <span class="strategy-status-badge ${statusClass}">${strategy.enabled ? 'Active' : 'Disabled'}</span>
                </div>
                <div class="strategy-summary-stats">
                    <div class="strategy-summary-stat">
                        <span class="label">Positions</span>
                        <span class="value">${strategy.position_count}</span>
                    </div>
                    <div class="strategy-summary-stat">
                        <span class="label">Daily P&L</span>
                        <span class="value ${pnlClass}">${this.formatCurrency(strategy.daily_pnl)}</span>
                    </div>
                </div>
            </div>
        `;
    },

    // Overview dashboard
    overviewDashboard(summary, strategies, pnl) {
        const strategyCards = strategies.map(s => this.strategySummaryCard(s)).join('');

        return `
            <div class="overview-dashboard">
                <div class="dashboard-section">
                    <h2>Portfolio Summary</h2>
                    <div class="metrics-grid">
                        ${this.pnlCard('Daily Total', pnl?.daily_total || 0)}
                        ${this.pnlCard('Cumulative P&L', pnl?.cumulative_realized || 0)}
                        ${this.metricCard('Total Trades', summary?.total_trades || 0)}
                        ${this.metricCard('Win Rate', summary?.win_rate ? this.formatPercent(summary.win_rate) : '-')}
                        ${this.metricCard('Sharpe Ratio', summary?.sharpe_ratio ? this.formatNumber(summary.sharpe_ratio) : '-', '30-day rolling')}
                        ${this.metricCard('Max Drawdown', summary?.max_drawdown ? `-${this.formatPercent(summary.max_drawdown)}` : '-')}
                    </div>
                </div>

                <div class="dashboard-section">
                    <h2>Strategies</h2>
                    <div class="strategies-summary-grid">
                        ${strategyCards || '<div class="empty-state">No strategies configured</div>'}
                    </div>
                </div>
            </div>
        `;
    },

    // Strategy detail dashboard
    strategyDashboard(strategy, performance, positions, orders) {
        const positionsHtml = this.positionsTable(positions);
        const ordersHtml = this.ordersTable(orders);

        return `
            <div class="strategy-dashboard">
                <div class="strategy-detail-header">
                    <div class="strategy-detail-info">
                        <h2>${this.escapeHtml(strategy.name)}</h2>
                        <span class="strategy-detail-type">${this.escapeHtml(strategy.type)}</span>
                        <span class="strategy-detail-id">${this.escapeHtml(strategy.strategy_id)}</span>
                    </div>
                    <div class="strategy-detail-controls">
                        <label class="toggle-switch">
                            <input type="checkbox" ${strategy.enabled ? 'checked' : ''}
                                   onchange="dashboardController.toggleStrategy('${this.escapeHtml(strategy.strategy_id)}', this.checked)">
                            <span class="toggle-slider"></span>
                        </label>
                        <span class="strategy-status-text">${strategy.enabled ? 'Enabled' : 'Disabled'}</span>
                    </div>
                </div>

                <div class="dashboard-section">
                    <h3>Performance Metrics</h3>
                    <div class="metrics-grid">
                        ${this.pnlCard('Total P&L', performance?.total_pnl || 0)}
                        ${this.pnlCard('Daily P&L', strategy.daily_pnl || 0)}
                        ${this.metricCard('Trade Count', performance?.trade_count || 0)}
                        ${this.metricCard('Win Rate', performance?.win_rate ? this.formatPercent(performance.win_rate) : '-')}
                        ${this.metricCard('Profit Factor', performance?.profit_factor ? this.formatNumber(performance.profit_factor) : '-')}
                        ${this.metricCard('Sharpe Ratio', performance?.sharpe_ratio ? this.formatNumber(performance.sharpe_ratio) : '-')}
                        ${this.metricCard('Sortino Ratio', performance?.sortino_ratio ? this.formatNumber(performance.sortino_ratio) : '-')}
                        ${this.metricCard('Max Drawdown', performance?.max_drawdown ? `-${this.formatPercent(performance.max_drawdown)}` : '-')}
                        ${this.pnlCard('Largest Win', performance?.largest_win || 0)}
                        ${this.pnlCard('Largest Loss', performance?.largest_loss || 0)}
                        ${this.pnlCard('Avg Trade', performance?.avg_trade_pnl || 0)}
                        ${this.metricCard('Avg Duration', performance?.avg_trade_duration_hours ? `${this.formatNumber(performance.avg_trade_duration_hours, 1)}h` : '-')}
                    </div>
                </div>

                <div class="dashboard-section">
                    <h3>Open Positions (${positions?.length || 0})</h3>
                    ${positionsHtml}
                </div>

                <div class="dashboard-section">
                    <h3>Recent Orders</h3>
                    ${ordersHtml}
                </div>

                ${strategy.config ? this.strategyConfigSection(strategy.config) : ''}
            </div>
        `;
    },

    // Strategy config display
    strategyConfigSection(config) {
        if (!config || Object.keys(config).length === 0) return '';

        const configItems = Object.entries(config).map(([key, value]) => `
            <div class="config-item">
                <span class="config-key">${this.escapeHtml(key)}</span>
                <span class="config-value">${this.escapeHtml(JSON.stringify(value))}</span>
            </div>
        `).join('');

        return `
            <div class="dashboard-section">
                <h3>Configuration</h3>
                <div class="config-grid">
                    ${configItems}
                </div>
            </div>
        `;
    },

    // Positions table
    positionsTable(positions) {
        if (!positions || positions.length === 0) {
            return '<div class="empty-state">No open positions</div>';
        }

        const rows = positions.map(pos => {
            const pnlClass = this.getPnlClass(pos.unrealized_pnl);
            const sideClass = pos.side === 'buy' ? 'side-buy' : 'side-sell';

            return `
                <tr>
                    <td>${this.escapeHtml(pos.symbol)}</td>
                    <td class="${sideClass}">${pos.side.toUpperCase()}</td>
                    <td>${this.formatNumber(pos.quantity, 0)}</td>
                    <td>$${this.formatNumber(pos.avg_entry_price)}</td>
                    <td>${pos.current_price ? '$' + this.formatNumber(pos.current_price) : '-'}</td>
                    <td class="${pnlClass}">${pos.unrealized_pnl ? this.formatCurrency(pos.unrealized_pnl) : '-'}</td>
                </tr>
            `;
        }).join('');

        return `
            <table class="dashboard-table">
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Side</th>
                        <th>Qty</th>
                        <th>Avg Price</th>
                        <th>Current</th>
                        <th>Unrealized P&L</th>
                    </tr>
                </thead>
                <tbody>
                    ${rows}
                </tbody>
            </table>
        `;
    },

    // Orders table
    ordersTable(orders) {
        if (!orders || orders.length === 0) {
            return '<div class="empty-state">No recent orders</div>';
        }

        const rows = orders.map(order => {
            const sideClass = order.side === 'buy' ? 'side-buy' : 'side-sell';
            const statusClass = `status-${order.status}`;

            return `
                <tr>
                    <td>${this.formatDateTime(order.created_at)}</td>
                    <td>${this.escapeHtml(order.symbol)}</td>
                    <td class="${sideClass}">${order.side.toUpperCase()}</td>
                    <td>${this.formatNumber(order.quantity, 0)}</td>
                    <td>${this.escapeHtml(order.order_type)}</td>
                    <td class="${statusClass}">${this.escapeHtml(order.status)}</td>
                    <td>${order.avg_fill_price ? '$' + this.formatNumber(order.avg_fill_price) : '-'}</td>
                </tr>
            `;
        }).join('');

        return `
            <table class="dashboard-table">
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Symbol</th>
                        <th>Side</th>
                        <th>Qty</th>
                        <th>Type</th>
                        <th>Status</th>
                        <th>Fill Price</th>
                    </tr>
                </thead>
                <tbody>
                    ${rows}
                </tbody>
            </table>
        `;
    },

    // Navigation tabs
    navigationTabs(strategies, activeView) {
        const overviewActive = activeView === 'overview' ? 'active' : '';

        const strategyTabs = strategies.map(s => {
            const active = activeView === s.strategy_id ? 'active' : '';
            const statusClass = s.enabled ? '' : 'disabled-tab';
            return `
                <button class="nav-tab ${active} ${statusClass}"
                        data-view="${this.escapeHtml(s.strategy_id)}"
                        onclick="dashboardController.showView('${this.escapeHtml(s.strategy_id)}')">
                    ${this.escapeHtml(s.name)}
                </button>
            `;
        }).join('');

        return `
            <button class="nav-tab ${overviewActive}" data-view="overview"
                    onclick="dashboardController.showView('overview')">
                Overview
            </button>
            ${strategyTabs}
        `;
    },

    // Loading state
    loadingState() {
        return `
            <div class="loading-state">
                <div class="loading-spinner"></div>
                <span>Loading...</span>
            </div>
        `;
    },

    // Error state
    errorState(message) {
        return `
            <div class="error-state">
                <span class="error-icon">!</span>
                <span>${this.escapeHtml(message)}</span>
            </div>
        `;
    },
};

// Export for use in other modules
window.Templates = Templates;
