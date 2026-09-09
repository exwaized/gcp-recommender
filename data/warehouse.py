"""
Warehouse backend dispatcher. Everything in api/ and models/ should import
query_warehouse / load_to_warehouse from here, never from generate_data or
oracle_warehouse directly, so the backend swap is one env var:

    WAREHOUSE_BACKEND=sqlite  (default) -> local warehouse.db, for dev without any cloud account
    WAREHOUSE_BACKEND=oracle             -> real Oracle Autonomous Database (Always Free tier)
"""
import os

BACKEND = os.getenv("WAREHOUSE_BACKEND", "sqlite")

if BACKEND == "oracle":
    from data.oracle_warehouse import query_warehouse as _query_warehouse, load_to_warehouse
elif BACKEND == "sqlite":
    from data.generate_data import query_warehouse as _query_warehouse, load_to_warehouse
else:
    raise ValueError(f"Unknown WAREHOUSE_BACKEND: {BACKEND!r} (expected 'sqlite' or 'oracle')")


def query_warehouse(sql: str, params: dict = None):
    return _query_warehouse(sql, params)


def paginate_clause(limit: int, offset: int) -> str:
    """Backend-appropriate pagination SQL fragment (Oracle has no LIMIT/OFFSET keyword)."""
    limit, offset = int(limit), int(offset)
    if BACKEND == "oracle":
        return f"OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY"
    return f"LIMIT {limit} OFFSET {offset}"


def backend_name() -> str:
    return BACKEND
