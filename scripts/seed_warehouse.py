"""
Backend-agnostic warehouse seeding. Generates the synthetic dataset and loads
it into whichever backend WAREHOUSE_BACKEND points at (sqlite locally, oracle
in the real deployment). Also writes CSVs for inspection either way.

Usage:
    WAREHOUSE_BACKEND=oracle ORACLE_USER=... ORACLE_PASSWORD=... ORACLE_CONNECT_STRING=... \
        python scripts/seed_warehouse.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from data.generate_data import generate_users, generate_items, generate_interactions
from data.warehouse import load_to_warehouse, backend_name


def run():
    print(f"Seeding warehouse backend: {backend_name()}")
    users = generate_users(500)
    items = generate_items(200)
    interactions = generate_interactions(users, items, 15000)
    load_to_warehouse(users, items, interactions)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    users.to_csv(f"{out}/users.csv", index=False)
    items.to_csv(f"{out}/items.csv", index=False)
    interactions.to_csv(f"{out}/interactions.csv", index=False)
    print("Seed complete.")


if __name__ == "__main__":
    run()
