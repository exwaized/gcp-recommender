"""
FastAPI prediction server — deployable via Docker to any host.
/predict mirrors the Vertex AI Prediction endpoint contract for reference.
Run locally: uvicorn api.main:app --reload --port 8080
Real deployment: containerize via Dockerfile, run on an Oracle Cloud
Always-Free compute instance (see README > Oracle Cloud deployment).
"""
import os
import sys
import time
import logging
import json
import hmac
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from models.train import load_model, CollaborativeFilteringModel
from data.warehouse import query_warehouse, paginate_clause, backend_name
from monitoring.logger import StructuredLogger
from monitoring import metrics

log = StructuredLogger("api")

# CORS is closed by default. Set CORS_ALLOW_ORIGINS to a comma-separated list
# (e.g. "https://app.example.com,http://localhost:5173"); "*" must be asked for
# explicitly and is for local demos only.
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()]

# API-key auth. Fails closed: with no API_KEY set, protected endpoints return 503
# unless API_AUTH_DISABLED=1 is set explicitly (local development / tests).
API_KEY = os.getenv("API_KEY", "")
AUTH_DISABLED = os.getenv("API_AUTH_DISABLED") == "1"
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

MAX_N = 100
MAX_LIMIT = 200


def require_api_key(key: Optional[str] = Depends(_api_key_header)):
    if AUTH_DISABLED:
        return
    if not API_KEY:
        raise HTTPException(503, "Server auth is not configured (set API_KEY)")
    if not key or not hmac.compare_digest(key, API_KEY):
        raise HTTPException(401, "Invalid or missing API key")


# ---- Global model state ----
model: Optional[CollaborativeFilteringModel] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global model
    if not API_KEY and not AUTH_DISABLED:
        log.error("startup", message="API_KEY not set — protected endpoints will return 503")
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
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"]
)

# ---- Request/Response Models ----
class RecommendRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    n: int = Field(default=10, ge=1, le=MAX_N)
    exclude_seen: bool = True

class SimilarItemsRequest(BaseModel):
    item_id: str = Field(min_length=1, max_length=128)
    n: int = Field(default=5, ge=1, le=MAX_N)

class PredictRequest(BaseModel):
    """Vertex AI prediction endpoint contract"""
    instances: list[dict] = Field(max_length=100)

# ---- Middleware: request logging ----
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        elapsed = time.perf_counter() - start
        # Route template, not the raw URL, so /users/<id> doesn't create a series per user.
        route = request.scope.get("route")
        path = route.path if route else "unmatched"
        log.info("request", method=request.method, path=request.url.path,
                 status=status, latency_ms=round(elapsed * 1000, 2))
        metrics.observe_request(request.method, path, status, elapsed)

# ---- Health & Status ----
@app.get("/health")
def health():
    body = {
        "status": "healthy" if model else "degraded",
        "model_loaded": model is not None,
        "warehouse_backend": backend_name(),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    return JSONResponse(body, status_code=200 if model else 503)

@app.get("/metrics", dependencies=[Depends(require_api_key)])
def get_metrics():
    """Prometheus text exposition format."""
    return Response(metrics.render(), media_type=metrics.CONTENT_TYPE)

@app.get("/model/info", dependencies=[Depends(require_api_key)])
def model_info():
    registry_path = os.path.join(os.path.dirname(__file__), "../models/model_registry.json")
    if os.path.exists(registry_path):
        with open(registry_path) as f:
            return json.load(f)
    return {"status": "no registry found"}

# ---- Prediction Endpoints ----
@app.post("/recommend", dependencies=[Depends(require_api_key)])
def recommend(req: RecommendRequest):
    if not model:
        raise HTTPException(503, "Model not loaded")
    recs = model.recommend(req.user_id, n=req.n, exclude_seen=req.exclude_seen)
    log.info("recommend", user_id=req.user_id, n_results=len(recs))
    return {"user_id": req.user_id, "recommendations": recs, "count": len(recs)}

@app.post("/similar-items", dependencies=[Depends(require_api_key)])
def similar_items(req: SimilarItemsRequest):
    if not model:
        raise HTTPException(503, "Model not loaded")
    similar = model.similar_items(req.item_id, n=req.n)
    return {"item_id": req.item_id, "similar_items": similar}

@app.post("/predict", dependencies=[Depends(require_api_key)])
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
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= MAX_N:
            raise HTTPException(422, f"n must be an integer between 1 and {MAX_N}")
        if uid:
            recs = model.recommend(uid, n=n)
            predictions.append({"user_id": uid, "recommendations": recs})
    return {"predictions": predictions}

# ---- Data endpoints (BigQuery equivalent) ----
@app.get("/users", dependencies=[Depends(require_api_key)])
def list_users(limit: int = Query(20, ge=1, le=MAX_LIMIT), offset: int = Query(0, ge=0)):
    df = query_warehouse(f"SELECT * FROM users ORDER BY user_id {paginate_clause(limit, offset)}")
    total = query_warehouse("SELECT COUNT(*) as c FROM users")["c"][0]
    return {"users": df.to_dict("records"), "total": int(total)}

@app.get("/users/{user_id}", dependencies=[Depends(require_api_key)])
def get_user(user_id: str):
    df = query_warehouse("SELECT * FROM users WHERE user_id = :user_id", {"user_id": user_id})
    if df.empty:
        raise HTTPException(404, f"User {user_id} not found")
    history = query_warehouse(f"""
        SELECT i.event_type, i.timestamp, it.title, it.category, it.price
        FROM interactions i JOIN items it ON i.item_id = it.item_id
        WHERE i.user_id = :user_id
        ORDER BY i.timestamp DESC {paginate_clause(20, 0)}
    """, {"user_id": user_id})
    return {
        "user": df.to_dict("records")[0],
        "recent_interactions": history.to_dict("records")
    }

@app.get("/items", dependencies=[Depends(require_api_key)])
def list_items(category: Optional[str] = None, limit: int = Query(20, ge=1, le=MAX_LIMIT)):
    if category:
        df = query_warehouse(
            f"SELECT * FROM items WHERE category = :category {paginate_clause(limit, 0)}",
            {"category": category}
        )
    else:
        df = query_warehouse(f"SELECT * FROM items {paginate_clause(limit, 0)}")
    return {"items": df.to_dict("records")}

@app.get("/analytics/summary", dependencies=[Depends(require_api_key)])
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
    uvicorn.run("api.main:app", host="127.0.0.1", port=8080)
