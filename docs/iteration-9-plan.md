# Iteration 9: System Health Monitoring and Alerts

## Goal
Monitor system health with alerts displayed as logs/events in the frontend. Architecture supports future alert channels (email, SMS, Slack).

## Scope
- System health checks (Redis, Database, Broker, Data feeds)
- Alert types and severity levels
- Extensible alert channel architecture
- LogChannel implementation (logs + in-memory event store)
- REST API for alerts and health status
- WebSocket broadcast for real-time alerts
- Frontend alerts panel and health indicators

## Architecture

```
+----------------+     +------------------+     +------------------+
| HealthMonitor  | --> | AlertService     | --> | AlertChannel     |
| - Redis check  |     | - Rule matching  |     | (abstract)       |
| - DB check     |     | - Deduplication  |     |   |              |
| - Broker check |     | - Rate limiting  |     |   +-> LogChannel |
| - Heartbeats   |     +------------------+     |   +-> (future)    |
+----------------+              |               +------------------+
                                v
                    +----------------------+
                    | AlertRepository      |
                    | (in-memory + persist)|
                    +----------------------+
                                |
                    +-----------+-----------+
                    |                       |
              REST API               WebSocket
           GET /api/alerts        broadcast on new
           GET /api/health
```

## Alert Types

```python
class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

class AlertCategory(Enum):
    SYSTEM = "system"          # Infrastructure health
    TRADING = "trading"        # Order/position events
    RISK = "risk"              # Risk limit breaches
    DATA = "data"              # Data feed issues
```

## Files to Create

```
src/axtrade/alerts/
    __init__.py
    types.py              # Alert, AlertSeverity, AlertCategory
    channels.py           # AlertChannel ABC, LogChannel
    repository.py         # AlertRepository (in-memory with rotation)
    service.py            # AlertService (rule matching, dispatch)
    health.py             # HealthMonitor, HealthStatus
    rules.py              # AlertRule, default rules

src/axtrade/api/routes/alerts.py   # GET /api/alerts
src/axtrade/api/routes/health.py   # GET /api/health
```

## Files to Modify

```
src/axtrade/api/app.py            # Register new routes
src/axtrade/api/routes/ws.py      # Broadcast alerts via WebSocket
src/axtrade/web/static/index.html # Alerts panel, health indicators
src/axtrade/web/static/app.js     # Handle alert events
src/axtrade/web/static/styles.css # Alert styling
```

## Implementation Details

### 1. Alert Types (types.py)

```python
@dataclass
class Alert:
    id: str
    timestamp: datetime
    severity: AlertSeverity
    category: AlertCategory
    title: str
    message: str
    source: str              # Component that raised alert
    metadata: dict = field(default_factory=dict)
    acknowledged: bool = False
```

### 2. Alert Channels (channels.py)

```python
class AlertChannel(ABC):
    @abstractmethod
    async def send(self, alert: Alert) -> bool: ...

class LogChannel(AlertChannel):
    """Logs alerts and stores in repository for frontend."""
    def __init__(self, repository: AlertRepository):
        self.repository = repository

    async def send(self, alert: Alert) -> bool:
        # Log with structlog
        # Store in repository
        # Return True
```

### 3. Alert Repository (repository.py)

```python
class AlertRepository:
    """In-memory alert storage with rotation."""
    def __init__(self, max_alerts: int = 1000):
        self._alerts: deque[Alert] = deque(maxlen=max_alerts)

    def add(self, alert: Alert) -> None
    def get_recent(self, limit: int = 50) -> list[Alert]
    def get_by_severity(self, severity: AlertSeverity) -> list[Alert]
    def acknowledge(self, alert_id: str) -> bool
    def get_unacknowledged_count(self) -> int
```

### 4. Health Monitor (health.py)

