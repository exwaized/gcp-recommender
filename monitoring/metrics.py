"""
Prometheus metrics — in-memory, per-process, no disk I/O on the request path.
Scrape GET /metrics (needs the X-API-Key header) with Prometheus/Grafana Agent.
GCP swap: Managed Service for Prometheus scrapes the same endpoint unchanged.

Uses a dedicated registry so tests/reloads never hit duplicate-registration errors.
With multiple uvicorn workers each process has its own counters; run one worker per
container (scale by containers) or switch to prometheus_client multiprocess mode.
"""
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

REGISTRY = CollectorRegistry()

REQUESTS = Counter(
    "http_requests_total", "HTTP requests",
    ["method", "path", "status"], registry=REGISTRY,
)
LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency in seconds",
    ["method", "path"], registry=REGISTRY,
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)

# Raw output for the /metrics endpoint.
CONTENT_TYPE = CONTENT_TYPE_LATEST


def observe_request(method: str, path: str, status: int, seconds: float):
    """`path` must be a route template (e.g. /users/{user_id}) to keep label cardinality bounded."""
    REQUESTS.labels(method, path, str(status)).inc()
    LATENCY.labels(method, path).observe(seconds)


def render() -> bytes:
    return generate_latest(REGISTRY)
