# main.py
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import pandas as pd
import numpy as np
from datetime import datetime
import os
import json

import uvicorn

app = FastAPI(title="Rwanda Tourism Analytics")

OUTPUT_DIR = "./output"
RESULTS_FILE = os.path.join(OUTPUT_DIR, "tourism_analysis.json")
DATA_FILE = os.path.join(OUTPUT_DIR, "tourism_data.json")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def generate_tourism_data():
    # Create synthetic dataset
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    data = {
        "date": dates.strftime("%Y-%m-%d").tolist(),
        "province": np.random.choice(
            ["Kigali", "Eastern", "Western", "Northern", "Southern"], len(dates)
        ).tolist(),
        "visitors": np.random.poisson(1000, len(dates)).tolist(),
        "avg_stay_days": np.random.normal(3.5, 1.2, len(dates)).round(2).tolist(),
        "revenue_usd": np.random.exponential(500, len(dates)).round(2).tolist(),
    }
    df = pd.DataFrame(data)
    return df

def analyze_tourism_data(df: pd.DataFrame):
    # Basic analytics
    results = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total_visitors": int(df["visitors"].sum()),
        "avg_daily_visitors": float(df["visitors"].mean()),
        "top_province": df.groupby("province")["visitors"].sum().idxmax(),
        "avg_stay_days": float(df["avg_stay_days"].mean()),
        "total_revenue_usd": float(df["revenue_usd"].sum()),
    }
    return results

@app.get("/")
def root():
    return {"ok": True, "message": "Use /analyze for summary or /data for full dataset"}

@app.get("/analyze")
def analyze():
    df = generate_tourism_data()
    results = analyze_tourism_data(df)

    # Save both summary and raw data
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        f.write(df.to_json(orient="records", indent=2))

    return JSONResponse(content=results)

@app.get("/data")
def get_data():
    if not os.path.exists(DATA_FILE):
        raise HTTPException(status_code=404, detail="No dataset found. Run /analyze first.")
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return JSONResponse(content=data)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)