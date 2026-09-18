from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://jobsearch_app:devpassword@localhost:5432/jobsearch_test",
)

import pytest
from jobsearch_db.db import Base, SessionLocal, engine
from sqlalchemy.orm import Session


@pytest.fixture(autouse=True)
def _clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db() -> Session:
    with SessionLocal() as session:
        yield session
