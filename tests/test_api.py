from api import main


def test_health_ok_when_model_loaded(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["model_loaded"] is True


def test_health_503_when_model_missing(client, monkeypatch):
    monkeypatch.setattr(main, "model", None)
    assert client.get("/health").status_code == 503


PROTECTED = [
    ("get", "/users"), ("get", "/users/U0001"), ("get", "/items"),
    ("get", "/analytics/summary"), ("get", "/metrics"), ("get", "/model/info"),
]


def test_protected_get_requires_key(client):
    for method, path in PROTECTED:
        assert getattr(client, method)(path).status_code == 401, path
        assert getattr(client, method)(path, headers={"X-API-Key": "bad"}).status_code == 401, path


def test_protected_post_requires_key(client):
    for path, body in [("/recommend", {"user_id": "U0001"}),
                       ("/similar-items", {"item_id": "I001"}),
                       ("/predict", {"instances": []})]:
        assert client.post(path, json=body).status_code == 401, path


def test_fails_closed_without_configured_key(client, monkeypatch):
    monkeypatch.setattr(main, "API_KEY", "")
    assert client.get("/users", headers={"X-API-Key": ""}).status_code == 503


def test_recommend_with_key(client, auth):
    r = client.post("/recommend", json={"user_id": "U0001", "n": 3}, headers=auth)
    assert r.status_code == 200
    assert len(r.json()["recommendations"]) <= 3


def test_n_bounds_enforced(client, auth):
    for n in (0, -1, main.MAX_N + 1):
        r = client.post("/recommend", json={"user_id": "U0001", "n": n}, headers=auth)
        assert r.status_code == 422, n
    r = client.post("/predict", json={"instances": [{"user_id": "U0001", "n": 10**7}]}, headers=auth)
    assert r.status_code == 422


def test_limit_bounds_enforced(client, auth):
    assert client.get("/users?limit=0", headers=auth).status_code == 422
    assert client.get(f"/users?limit={main.MAX_LIMIT + 1}", headers=auth).status_code == 422
    assert client.get("/users?offset=-1", headers=auth).status_code == 422
    assert client.get(f"/items?limit={main.MAX_LIMIT + 1}", headers=auth).status_code == 422
    assert client.get("/users?limit=5", headers=auth).status_code == 200


def test_unknown_user_404(client, auth):
    assert client.get("/users/NOPE", headers=auth).status_code == 404


def test_cors_closed_by_default(client):
    r = client.options("/recommend", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers


def test_metrics_prometheus_format_and_bounded_labels(client, auth):
    client.get("/users/U0001", headers=auth)
    client.get("/users/NOPE", headers=auth)
    r = client.get("/metrics", headers=auth)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert "http_requests_total" in body and "http_request_duration_seconds_bucket" in body
    # route template, never the raw per-user URL
    assert 'path="/users/{user_id}"' in body
    assert "NOPE" not in body
