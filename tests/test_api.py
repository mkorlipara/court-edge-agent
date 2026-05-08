"""Tests for the FastAPI application."""

from fastapi.testclient import TestClient

from court_edge_agent.api.main import app

client = TestClient(app)


class TestHealth:
    def test_health_returns_200(self) -> None:
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_body(self) -> None:
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestPredictSchema:
    def test_missing_required_fields_returns_422(self) -> None:
        response = client.post("/predict", json={})
        assert response.status_code == 422

    def test_invalid_market_returns_422(self) -> None:
        response = client.post("/predict", json={
            "player_name": "Stephen Curry",
            "game_date": "2025-01-15",
            "market": "turnovers",  # invalid market
        })
        assert response.status_code == 422

    def test_invalid_date_format_returns_422(self) -> None:
        response = client.post("/predict", json={
            "player_name": "Stephen Curry",
            "game_date": "not-a-date",
            "market": "points",
        })
        assert response.status_code == 422
