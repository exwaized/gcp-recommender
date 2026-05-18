import numpy as np
import scipy.sparse as sp

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
        self.index_user = {i: u for u, i in self.user_index.items()}
        self.index_item = {i: it for it, i in self.item_index.items()}
        rows = interactions_df["user_id"].map(self.user_index)
        cols = interactions_df["item_id"].map(self.item_index)
        data = interactions_df["weight"]
        return sp.csr_matrix((data, (rows, cols)), shape=(len(users), len(items)))

    def _als_train(self, matrix, log=None):
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
            if log and (it + 1) % 5 == 0:
                loss = float(np.mean((dense - self.user_factors @ self.item_factors.T) ** 2))
                log.info(f"  Iteration {it+1}/{self.iterations} | Loss: {loss:.4f}")

    def fit(self, interactions_df, items_df, log=None):
        if log:
            log.info("Building interaction matrix...")
        matrix = self._build_matrix(interactions_df)
        self.item_meta = items_df.set_index("item_id").to_dict("index")
        if log:
            log.info(f"Matrix shape: {matrix.shape} | Training ALS...")
        self._als_train(matrix, log=log)
        if log:
            log.info("Training complete.")
        return self

    def recommend(self, user_id, n=10, exclude_seen=True):
        if user_id not in self.user_index:
            return self._popular_fallback(n)
        u_idx = self.user_index[user_id]
        scores = self.user_factors[u_idx] @ self.item_factors.T
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

    def _popular_fallback(self, n):
        items = sorted(self.item_meta.items(), key=lambda x: x[1].get("avg_rating", 0), reverse=True)
        return [{"item_id": k, **v, "score": 0.0} for k, v in items[:n]]
