from __future__ import annotations

import os

# Point at the test database and set required secrets *before* app.config is
# imported anywhere below -- load_dotenv() defaults to override=False, so setting
# these first means the real services/api/.env is never touched by the test run.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://jobsearch_app:devpassword@localhost:5432/jobsearch_test",
)
os.environ.setdefault("SESSION_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("DASHBOARD_PASSWORD", "test-password")

import pytest
from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def _clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def authed_client(client: TestClient) -> TestClient:
    response = client.post(
        "/login",
        data={"password": os.environ["DASHBOARD_PASSWORD"], "next": "/leads"},
    )
    assert response.status_code == 200  # TestClient follows the 303 redirect by default
    return client
