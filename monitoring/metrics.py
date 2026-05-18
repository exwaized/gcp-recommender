"""
Metrics collector — mirrors Google Cloud Monitoring custom metrics.
GCP swap: google.cloud.monitoring_v3.MetricServiceClient
"""
import sqlite3
import json
import os
import time
from datetime import datetime
from collections import defaultdict

DB_PATH = os.path.join(os.path.dirname(__file__), "metrics.db")

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("""
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            metric_name TEXT,
            value REAL,
            labels TEXT,
            timestamp TEXT
        )
    """)
    c.commit()
    return c

class MetricsCollector:
    """
    Local metrics sink. In production: write to Cloud Monitoring time series.
    """
    def __init__(self):
        self._counts = defaultdict(int)
        self._latencies = defaultdict(list)

    def record(self, metric_name: str, value: float, labels: dict = None):
        conn = _conn()
        conn.execute(
            "INSERT INTO metrics (metric_name, value, labels, timestamp) VALUES (?,?,?,?)",
            (metric_name, value, json.dumps(labels or {}), datetime.utcnow().isoformat())
        )
        conn.commit()
        conn.close()

    def get_summary(self, metric_name: str, last_n: int = 100) -> dict:
        conn = _conn()
        rows = conn.execute(
            "SELECT value FROM metrics WHERE metric_name=? ORDER BY id DESC LIMIT ?",
            (metric_name, last_n)
        ).fetchall()
        conn.close()
        if not rows:
            return {}
        vals = [r[0] for r in rows]
        return {
            "count": len(vals),
            "mean": round(sum(vals) / len(vals), 4),
            "min": round(min(vals), 4),
            "max": round(max(vals), 4)
        }

    def get_all_metrics(self) -> list:
        conn = _conn()
        rows = conn.execute(
            "SELECT metric_name, value, labels, timestamp FROM metrics ORDER BY id DESC LIMIT 200"
        ).fetchall()
        conn.close()
        return [{"metric": r[0], "value": r[1], "labels": json.loads(r[2]), "ts": r[3]} for r in rows]
