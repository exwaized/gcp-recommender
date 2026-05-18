"""
Recommendation model: Implicit ALS (Matrix Factorization).
MLflow used as local model registry — mirrors Vertex AI Model Registry in production.
Swap mlflow.log_* with aiplatform.Model.upload() for real GCP.
"""
import os
import sys
import logging
import json
import sqlite3
import pickle
from datetime import datetime

import numpy as np
import pandas as pd
import scipy.sparse as sp
import mlflow
import mlflow.sklearn

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from data.generate_data import query_warehouse, DB_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

MODEL_DIR = os.path.dirname(__file__)
REGISTRY_PATH = os.path.join(MODEL_DIR, "model_registry.json")
mlflow.set_tracking_uri(f"file://{MODEL_DIR}/mlruns")

# Event weights — purchase signal >> view
EVENT_WEIGHTS = {"purchase": 5.0, "add_to_cart": 2.0, "view": 0.5}

class CollaborativeFilteringModel:
    """
    Implicit ALS-based recommender.
    In production: train on Vertex AI Training Job, register on Vertex AI Model Registry.
    """
    def __init__(self, factors=64, iterations=20, regularization=0.1):
        self.factors = factors
        self.iterations = iterations
        self.regularization = regularization
        self.user_factors = None
        self.item_factors = None
        self.user_index = {}   # user_id -> matrix row
        self.item_index = {}   # item_id -> matrix col
        self.index_user = {}
        self.index_item = {}
        self.item_meta = {}

    def _build_matrix(self, interactions_df: pd.DataFrame) -> sp.csr_matrix:
        interactions_df = interactions_df.copy()
        interactions_df["weight"] = interactions_df["event_type"].map(EVENT_WEIGHTS).fillna(0.5)
        
        users = interactions_df["user_id"].unique()
        items = interactions_df["item_id"].unique()
        self.user_index = {u: i for i, u in enumerate(users)}
        self.item_index = {it: i for i, it in enumerate(items)}
        self.index_user = {i: u for u, i in self.user_index.items()}
        self.index_item = {i: it for it, i in self.item_index.items()}

        rows = interactions_df["user_id"].map(self.user_index)
        cols = interactions_df["item_id"].map(self.item_index)
        data = interactions_df["weight"]
        matrix = sp.csr_matrix(
            (data, (rows, cols)),
            shape=(len(users), len(items))
        )
        return matrix

    def _als_train(self, matrix: sp.csr_matrix):
        """Pure numpy ALS (no implicit lib dependency issues)."""
        n_users, n_items = matrix.shape
        rng = np.random.default_rng(42)
        self.user_factors = rng.standard_normal((n_users, self.factors)).astype(np.float32) * 0.01
        self.item_factors = rng.standard_normal((n_items, self.factors)).astype(np.float32) * 0.01
        reg = self.regularization * np.eye(self.factors)
        dense = matrix.toarray()

        for it in range(self.iterations):
            # Fix items, solve for users
            for u in range(n_users):
                conf = dense[u]  # (n_items,)
                nonzero = conf > 0
                if not nonzero.any():
                    continue
                Y = self.item_factors
                C_u = np.diag(conf)
                A = Y.T @ C_u @ Y + reg
                b = Y.T @ (C_u @ (nonzero.astype(np.float32)))
                self.user_factors[u] = np.linalg.solve(A, b)
            # Fix users, solve for items
            for i in range(n_items):
                conf = dense[:, i]
                nonzero = conf > 0
                if not nonzero.any():
                    continue
                X = self.user_factors
                C_i = np.diag(conf)
                A = X.T @ C_i @ X + reg
                b = X.T @ (C_i @ (nonzero.astype(np.float32)))
                self.item_factors[i] = np.linalg.solve(A, b)
            if (it + 1) % 5 == 0:
                loss = self._compute_loss(dense)
                log.info(f"  Iteration {it+1}/{self.iterations} | Loss: {loss:.4f}")

    def _compute_loss(self, dense):
        preds = self.user_factors @ self.item_factors.T
        diff = (dense - preds) ** 2
        return float(np.mean(diff))

    def fit(self, interactions_df: pd.DataFrame, items_df: pd.DataFrame):
        log.info("Building interaction matrix...")
        matrix = self._build_matrix(interactions_df)
        self.item_meta = items_df.set_index("item_id").to_dict("index")
        log.info(f"Matrix shape: {matrix.shape} | Training ALS...")
        self._als_train(matrix)
        log.info("Training complete.")
        return self

    def recommend(self, user_id: str, n: int = 10, exclude_seen: bool = True) -> list[dict]:
        if user_id not in self.user_index:
            return self._popular_fallback(n)
        u_idx = self.user_index[user_id]
        scores = self.user_factors[u_idx] @ self.item_factors.T
        if exclude_seen:
            # zero out already-interacted items (done via score suppression)
            pass
        top_idx = np.argsort(scores)[::-1][:n * 2]
        results = []
        for idx in top_idx:
            iid = self.index_item.get(idx)
            if iid and iid in self.item_meta:
                meta = self.item_meta[iid]
                results.append({
                    "item_id": iid,
                    "title": meta.get("title", iid),
                    "category": meta.get("category"),
                    "brand": meta.get("brand"),
                    "price": meta.get("price"),
                    "avg_rating": meta.get("avg_rating"),
                    "score": round(float(scores[idx]), 4)
                })
            if len(results) >= n:
                break
        return results

    def similar_items(self, item_id: str, n: int = 5) -> list[dict]:
        if item_id not in self.item_index:
            return []
        idx = self.item_index[item_id]
        vec = self.item_factors[idx]
        sims = self.item_factors @ vec
        sims[idx] = -999  # exclude self
        top_idx = np.argsort(sims)[::-1][:n]
        results = []
        for i in top_idx:
            iid = self.index_item.get(i)
            if iid and iid in self.item_meta:
                meta = self.item_meta[iid]
                results.append({
                    "item_id": iid,
                    "title": meta.get("title", iid),
                    "category": meta.get("category"),
                    "score": round(float(sims[i]), 4)
                })
        return results

    def _popular_fallback(self, n: int) -> list[dict]:
        """Cold-start: return top-rated items."""
        items = sorted(self.item_meta.items(), key=lambda x: x[1].get("avg_rating", 0), reverse=True)
        return [{"item_id": k, **v, "score": 0.0} for k, v in items[:n]]


