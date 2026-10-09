import asyncio

from fastapi.testclient import TestClient

from app.ai import AIRequest, AITask, build_ai_provider
from app.core.config import BACKEND_DIR, Settings


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "carbon-copy-api"
    assert body["database"] == "connected"


def test_system_status_flags_demo_mode_and_disabled_ai(client: TestClient) -> None:
    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    body = response.json()
    assert body["environment"] == "test"
    assert body["demo_mode"] is True
    assert body["ai"] == {"provider": "disabled", "enabled": False}
    assert "not clinically validated" in body["disclaimer"]


def test_cors_allows_local_frontend(client: TestClient) -> None:
    response = client.options(
        "/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_rejects_unknown_origin(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "http://evil.example"})

    assert "access-control-allow-origin" not in response.headers


def test_relative_sqlite_path_is_anchored_to_backend_dir() -> None:
    settings = Settings(database_url="sqlite:///./carbon_copy.db")

    assert settings.database_url == f"sqlite:///{(BACKEND_DIR / 'carbon_copy.db').as_posix()}"


def test_disabled_ai_provider_never_claims_generated_output() -> None:
    provider = build_ai_provider(Settings())
    result = asyncio.run(provider.generate(AIRequest(task=AITask.ANALYZE_FAILURE)))

    assert provider.enabled is False
    assert result.generated is False
    assert result.provider == "disabled"


def test_root_redirects_to_api_docs(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/docs"
