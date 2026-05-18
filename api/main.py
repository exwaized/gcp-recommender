"""
FastAPI prediction server — Cloud Run deployable.
Mirrors Vertex AI Prediction endpoint contract.
Run locally: uvicorn api.main:app --reload --port 8080
On GCP: containerize via Dockerfile, deploy to Cloud Run
"""
import os
import sys
import time
import logging
import json
import sqlite3
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from models.train import load_model, CollaborativeFilteringModel
from data.generate_data import query_warehouse, DB_PATH
from monitoring.logger import StructuredLogger

log = StructuredLogger("api")

# ---- Global model state ----
model: Optional[CollaborativeFilteringModel] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global model
    log.info("startup", message="Loading model from registry...")
    try:
        model = load_model()
        log.info("startup", message="Model loaded successfully",
                 users_indexed=len(model.user_index),
                 items_indexed=len(model.item_index))
    except FileNotFoundError:
        log.error("startup", message="Model not found — run train.py first")
    yield
    log.info("shutdown", message="API shutting down")

app = FastAPI(
    title="GCP Recommender API",
    description="Collaborative filtering recommendation engine — Cloud Run ready",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# ---- Request/Response Models ----
class RecommendRequest(BaseModel):
    user_id: str
    n: int = 10
    exclude_seen: bool = True

class SimilarItemsRequest(BaseModel):
    item_id: str
    n: int = 5

class PredictRequest(BaseModel):
    """Vertex AI prediction endpoint contract"""
    instances: list[dict]

# ---- Middleware: request logging ----
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    log.info("request", method=request.method, path=request.url.path,
             status=response.status_code, latency_ms=latency_ms)
    return response

# ---- Health & Status ----
@app.get("/health")
def health():
    return {
        "status": "healthy" if model else "degraded",
        "model_loaded": model is not None,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/model/info")
def model_info():
    registry_path = os.path.join(os.path.dirname(__file__), "../models/model_registry.json")
    if os.path.exists(registry_path):
        with open(registry_path) as f:
            return json.load(f)
    return {"status": "no registry found"}

# ---- Prediction Endpoints ----
@app.post("/recommend")
def recommend(req: RecommendRequest):
    if not model:
        raise HTTPException(503, "Model not loaded")
    recs = model.recommend(req.user_id, n=req.n, exclude_seen=req.exclude_seen)
    log.info("recommend", user_id=req.user_id, n_results=len(recs))
    return {"user_id": req.user_id, "recommendations": recs, "count": len(recs)}

@app.post("/similar-items")
def similar_items(req: SimilarItemsRequest):
    if not model:
        raise HTTPException(503, "Model not loaded")
    similar = model.similar_items(req.item_id, n=req.n)
    return {"item_id": req.item_id, "similar_items": similar}

@app.post("/predict")
def predict(req: PredictRequest):
    """
    Vertex AI-compatible prediction endpoint.
    POST /predict with {"instances": [{"user_id": "U0001", "n": 5}]}
    """
    if not model:
        raise HTTPException(503, "Model not loaded")
    predictions = []
    for instance in req.instances:
        uid = instance.get("user_id")
        n = instance.get("n", 10)
        if uid:
            recs = model.recommend(uid, n=n)
            predictions.append({"user_id": uid, "recommendations": recs})
    return {"predictions": predictions}

# ---- Data endpoints (BigQuery equivalent) ----
@app.get("/users")
def list_users(limit: int = 20, offset: int = 0):
    df = query_warehouse(f"SELECT * FROM users LIMIT {limit} OFFSET {offset}")
    total = query_warehouse("SELECT COUNT(*) as c FROM users")["c"][0]
    return {"users": df.to_dict("records"), "total": int(total)}

@app.get("/users/{user_id}")
def get_user(user_id: str):
    df = query_warehouse(f"SELECT * FROM users WHERE user_id = '{user_id}'")
    if df.empty:
        raise HTTPException(404, f"User {user_id} not found")
    history = query_warehouse(f"""
        SELECT i.event_type, i.timestamp, it.title, it.category, it.price
        FROM interactions i JOIN items it ON i.item_id = it.item_id
        WHERE i.user_id = '{user_id}'
        ORDER BY i.timestamp DESC LIMIT 20
    """)
    return {
        "user": df.to_dict("records")[0],
        "recent_interactions": history.to_dict("records")
    }

@app.get("/items")
def list_items(category: Optional[str] = None, limit: int = 20):
    where = f"WHERE category = '{category}'" if category else ""
    df = query_warehouse(f"SELECT * FROM items {where} LIMIT {limit}")
    return {"items": df.to_dict("records")}

@app.get("/analytics/summary")
def analytics_summary():
    stats = {}
    stats["total_users"] = int(query_warehouse("SELECT COUNT(*) as c FROM users")["c"][0])
    stats["total_items"] = int(query_warehouse("SELECT COUNT(*) as c FROM items")["c"][0])
    stats["total_interactions"] = int(query_warehouse("SELECT COUNT(*) as c FROM interactions")["c"][0])
    stats["top_categories"] = query_warehouse("""
        SELECT category, COUNT(*) as interactions
        FROM interactions i JOIN items it ON i.item_id = it.item_id
        GROUP BY category ORDER BY interactions DESC LIMIT 5
    """).to_dict("records")
    stats["event_breakdown"] = query_warehouse("""
        SELECT event_type, COUNT(*) as count
        FROM interactions GROUP BY event_type
    """).to_dict("records")
    return stats

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
