import os

# Must be set before the app is imported: the engine is built at import time.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ENVIRONMENT"] = "test"

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def seeded_app_database() -> None:
    """Seed the app's in-memory database once for API tests."""
    from app.db.seed import seed_database
    from app.db.session import SessionLocal, init_db

    init_db()
    with SessionLocal() as session:
        seed_database(session)
