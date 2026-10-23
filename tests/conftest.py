import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("WAREHOUSE_BACKEND", "sqlite")

import pytest
from fastapi.testclient import TestClient

from api import main


@pytest.fixture(scope="session")
def warehouse():
    """Ensure a local sqlite warehouse exists (it is not tracked in git)."""
    from data import generate_data
    if not os.path.exists(generate_data.DB_PATH):
        generate_data.run()


@pytest.fixture
def client(warehouse, monkeypatch):
    monkeypatch.setattr(main, "API_KEY", "test-key")
    monkeypatch.setattr(main, "AUTH_DISABLED", False)
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def auth():
    return {"X-API-Key": "test-key"}
