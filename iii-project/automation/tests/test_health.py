from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_default_service_status(monkeypatch) -> None:
    monkeypatch.delenv("OUTREACH_MODE", raising=False)
    app = create_app()
    client = TestClient(app)

    response = client.get("/automation/health")

    assert app.title == "CareCircle Automation"
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "service": "carecircle-automation",
        "outreachMode": "simulation",
    }


def test_health_uses_configured_outreach_mode(monkeypatch) -> None:
    monkeypatch.setenv("OUTREACH_MODE", "live")
    client = TestClient(create_app())

    response = client.get("/automation/health")

    assert response.status_code == 200
    assert response.json()["outreachMode"] == "live"


def test_browser_preflight_is_accepted() -> None:
    client = TestClient(create_app())

    response = client.options(
        "/automation/cases",
        headers={
            "Origin": "http://127.0.0.1:8010",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": (
                "authorization,content-type,idempotency-key"
            ),
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert "POST" in response.headers["access-control-allow-methods"]
