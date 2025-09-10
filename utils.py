from urllib.parse import ParseResult, urlparse, urlunparse
import psycopg
from psycopg_pool import ConnectionPool


def ensure_database_exists(dsn: str):
    """
    If the target database in DSN doesn't exist, connect to 'postgres' DB and create it.
    """
    parsed = urlparse(dsn)
    target_db = parsed.path.lstrip("/") or "postgres"

    # Try connecting to the target DB
    try:
        with psycopg.connect(dsn) as _test:
            return
    except Exception:
        pass

    # Build maintenance DSN (same host/user/pass, DB='postgres')
    maint_parsed = ParseResult(
        scheme=parsed.scheme,
        netloc=parsed.netloc,
        path="/postgres",
        params=parsed.params,
        query=parsed.query,
        fragment=parsed.fragment
    )
    maint_dsn = urlunparse(maint_parsed)

    with psycopg.connect(maint_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (target_db,))
            exists = cur.fetchone() is not None
            if not exists:
                cur.execute(f'CREATE DATABASE "{target_db}";')

def ensure_schema(pool: ConnectionPool):
    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS tourism_records (
        id SERIAL PRIMARY KEY,
        date DATE NOT NULL,
        province VARCHAR(50) NOT NULL,
        visitors INT NOT NULL,
        avg_stay_days DOUBLE PRECISION NOT NULL,
        revenue_usd DOUBLE PRECISION NOT NULL
    );
    """
    CREATE_INDEXES_SQL = [
        "CREATE INDEX IF NOT EXISTS idx_tourism_records_date ON tourism_records(date);",
        "CREATE INDEX IF NOT EXISTS idx_tourism_records_province ON tourism_records(province);"
    ]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
            for stmt in CREATE_INDEXES_SQL:
                cur.execute(stmt)