```python
@dataclass
class ComponentHealth:
    name: str
    status: Literal["healthy", "degraded", "unhealthy"]
    latency_ms: float | None = None
    last_check: datetime = None
    error: str | None = None

@dataclass
class SystemHealth:
    overall: Literal["healthy", "degraded", "unhealthy"]
    components: dict[str, ComponentHealth]
    timestamp: datetime

class HealthMonitor:
    def __init__(self, alert_service: AlertService):
        self._components: dict[str, ComponentHealth] = {}
        self._alert_service = alert_service

    async def check_redis(self, redis: Redis) -> ComponentHealth
    async def check_database(self, pool: DatabasePool) -> ComponentHealth
    async def check_broker(self, broker: BrokerProtocol) -> ComponentHealth

    def record_heartbeat(self, component: str) -> None
    def check_heartbeats(self, timeout_seconds: float = 30) -> None

    def get_health(self) -> SystemHealth
```

### 5. Alert Service (service.py)

```python
class AlertService:
    def __init__(self, channels: list[AlertChannel]):
        self._channels = channels
        self._recent_alerts: dict[str, datetime] = {}  # For deduplication

    async def send(
        self,
        severity: AlertSeverity,
        category: AlertCategory,
        title: str,
        message: str,
        source: str,
        metadata: dict | None = None,
        dedupe_key: str | None = None,
        dedupe_seconds: int = 60,
    ) -> Alert | None:
        # Check deduplication
        # Create Alert
        # Dispatch to all channels
        # Return alert or None if deduped

    # Convenience methods
    async def info(self, title: str, message: str, **kwargs) -> Alert | None
    async def warning(self, title: str, message: str, **kwargs) -> Alert | None
    async def error(self, title: str, message: str, **kwargs) -> Alert | None
    async def critical(self, title: str, message: str, **kwargs) -> Alert | None
```

### 6. API Endpoints

```python
# GET /api/alerts?limit=50&severity=error&acknowledged=false
@router.get("/alerts")
async def get_alerts(
    limit: int = 50,
    severity: AlertSeverity | None = None,
    acknowledged: bool | None = None,
) -> list[AlertResponse]

# POST /api/alerts/{alert_id}/acknowledge
@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str) -> dict

# GET /api/health
@router.get("/health")
async def get_health() -> SystemHealthResponse
```

### 7. WebSocket Updates

Add alert broadcasts to existing WebSocket:
```python
# In ws.py, when alert is created:
{
    "type": "alert",
    "data": {
        "id": "...",
        "severity": "error",
        "category": "system",
        "title": "Database Connection Lost",
        "message": "...",
        "timestamp": "..."
    }
}
```

### 8. Frontend Updates

**Alerts Panel**:
- Collapsible alerts section at top of dashboard
- Color-coded by severity (info=blue, warning=yellow, error=red, critical=purple)
- Click to acknowledge
- Badge showing unacknowledged count

**Health Indicators**:
- Status dots in header (green/yellow/red)
- Hover for component details
- Click for full health panel

## Default Alert Rules

1. **System Health**:
   - Redis disconnected -> CRITICAL
   - Database disconnected -> CRITICAL
   - Broker disconnected -> ERROR
   - Component heartbeat missed -> WARNING
   - High latency (>1s) -> WARNING

2. **Trading Events** (for future integration):
   - Order filled -> INFO
   - Order rejected -> WARNING
   - Stop loss hit -> WARNING
   - Daily loss limit approaching -> WARNING
   - Daily loss limit hit -> ERROR

3. **Risk Events** (for future integration):
   - Position limit approaching -> WARNING
   - Portfolio heat high -> WARNING

## Implementation Order

1. Alert types and repository
2. Alert channels (LogChannel)
3. Alert service with deduplication
4. Health monitor with checks
5. API endpoints for alerts and health
6. WebSocket alert broadcasts
7. Frontend alerts panel
8. Frontend health indicators
9. Tests

## Verification

1. Start services: `make infra && make run-api`
2. Check health endpoint: `curl http://localhost:8000/api/health`
3. Simulate unhealthy state (stop Redis)
4. Verify alert appears in: `curl http://localhost:8000/api/alerts`
5. Check frontend shows alert and health status
6. Run tests: `pytest tests/unit/test_alerts.py tests/unit/test_health.py -v`
