# main.py
from typing import Optional
from fastapi import FastAPI, Query
from fastapi.concurrency import asynccontextmanager
from fastapi.responses import JSONResponse
import pandas as pd
import numpy as np
from datetime import datetime, date
import os
import json
import uvicorn
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from dotenv import load_dotenv
from utils import ensure_database_exists, ensure_schema

load_dotenv()
# --- Config ---
POSTGRES_URL = os.environ.get(
    "POSTGRES_URL"
)
print("Using POSTGRES_URL:", POSTGRES_URL)
OUTPUT_DIR = "./output"
os.makedirs(OUTPUT_DIR, exist_ok=True)
RESULTS_FILE = os.path.join(OUTPUT_DIR, "tourism_analysis.json")

# --- Connection Pool ---
pool = ConnectionPool(
    POSTGRES_URL,
    min_size=1,
    max_size=5,
    kwargs={"autocommit": True}  # autocommit simplifies DDL/DML here
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    
    # Make sure DB exists
    ensure_database_exists(POSTGRES_URL)

    # Create pool (sync connections, autocommit simplifies DDL/DML here)
    pool = ConnectionPool(POSTGRES_URL, min_size=1, max_size=5, kwargs={"autocommit": True})
    app.state.pool = pool

    # Ensure schema
    ensure_schema(pool)

    try:
        yield
    finally:
        # Close pool on shutdown
        pool.close()
        pool.wait_closed()

app = FastAPI(title="Rwanda Tourism Analytics (PostgreSQL, psycopg)", lifespan=lifespan)

def ensure_table_exists():
    """
    Ensure the tourism_records table exists. This is a fallback in case
    the lifespan function hasn't run yet or there are timing issues.
    """
    try:
        ensure_database_exists(POSTGRES_URL)
        ensure_schema(pool)
    except Exception as e:
        print(f"Warning: Could not ensure table exists: {e}")

def generate_tourism_data(rows: int = 100) -> pd.DataFrame:
    dates = pd.date_range(date(2024, 1, 1), periods=rows, freq="D")
    df = pd.DataFrame({
        "date": dates.date,  # Python date objects -> maps well to DATE
        "province": np.random.choice(
            ["Kigali", "Eastern", "Western", "Northern", "Southern"], len(dates)
        ),
        "visitors": np.random.poisson(1000, len(dates)),
        "avg_stay_days": np.random.normal(3.5, 1.2, len(dates)).round(2),
        "revenue_usd": np.random.exponential(500, len(dates)).round(2),
    })
    return df

def truncate_and_insert(df: pd.DataFrame):
    ensure_table_exists()  # Ensure table exists before operations
    
    TRUNCATE_SQL = "TRUNCATE TABLE tourism_records;"
    INSERT_SQL = """
        INSERT INTO tourism_records (date, province, visitors, avg_stay_days, revenue_usd)
        VALUES (%s, %s, %s, %s, %s);
    """
    rows = list(
        zip(
            df["date"].tolist(),
            df["province"].tolist(),
            df["visitors"].astype(int).tolist(),
            df["avg_stay_days"].astype(float).tolist(),
            df["revenue_usd"].astype(float).tolist(),
        )
    )
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(TRUNCATE_SQL)
            cur.executemany(INSERT_SQL, rows)

def compute_analytics() -> dict:
    ensure_table_exists()  # Ensure table exists before operations
    
    ANALYTICS_SQL = """
    WITH sums AS (
      SELECT
        SUM(visitors)::BIGINT AS total_visitors,
        AVG(visitors)::FLOAT AS avg_daily_visitors,
        AVG(avg_stay_days)::FLOAT AS avg_stay_days,
        SUM(revenue_usd)::FLOAT AS total_revenue_usd
      FROM tourism_records
    ),
    top AS (
      SELECT province
      FROM tourism_records
      GROUP BY province
      ORDER BY SUM(visitors) DESC
      LIMIT 1
    )
    SELECT
      (SELECT total_visitors FROM sums) AS total_visitors,
      (SELECT avg_daily_visitors FROM sums) AS avg_daily_visitors,
      (SELECT avg_stay_days FROM sums) AS avg_stay_days,
      (SELECT total_revenue_usd FROM sums) AS total_revenue_usd,
      (SELECT province FROM top) AS top_province;
    """
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(ANALYTICS_SQL)
            row = cur.fetchone()
    if row is None or row["total_visitors"] is None:
        return {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "total_visitors": 0,
            "avg_daily_visitors": 0.0,
            "top_province": None,
            "avg_stay_days": 0.0,
            "total_revenue_usd": 0.0,
        }
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total_visitors": int(row["total_visitors"]),
        "avg_daily_visitors": float(row["avg_daily_visitors"]),
        "top_province": row["top_province"],
        "avg_stay_days": float(row["avg_stay_days"]),
        "total_revenue_usd": float(row["total_revenue_usd"]),
    }


@app.post("/generate_random_data")
def generate_random_data_endpoint(rows: int = Query(100, ge=1, le=100000)):
    """
    Generate synthetic tourism dataset (rows=N) and insert into database.
    """
    df = generate_tourism_data(rows)
    truncate_and_insert(df)
    
    return JSONResponse(content={
        "message": f"Successfully generated and inserted {rows} rows of tourism data",
        "rows_inserted": len(df),
        "generated_at": datetime.utcnow().isoformat() + "Z"
    })

@app.get("/analyze")
def analyze():
    """
    Analyze existing data in the database and return analytics summary.
    """
    results = compute_analytics()

    # Optional: snapshot to file
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    return JSONResponse(content=results)

@app.get("/data")
def get_data(
    province: Optional[str] = Query(None, description="Filter by province"),
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    limit: int = Query(1000, ge=1, le=100000),
    offset: int = Query(0, ge=0),
):
    """
    Fetch records from Postgres with optional filters and pagination.
    Available at both /data and /get_data endpoints.
    """
    ensure_table_exists()  # Ensure table exists before operations
    
    clauses = []
    params = []

    if province:
        clauses.append("province = %s")
        params.append(province)
    if start_date:
        clauses.append("date >= %s")
        params.append(start_date)
    if end_date:
        clauses.append("date <= %s")
        params.append(end_date)

    where_sql = ""
    if clauses:
        where_sql = "WHERE " + " AND ".join(clauses)

    sql = (
        "SELECT id, date, province, visitors, avg_stay_days, revenue_usd "
        f"FROM tourism_records {where_sql} "
        "ORDER BY date ASC, id ASC LIMIT %s OFFSET %s;"
    )
    params.extend([limit, offset])

    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    # ISO-ify dates
    for r in rows:
        if isinstance(r["date"], (datetime, date)):
            r["date"] = r["date"].isoformat()

    return JSONResponse(content=rows)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
