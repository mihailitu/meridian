# Iteration 6: Web Dashboard

## Goal
Build a real-time monitoring web UI for positions, P&L, orders, and strategy performance.

## Definition of Done
```
Browser at http://localhost:8000 shows:
- Current positions with real-time P&L updates
- Order history with fill details
- Daily/cumulative P&L chart
- Strategy status and performance metrics
- Auto-refreshing via WebSocket
```

## Architecture

```
                                    +------------------+
                                    |   Browser (UI)   |
                                    +--------+---------+
                                             |
                                    WebSocket + REST
                                             |
                                    +--------v---------+
                                    |    FastAPI App   |
                                    +--------+---------+
                                             |
              +------------------------------+------------------------------+
              |                              |                              |
    +---------v----------+       +-----------v-----------+       +----------v---------+
    |  PositionRepository |       |   OrderRepository    |       |   BarRepository    |
    +--------------------+       +-----------------------+       +--------------------+
              |                              |                              |
              +------------------------------+------------------------------+
                                             |
                                    +--------v---------+
                                    |   TimescaleDB    |
                                    +------------------+
```

## Files to Create/Modify

### New Files
```
src/axtrade/api/
    __init__.py
    app.py              # FastAPI application factory
    routes/
        __init__.py
        positions.py    # Position endpoints
        orders.py       # Order endpoints
        pnl.py          # P&L endpoints
        ws.py           # WebSocket handler
    schemas.py          # Pydantic response models
    dependencies.py     # Shared dependencies (db pool)

src/axtrade/web/
    static/
        index.html      # Single page dashboard
        styles.css      # Styling
        app.js          # Frontend logic + WebSocket client

tests/unit/test_api.py  # API endpoint tests
```

### Modify Existing
```
src/axtrade/oms/repository.py   # Add methods for API queries
pyproject.toml                   # Add fastapi, uvicorn dependencies
Makefile                         # Add run-api command
config/default.yaml              # Add api section
src/axtrade/common/config.py     # Add APIConfig
```

## Implementation Details

### 1. Config (config.py + default.yaml)
```python
@dataclass
class APIConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
```

```yaml
api:
  host: "0.0.0.0"
  port: 8000
  cors_origins:
    - "http://localhost:3000"
    - "http://localhost:8000"
```

### 2. Pydantic Schemas (api/schemas.py)
```python
class PositionResponse(BaseModel):
    symbol: str
    side: str
    quantity: Decimal
    avg_entry_price: Decimal
    current_price: Decimal | None
    unrealized_pnl: Decimal | None
    strategy_id: str

class OrderResponse(BaseModel):
    id: str
    symbol: str
    side: str
    quantity: Decimal
    order_type: str
    status: str
    limit_price: Decimal | None
    filled_quantity: Decimal
    avg_fill_price: Decimal | None
    created_at: datetime
    updated_at: datetime

class FillResponse(BaseModel):
    id: str
    order_id: str
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    commission: Decimal
    filled_at: datetime

class PnLSummary(BaseModel):
    daily_realized: Decimal
    daily_unrealized: Decimal
    daily_total: Decimal
    cumulative_realized: Decimal

class StrategyStatus(BaseModel):
    strategy_id: str
    name: str
    enabled: bool
    position_count: int
    daily_pnl: Decimal
```

### 3. REST Endpoints (api/routes/)

**positions.py**
```python
@router.get("/positions", response_model=list[PositionResponse])
async def get_positions(strategy_id: str | None = None)

@router.get("/positions/{symbol}", response_model=PositionResponse)
async def get_position(symbol: str, strategy_id: str | None = None)
```

**orders.py**
```python
@router.get("/orders", response_model=list[OrderResponse])
async def get_orders(
    strategy_id: str | None = None,
    status: str | None = None,
    limit: int = 50
)

@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(order_id: str)

@router.get("/orders/{order_id}/fills", response_model=list[FillResponse])
async def get_order_fills(order_id: str)
```

