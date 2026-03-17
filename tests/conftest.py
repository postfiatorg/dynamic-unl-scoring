"""Shared test fixtures."""

import pytest
from fastapi.testclient import TestClient

from scoring_service.main import app


@pytest.fixture()
def client(monkeypatch):
    """FastAPI test client with database calls mocked out."""
    monkeypatch.setattr("scoring_service.main.init_db_if_needed", lambda: None)

    with TestClient(app) as c:
        yield c
