import pytest
from fastapi.testclient import TestClient
from jobpilot.app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "database" in data
    assert "gemini" in data
    assert "smtp" in data


def test_ui_pages_render():
    pages = [
        "/",
        "/discover",
        "/pipeline",
        "/companies",
        "/outbox",
        "/followups",
        "/sources",
        "/answers",
        "/settings",
    ]
    for page in pages:
        res = client.get(page)
        assert res.status_code == 200, f"Page {page} failed with status {res.status_code}"
        assert "<!DOCTYPE html>" in res.text, f"Page {page} did not return valid HTML"

