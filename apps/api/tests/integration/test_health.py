"""Health endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_liveness_never_touches_a_dependency(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "test"


def test_readiness_reports_each_dependency(client: TestClient) -> None:
    response = client.get("/health/ready")

    # Redis may or may not be running locally; the contract is that the endpoint
    # names every dependency and returns 503 rather than 200 when one is down.
    assert response.status_code in (200, 503)
    checks = response.json()["checks"]
    assert checks["database"] == "ok"
    assert "redis" in checks
    assert (response.status_code == 200) == all(v == "ok" for v in checks.values())


def test_every_response_carries_a_request_id(client: TestClient) -> None:
    response = client.get("/health")
    assert response.headers["X-Request-ID"]


def test_supplied_request_id_is_echoed_back(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "trace-me-123"})
    assert response.headers["X-Request-ID"] == "trace-me-123"


def test_openapi_is_served(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert spec["info"]["title"] == "Matchly API"
    assert "/api/v1/auth/request-otp" in spec["paths"]
