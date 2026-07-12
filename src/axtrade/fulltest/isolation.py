"""Infrastructure isolation for backtest -- separate DB and Redis."""

from pathlib import Path

import asyncpg
import redis.asyncio as redis

from axtrade.common import DatabaseConfig, RedisConfig, get_logger

logger = get_logger("fulltest.isolation")

# SQL scripts relative to project root
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_INIT_SQL = _PROJECT_ROOT / "scripts" / "init-db.sql"
_MIGRATIONS_DIR = _PROJECT_ROOT / "scripts" / "migrations"


class BacktestInfrastructure:
    """Manages isolated infrastructure for backtests.

    Creates a separate TimescaleDB database and uses a separate Redis DB
    to avoid polluting production data.
    """

    def __init__(
        self,
        db_config: DatabaseConfig,
        redis_config: RedisConfig,
        backtest_db_name: str = "axtrade_backtest",
    ):
        self._db_config = db_config
        self._redis_config = redis_config
        self._backtest_db_name = backtest_db_name

    async def setup(self) -> None:
        """Set up isolated infrastructure.

        Creates the backtest database (if not exists), runs init SQL and
        migrations, and flushes the backtest Redis DB.
        """
        await self._setup_database()
        await self._flush_redis()

    async def teardown(self) -> None:
        """Clean up Redis. Database is kept for inspection."""
        await self._flush_redis()
        logger.info(
            "Teardown complete. Database kept for inspection",
            database=self._backtest_db_name,
        )

    async def _setup_database(self) -> None:
        """Create backtest database and run schema."""
        # Connect to default database to create backtest DB
        conn = await asyncpg.connect(
            host=self._db_config.host,
            port=self._db_config.port,
            database=self._db_config.database,
            user=self._db_config.user,
            password=self._db_config.password,
        )

        try:
            # Check if database exists
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1",
                self._backtest_db_name,
            )

            if not exists:
                # Cannot run CREATE DATABASE in a transaction
                await conn.execute(
                    f'CREATE DATABASE "{self._backtest_db_name}"'
                )
                logger.info("Created backtest database", name=self._backtest_db_name)
            else:
                logger.info("Backtest database exists", name=self._backtest_db_name)
        finally:
            await conn.close()

        # Connect to backtest DB and run schema
        bt_conn = await asyncpg.connect(
            host=self._db_config.host,
            port=self._db_config.port,
            database=self._backtest_db_name,
            user=self._db_config.user,
            password=self._db_config.password,
        )

        try:
            await self._run_schema(bt_conn)
            await self._truncate_data(bt_conn)
        finally:
            await bt_conn.close()

    async def _run_schema(self, conn: asyncpg.Connection) -> None:
        """Run init SQL and migrations against the backtest database."""
        # Check if tables already exist
        table_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'bars')"
        )

        if not table_exists:
            if _INIT_SQL.exists():
                sql = _INIT_SQL.read_text()
                await conn.execute(sql)
                logger.info("Ran init-db.sql")
            else:
                logger.warning("init-db.sql not found", path=str(_INIT_SQL))

        # Run migrations in order
        if _MIGRATIONS_DIR.exists():
            migration_files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
            for migration in migration_files:
                migration_name = migration.stem

                # Track applied migrations
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS _migrations (
                        name VARCHAR(255) PRIMARY KEY,
                        applied_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)

                applied = await conn.fetchval(
                    "SELECT 1 FROM _migrations WHERE name = $1",
                    migration_name,
                )

                if not applied:
                    try:
                        sql = migration.read_text()
                        await conn.execute(sql)
                        await conn.execute(
                            "INSERT INTO _migrations (name) VALUES ($1)",
                            migration_name,
                        )
                        logger.info("Applied migration", name=migration_name)
                    except Exception as e:
                        logger.warning(
                            "Migration failed (may already be applied)",
                            name=migration_name,
                            error=str(e),
                        )

    async def _truncate_data(self, conn: asyncpg.Connection) -> None:
        """Truncate data tables so each backtest starts clean."""
        tables = ["fills", "orders", "positions", "bars", "discovered_symbols"]
        for table in tables:
            try:
                await conn.execute(f"TRUNCATE {table} CASCADE")
            except Exception:
                pass  # Table may not exist yet
        logger.info("Truncated data tables for clean backtest")

    async def _flush_redis(self) -> None:
        """Flush the backtest Redis DB."""
        client = redis.Redis(
            host=self._redis_config.host,
            port=self._redis_config.port,
            db=self._redis_config.db,
        )
        try:
            await client.flushdb()
            logger.info("Flushed Redis", db=self._redis_config.db)
        finally:
            await client.aclose()
