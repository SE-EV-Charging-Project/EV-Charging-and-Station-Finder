"""
Test Suite for Frontend Static Serving & CORS (ChargeSlot Minimalist Frontend).
"""

from fastapi.testclient import TestClient
from app.main import app


def test_frontend_root_serves_index_html(client: TestClient):
    """GET / serves the minimalist ChargeSlot frontend index.html."""
    response = client.get("/")
    assert response.status_code == 200
    assert "ChargeSlot" in response.text
    assert "map-container" in response.text
    assert "battery-soc-slider" in response.text


def test_frontend_serves_static_assets(client: TestClient):
    """GET /static/css/style.css and /static/js/app.js serve frontend assets."""
    css_resp = client.get("/static/css/style.css")
    assert css_resp.status_code == 200
    assert "--brand-green" in css_resp.text

    js_resp = client.get("/static/js/app.js")
    assert js_resp.status_code == 200
    assert "calculateBatteryEstimates" in js_resp.text


def test_frontend_static_path_traversal_blocked(client: TestClient):
    """Directory traversal attempts return 404."""
    resp = client.get("/static/../../README.md")
    assert resp.status_code == 404


def test_cors_headers_present(client: TestClient):
    """CORS middleware allows local development requests."""
    response = client.options(
        "/api/v1/stations/nearby",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