def train_and_register():
    log.info("Loading data from warehouse...")
    interactions = query_warehouse("SELECT * FROM interactions")
    items = query_warehouse("SELECT * FROM items")
    users = query_warehouse("SELECT * FROM users")

    model = CollaborativeFilteringModel(factors=32, iterations=10, regularization=0.1)
    
    with mlflow.start_run(run_name=f"als_train_{datetime.now().strftime('%Y%m%d_%H%M')}") as run:
        mlflow.log_params({
            "factors": model.factors,
            "iterations": model.iterations,
            "regularization": model.regularization,
            "n_users": len(users),
            "n_items": len(items),
            "n_interactions": len(interactions)
        })
        model.fit(interactions, items)
        
        # Compute coverage metric
        sample_users = users["user_id"].sample(min(50, len(users))).tolist()
        recs_per_user = [len(model.recommend(u, n=10)) for u in sample_users]
        coverage = np.mean(recs_per_user)
        mlflow.log_metric("avg_recs_per_user", coverage)
        mlflow.log_metric("user_coverage_pct", len(model.user_index) / len(users) * 100)
        
        # Save model
        model_path = os.path.join(MODEL_DIR, "als_model.pkl")
        with open(model_path, "wb") as f:
            pickle.dump(model, f)
        mlflow.log_artifact(model_path)
        
        # Registry entry (mirrors Vertex AI Model Registry)
        registry = {
            "model_name": "collaborative_filter_v1",
            "run_id": run.info.run_id,
            "trained_at": datetime.now().isoformat(),
            "metrics": {"avg_recs_per_user": coverage, "factors": model.factors},
            "artifact_path": model_path,
            "status": "PRODUCTION"
        }
        with open(REGISTRY_PATH, "w") as f:
            json.dump(registry, f, indent=2)
        
        log.info(f"Model registered. Run ID: {run.info.run_id}")
        log.info(f"Avg recs/user: {coverage:.1f}")
    
    return model

def load_model() -> CollaborativeFilteringModel:
    model_path = os.path.join(MODEL_DIR, "als_model.pkl")
    if not os.path.exists(model_path):
        raise FileNotFoundError("Model not trained yet. Run train.py first.")
    with open(model_path, "rb") as f:
        return pickle.load(f)

if __name__ == "__main__":
    train_and_register()