**pnl.py**
```python
@router.get("/pnl/summary", response_model=PnLSummary)
async def get_pnl_summary(strategy_id: str | None = None)

@router.get("/pnl/history")
async def get_pnl_history(
    days: int = 30,
    strategy_id: str | None = None
) -> list[dict]
```

### 4. WebSocket Handler (api/routes/ws.py)
```python
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket)
    async def disconnect(self, websocket: WebSocket)
    async def broadcast(self, message: dict)

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Send updates every second
            positions = await get_current_positions()
            pnl = await get_pnl_summary()
            await websocket.send_json({
                "type": "update",
                "positions": positions,
                "pnl": pnl,
                "timestamp": datetime.utcnow().isoformat()
            })
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
```

### 5. FastAPI App (api/app.py)
```python
def create_app(config: Config) -> FastAPI:
    app = FastAPI(title="axtrade API", version="1.0.0")

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.api.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Static files
    app.mount("/static", StaticFiles(directory="src/axtrade/web/static"))

    # Routes
    app.include_router(positions.router, prefix="/api", tags=["positions"])
    app.include_router(orders.router, prefix="/api", tags=["orders"])
    app.include_router(pnl.router, prefix="/api", tags=["pnl"])
    app.include_router(ws.router, tags=["websocket"])

    # Root serves dashboard
    @app.get("/")
    async def root():
        return FileResponse("src/axtrade/web/static/index.html")

    return app
```

### 6. Frontend (web/static/)

**index.html** - Simple dashboard layout:
- Header with logo and connection status
- Positions table with live P&L
- Orders table (recent 20)
- P&L summary cards
- Strategy status indicators

**app.js** - Vanilla JS with:
- WebSocket connection with auto-reconnect
- DOM updates on message receive
- Number formatting for currency
- Color coding for profit/loss

**styles.css** - Clean, minimal styling:
- Dark theme (trading aesthetic)
- Tables with hover states
- Green/red for profit/loss
- Responsive layout

### 7. Repository Extensions (oms/repository.py)

```python
# PositionRepository additions
async def get_all_positions(self, strategy_id: str | None = None) -> list[Position]
async def get_positions_with_pnl(self) -> list[dict]

# OrderRepository additions
async def get_recent_orders(self, limit: int, strategy_id: str | None = None) -> list[Order]
async def get_orders_by_status(self, status: str) -> list[Order]

# New: PnLRepository
class PnLRepository:
    async def get_daily_realized_pnl(self, strategy_id: str | None = None) -> Decimal
    async def get_pnl_history(self, days: int) -> list[dict]
```

## Implementation Order

1. **Dependencies**: Add fastapi, uvicorn, python-multipart to pyproject.toml
2. **Config**: Add APIConfig to config.py, update default.yaml
3. **Schemas**: Create api/schemas.py with Pydantic models
4. **Repository Extensions**: Add query methods to repositories
5. **REST Routes**: Implement positions, orders, pnl endpoints
6. **WebSocket**: Implement real-time updates
7. **App Factory**: Create FastAPI app with all routes
8. **Frontend**: Build static HTML/CSS/JS dashboard
9. **Tests**: API endpoint tests
10. **Makefile**: Add run-api command

## Verification Steps

1. Install dependencies: `make dev`
2. Start infrastructure: `make infra`
3. Run strategy runner (generates some data): `make run-strategy`
4. Start API: `make run-api`
5. Open browser: http://localhost:8000
6. Verify dashboard loads with positions/orders
7. Run tests: `pytest tests/unit/test_api.py -v`

## Key Design Decisions

1. **FastAPI over Flask**: Native async support, automatic OpenAPI docs, Pydantic integration
2. **Vanilla JS over React**: Simpler for v1, no build step, sufficient for dashboard
3. **WebSocket for real-time**: More efficient than polling, native browser support
4. **Single HTML file**: No complex frontend build, easy to modify
5. **Dark theme**: Standard for trading applications, easier on eyes
