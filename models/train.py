import os
import sys
import logging
import json
import pathlib
from datetime import datetime

import numpy as np
import pandas as pd
import scipy.sparse as sp
import mlflow

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from data.generate_data import query_warehouse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

MODEL_DIR = os.path.dirname(os.path.abspath(__file__))
REGISTRY_PATH = os.path.join(MODEL_DIR, "model_registry.json")
mlflow.set_tracking_uri(pathlib.Path(MODEL_DIR, "mlruns").as_uri())

EVENT_WEIGHTS = {"purchase": 5.0, "add_to_cart": 2.0, "view": 0.5}


class CollaborativeFilteringModel:
    def __init__(self, factors=32, iterations=10, regularization=0.1):
        self.factors = factors
        self.iterations = iterations
        self.regularization = regularization
        self.user_factors = None
        self.item_factors = None
        self.user_index = {}
        self.item_index = {}
        self.index_user = {}
        self.index_item = {}
        self.item_meta = {}

    def _build_matrix(self, interactions_df):
        interactions_df = interactions_df.copy()
        interactions_df["weight"] = interactions_df["event_type"].map(EVENT_WEIGHTS).fillna(0.5)
        users = interactions_df["user_id"].unique()
        items = interactions_df["item_id"].unique()
        self.user_index = {u: i for i, u in enumerate(users)}
        self.item_index = {it: i for i, it in enumerate(items)}
        self.index_user = {str(i): u for u, i in self.user_index.items()}
        self.index_item = {str(i): it for it, i in self.item_index.items()}
        rows = interactions_df["user_id"].map(self.user_index)
        cols = interactions_df["item_id"].map(self.item_index)
        data = interactions_df["weight"]
        return sp.csr_matrix((data, (rows, cols)), shape=(len(users), len(items)))

    def _als_train(self, matrix):
        n_users, n_items = matrix.shape
        rng = np.random.default_rng(42)
        self.user_factors = rng.standard_normal((n_users, self.factors)).astype(np.float32) * 0.01
        self.item_factors = rng.standard_normal((n_items, self.factors)).astype(np.float32) * 0.01
        reg = self.regularization * np.eye(self.factors)
        dense = matrix.toarray()
        for it in range(self.iterations):
            for u in range(n_users):
                conf = dense[u]
                nonzero = conf > 0
                if not nonzero.any():
                    continue
                Y = self.item_factors
                C_u = np.diag(conf)
                A = Y.T @ C_u @ Y + reg
                b = Y.T @ (C_u @ nonzero.astype(np.float32))
                self.user_factors[u] = np.linalg.solve(A, b)
            for i in range(n_items):
                conf = dense[:, i]
                nonzero = conf > 0
                if not nonzero.any():
                    continue
                X = self.user_factors
                C_i = np.diag(conf)
                A = X.T @ C_i @ X + reg
                b = X.T @ (C_i @ nonzero.astype(np.float32))
                self.item_factors[i] = np.linalg.solve(A, b)
            if (it + 1) % 5 == 0:
                loss = float(np.mean((dense - self.user_factors @ self.item_factors.T) ** 2))
                log.info(f"  Iteration {it+1}/{self.iterations} | Loss: {loss:.4f}")

    def fit(self, interactions_df, items_df):
        log.info("Building interaction matrix...")
        matrix = self._build_matrix(interactions_df)
        self.item_meta = items_df.set_index("item_id").to_dict("index")
        log.info(f"Matrix shape: {matrix.shape} | Training ALS...")
        self._als_train(matrix)
        log.info("Training complete.")
        return self

    def save(self, directory):
        """Save as plain numpy + json — no pickle, no joblib."""
        os.makedirs(directory, exist_ok=True)
        np.save(os.path.join(directory, "user_factors.npy"), self.user_factors)
        np.save(os.path.join(directory, "item_factors.npy"), self.item_factors)
        meta = {
            "factors": self.factors,
            "iterations": self.iterations,
            "regularization": self.regularization,
            "user_index": self.user_index,
            "item_index": self.item_index,
            "index_user": self.index_user,
            "index_item": self.index_item,
            "item_meta": self.item_meta,
        }
        with open(os.path.join(directory, "meta.json"), "w") as f:
            json.dump(meta, f)
        log.info(f"Model saved to {directory}")

    @classmethod
    def load(cls, directory):
        """Load from plain numpy + json — works everywhere, no class resolution issues."""
        with open(os.path.join(directory, "meta.json")) as f:
            meta = json.load(f)
        model = cls(
            factors=meta["factors"],
            iterations=meta["iterations"],
            regularization=meta["regularization"]
        )
        model.user_factors = np.load(os.path.join(directory, "user_factors.npy"))
        model.item_factors = np.load(os.path.join(directory, "item_factors.npy"))
        model.user_index = meta["user_index"]
        model.item_index = meta["item_index"]
        model.index_user = meta["index_user"]
        model.index_item = meta["index_item"]
        model.item_meta = meta["item_meta"]
        return model

    def recommend(self, user_id, n=10):
        if user_id not in self.user_index:
            return self._popular_fallback(n)
        u_idx = self.user_index[user_id]
        scores = self.user_factors[u_idx] @ self.item_factors.T
        top_idx = np.argsort(scores)[::-1][:n * 2]
        results = []
        for idx in top_idx:
            iid = self.index_item.get(str(idx))
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

    def similar_items(self, item_id, n=5):
        if item_id not in self.item_index:
            return []
        idx = self.item_index[item_id]
        vec = self.item_factors[idx]
        sims = self.item_factors @ vec
        sims[idx] = -999
        top_idx = np.argsort(sims)[::-1][:n]
        results = []
        for i in top_idx:
            iid = self.index_item.get(str(i))
            if iid and iid in self.item_meta:
                meta = self.item_meta[iid]
                results.append({
                    "item_id": iid,
                    "title": meta.get("title", iid),
                    "category": meta.get("category"),
                    "score": round(float(sims[i]), 4)
                })
        return results

    def _popular_fallback(self, n):
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

        sample_users = users["user_id"].sample(min(50, len(users))).tolist()
        coverage = float(np.mean([len(model.recommend(u, n=10)) for u in sample_users]))
        mlflow.log_metric("avg_recs_per_user", coverage)
        mlflow.log_metric("user_coverage_pct", len(model.user_index) / len(users) * 100)

        save_dir = os.path.join(MODEL_DIR, "saved_model")
        model.save(save_dir)
        mlflow.log_artifact(save_dir)

        registry = {
            "model_name": "collaborative_filter_v1",
            "run_id": run.info.run_id,
            "trained_at": datetime.now().isoformat(),
            "metrics": {"avg_recs_per_user": coverage, "factors": model.factors},
            "artifact_path": save_dir,
            "status": "PRODUCTION"
        }
        with open(REGISTRY_PATH, "w") as f:
            json.dump(registry, f, indent=2)

        log.info(f"Model registered. Run ID: {run.info.run_id}")
        log.info(f"Avg recs/user: {coverage:.1f}")

    return model


def load_model():
    save_dir = os.path.join(MODEL_DIR, "saved_model")
    if not os.path.exists(save_dir):
        raise FileNotFoundError("Model not trained yet. Run: python models/train.py")
    return CollaborativeFilteringModel.load(save_dir)


if __name__ == "__main__":
    train_and_register()

