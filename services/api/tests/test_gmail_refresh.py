from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient


@dataclass
class _FakeStats:
    total: int = 5
    leads_created: int = 2
    interview_events_created: int = 1
    filtered_by_location: int = 1


def test_refresh_success_redirects_with_summary(authed_client: TestClient, monkeypatch) -> None:
    import ingest_gmail.sync as sync_module

    monkeypatch.setattr(sync_module, "run_once", lambda: _FakeStats())

    response = authed_client.post("/gmail/refresh")

    assert response.status_code == 200  # TestClient follows the redirect
    assert "2 new lead" in response.text
    assert "1 interview event" in response.text


def test_refresh_failure_redirects_with_error(authed_client: TestClient, monkeypatch) -> None:
    import ingest_gmail.sync as sync_module

    def _boom():
        raise RuntimeError("No stored Gmail credentials.")

    monkeypatch.setattr(sync_module, "run_once", _boom)

    response = authed_client.post("/gmail/refresh")

    assert response.status_code == 200
    assert "Gmail refresh failed" in response.text
    assert "No stored Gmail credentials" in response.text


def test_refresh_requires_login(client: TestClient) -> None:
    response = client.post("/gmail/refresh", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")
