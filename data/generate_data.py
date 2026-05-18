"""
Synthetic e-commerce interaction dataset generator.
Schema mirrors BigQuery tables: users, items, interactions.
Swap generate_* functions with BigQuery client reads in production.
"""
import sqlite3
import pandas as pd
import numpy as np
import json
import os
import logging
from datetime import datetime, timedelta
import random

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

CATEGORIES = ["Electronics", "Books", "Clothing", "Sports", "Home", "Beauty", "Toys"]
BRANDS = ["AlphaX", "NovaTech", "ZenBrand", "PeakGear", "CloudWear", "BrightLife"]
DB_PATH = os.path.join(os.path.dirname(__file__), "warehouse.db")

# --- BigQuery-equivalent schema ---
SCHEMA = {
    "users": """
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            age_group TEXT,
            city TEXT,
            signup_date TEXT,
            segment TEXT
        )""",
    "items": """
        CREATE TABLE IF NOT EXISTS items (
            item_id TEXT PRIMARY KEY,
            title TEXT,
            category TEXT,
            brand TEXT,
            price REAL,
            avg_rating REAL
        )""",
    "interactions": """
        CREATE TABLE IF NOT EXISTS interactions (
            interaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            item_id TEXT,
            event_type TEXT,
            rating REAL,
            timestamp TEXT
        )"""
}

def _get_conn():
    return sqlite3.connect(DB_PATH)

def generate_users(n=500):
    cities = ["Mumbai", "Delhi", "Bangalore", "Hyderabad", "Chennai", "Pune"]
    segments = ["budget", "mid-tier", "premium"]
    age_groups = ["18-24", "25-34", "35-44", "45-54", "55+"]
    rows = []
    for i in range(n):
        rows.append({
            "user_id": f"U{i:04d}",
            "age_group": random.choice(age_groups),
            "city": random.choice(cities),
            "signup_date": (datetime(2022, 1, 1) + timedelta(days=random.randint(0, 900))).strftime("%Y-%m-%d"),
            "segment": random.choice(segments)
        })
    return pd.DataFrame(rows)

def generate_items(n=200):
    rows = []
    for i in range(n):
        cat = random.choice(CATEGORIES)
        rows.append({
            "item_id": f"I{i:04d}",
            "title": f"{random.choice(BRANDS)} {cat} Item {i}",
            "category": cat,
            "brand": random.choice(BRANDS),
            "price": round(random.uniform(10, 2000), 2),
            "avg_rating": round(random.uniform(3.0, 5.0), 2)
        })
    return pd.DataFrame(rows)

def generate_interactions(users_df, items_df, n=15000):
    """Biased interaction generation — users prefer certain categories (realistic)."""
    user_prefs = {uid: random.sample(CATEGORIES, k=random.randint(2, 4))
                  for uid in users_df["user_id"]}
    cat_items = items_df.groupby("category")["item_id"].apply(list).to_dict()
    events = ["view", "view", "view", "add_to_cart", "purchase"]
    rows = []
    base_time = datetime(2024, 1, 1)
    for _ in range(n):
        uid = random.choice(users_df["user_id"].tolist())
        preferred_cats = user_prefs[uid]
        cat = random.choices(
            CATEGORIES,
            weights=[5 if c in preferred_cats else 1 for c in CATEGORIES]
        )[0]
        iid = random.choice(cat_items.get(cat, items_df["item_id"].tolist()))
        event = random.choice(events)
        rating = round(random.gauss(4.0, 0.8), 1) if event == "purchase" else None
        rating = max(1.0, min(5.0, rating)) if rating else None
        rows.append({
            "user_id": uid,
            "item_id": iid,
            "event_type": event,
            "rating": rating,
            "timestamp": (base_time + timedelta(
                days=random.randint(0, 365),
                hours=random.randint(0, 23)
            )).strftime("%Y-%m-%dT%H:%M:%S")
        })
    return pd.DataFrame(rows)

def load_to_warehouse(users_df, items_df, interactions_df):
    """Mirrors BigQuery load job. Locally uses SQLite."""
    conn = _get_conn()
    cur = conn.cursor()
    for table, ddl in SCHEMA.items():
        cur.execute(ddl)
    conn.commit()
    users_df.to_sql("users", conn, if_exists="replace", index=False)
    items_df.to_sql("items", conn, if_exists="replace", index=False)
    interactions_df.to_sql("interactions", conn, if_exists="replace", index=False)
    conn.close()
    log.info(f"Loaded {len(users_df)} users, {len(items_df)} items, {len(interactions_df)} interactions → warehouse.db")

def query_warehouse(sql: str) -> pd.DataFrame:
    """Drop-in replacement for bigquery.Client().query(sql).to_dataframe()"""
    conn = _get_conn()
    df = pd.read_sql_query(sql, conn)
    conn.close()
    return df

def run():
    log.info("Generating synthetic dataset...")
    users = generate_users(500)
    items = generate_items(200)
    interactions = generate_interactions(users, items, 15000)
    load_to_warehouse(users, items, interactions)
    # Persist CSVs for inspection
    out = os.path.dirname(__file__)
    users.to_csv(f"{out}/users.csv", index=False)
    items.to_csv(f"{out}/items.csv", index=False)
    interactions.to_csv(f"{out}/interactions.csv", index=False)
    log.info("CSVs exported. Data generation complete.")
    return users, items, interactions

if __name__ == "__main__":
    run()
