// Dashboard view controller
// Manages navigation, view state, and data loading

class DashboardController {
    constructor() {
        this.currentView = 'overview';
        this.strategies = [];
        this.cache = new Map();
        this.cacheTimeout = 30000; // 30 seconds
        this.refreshInterval = null;
        this.elements = {
            nav: null,
            content: null,
        };
    }

    async initialize() {
        // Get DOM elements
        this.elements.nav = document.getElementById('dashboard-nav');
        this.elements.content = document.getElementById('dashboard-content');

        if (!this.elements.nav || !this.elements.content) {
            console.error('Dashboard elements not found');
            return;
        }

        // Show loading state
        this.elements.content.innerHTML = Templates.loadingState();

        // Load strategies and render navigation
        await this.loadStrategies();
        this.renderNavigation();

        // Show initial view
        this.showView('overview');

        // Set up auto-refresh
        this.startAutoRefresh();
    }

    startAutoRefresh() {
        // Refresh current view every 10 seconds
        this.refreshInterval = setInterval(() => {
            this.refreshCurrentView();
        }, 10000);
    }

    stopAutoRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
    }

    async loadStrategies() {
        try {
            const response = await fetch('/api/strategies');
            if (response.ok) {
                this.strategies = await response.json();
            } else {
                console.error('Failed to load strategies:', response.status);
                this.strategies = [];
            }
        } catch (e) {
            console.error('Failed to load strategies:', e);
            this.strategies = [];
        }
    }

    renderNavigation() {
        if (!this.elements.nav) return;
        this.elements.nav.innerHTML = Templates.navigationTabs(this.strategies, this.currentView);
    }

    updateNavigation() {
        // Update active state without full re-render
        const tabs = this.elements.nav.querySelectorAll('.nav-tab');
        tabs.forEach(tab => {
            const view = tab.dataset.view;
            if (view === this.currentView) {
                tab.classList.add('active');
            } else {
                tab.classList.remove('active');
            }
        });
    }

    async showView(viewId) {
        this.currentView = viewId;
        this.updateNavigation();

        // Show loading state
        this.elements.content.innerHTML = Templates.loadingState();

        if (viewId === 'overview') {
            await this.renderOverview();
        } else {
            await this.renderStrategyDashboard(viewId);
        }
    }

    async refreshCurrentView() {
        // Clear cache for current view
        this.cache.delete(this.currentView);

        if (this.currentView === 'overview') {
            await this.renderOverview();
        } else {
            await this.renderStrategyDashboard(this.currentView);
        }
    }

    getCached(key) {
        const cached = this.cache.get(key);
        if (cached && Date.now() - cached.timestamp < this.cacheTimeout) {
            return cached.data;
        }
        return null;
    }

    setCache(key, data) {
        this.cache.set(key, {
            data,
            timestamp: Date.now(),
        });
    }

    async fetchOverviewData() {
        const cacheKey = 'overview';
        const cached = this.getCached(cacheKey);
        if (cached) return cached;

        try {
            // Fetch data in parallel
            const [strategiesRes, summaryRes, pnlRes] = await Promise.all([
                fetch('/api/strategies'),
                fetch('/api/analytics/summary'),
                fetch('/api/pnl/summary'),
            ]);

            const data = {
                strategies: strategiesRes.ok ? await strategiesRes.json() : [],
                summary: summaryRes.ok ? await summaryRes.json() : null,
                pnl: pnlRes.ok ? await pnlRes.json() : null,
            };

            // Update local strategies list
            if (data.strategies.length > 0) {
                this.strategies = data.strategies;
            }

            this.setCache(cacheKey, data);
            return data;
        } catch (e) {
            console.error('Failed to fetch overview data:', e);
            return { strategies: this.strategies, summary: null, pnl: null };
        }
    }

    async fetchStrategyData(strategyId) {
        const cacheKey = `strategy:${strategyId}`;
        const cached = this.getCached(cacheKey);
        if (cached) return cached;

        try {
            // Fetch strategy detail and performance in parallel
            const [detailRes, perfRes] = await Promise.all([
                fetch(`/api/strategies/${strategyId}`),
                fetch(`/api/strategies/${strategyId}/performance`),
            ]);

            if (!detailRes.ok) {
                throw new Error(`Strategy not found: ${strategyId}`);
            }

            const data = {
                strategy: await detailRes.json(),
                performance: perfRes.ok ? await perfRes.json() : null,
            };

            // Extract positions and orders from detail response
            data.positions = data.strategy.positions || [];
            data.orders = data.strategy.recent_orders || [];

            this.setCache(cacheKey, data);
            return data;
        } catch (e) {
            console.error('Failed to fetch strategy data:', e);
            throw e;
        }
    }

    async renderOverview() {
        try {
            const data = await this.fetchOverviewData();
            const html = Templates.overviewDashboard(data.summary, data.strategies, data.pnl);
            this.elements.content.innerHTML = html;

            // Add click handlers for strategy cards
            this.setupStrategyCardClicks();
        } catch (e) {
            console.error('Failed to render overview:', e);
            this.elements.content.innerHTML = Templates.errorState('Failed to load overview data');
        }
    }

    setupStrategyCardClicks() {
        const cards = this.elements.content.querySelectorAll('.strategy-summary-card');
        cards.forEach(card => {
            card.addEventListener('click', () => {
                const strategyId = card.dataset.strategyId;
                if (strategyId) {
                    this.showView(strategyId);
                }
            });
        });
    }

    async renderStrategyDashboard(strategyId) {
        try {
            const data = await this.fetchStrategyData(strategyId);
            const html = Templates.strategyDashboard(
                data.strategy,
                data.performance,
                data.positions,
                data.orders
            );
            this.elements.content.innerHTML = html;
        } catch (e) {
            console.error('Failed to render strategy dashboard:', e);
            this.elements.content.innerHTML = Templates.errorState(`Failed to load strategy: ${strategyId}`);
        }
    }

    async toggleStrategy(strategyId, enabled) {
        try {
            const action = enabled ? 'enable' : 'disable';
            const response = await fetch(`/api/strategies/${strategyId}/${action}`, {
                method: 'POST',
            });

            if (response.ok) {
                // Clear cache and refresh
                this.cache.delete('overview');
                this.cache.delete(`strategy:${strategyId}`);

                // Update local state
                const updated = await response.json();
                const strategy = this.strategies.find(s => s.strategy_id === strategyId);
                if (strategy) {
                    strategy.enabled = updated.enabled;
                }

                // Re-render navigation to update disabled tabs
                this.renderNavigation();

                // Refresh current view if viewing this strategy
                if (this.currentView === strategyId) {
                    await this.refreshCurrentView();
                }
            } else {
                console.error('Failed to toggle strategy:', await response.text());
                // Revert checkbox state
                await this.refreshCurrentView();
            }
        } catch (e) {
            console.error('Failed to toggle strategy:', e);
            // Revert checkbox state
            await this.refreshCurrentView();
        }
    }
}

// Export controller instance
window.dashboardController = new DashboardController();
