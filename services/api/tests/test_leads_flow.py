from __future__ import annotations

from fastapi.testclient import TestClient


def test_unauthenticated_leads_redirects_to_login(client: TestClient) -> None:
    response = client.get("/leads", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_login_wrong_password_shows_error(client: TestClient) -> None:
    response = client.post("/login", data={"password": "wrong", "next": "/leads"})
    assert response.status_code == 401
    assert "Incorrect password" in response.text


def test_create_lead_and_view_detail(authed_client: TestClient) -> None:
    response = authed_client.post(
        "/leads",
        data={
            "company": "Acme Corp",
            "role_title": "Backend Engineer",
            "jd_text": "Build things with Python.",
            "jd_url": "",
            "recruiter_name": "",
            "recruiter_contact": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    lead_url = response.headers["location"]

    detail = authed_client.get(lead_url)
    assert detail.status_code == 200
    assert "Acme Corp" in detail.text
    assert "Backend Engineer" in detail.text
    assert "new" in detail.text


def test_update_status_writes_history(authed_client: TestClient) -> None:
    created = authed_client.post(
        "/leads",
        data={
            "company": "Beta LLC",
            "role_title": "QA Engineer",
            "jd_text": "Test things.",
        },
        follow_redirects=False,
    )
    lead_url = created.headers["location"]
    lead_id = lead_url.rsplit("/", maxsplit=1)[-1]

    response = authed_client.post(
        f"/leads/{lead_id}/status",
        data={"new_status": "tailored", "reason": "manual test"},
    )
    assert response.status_code == 200
    assert "tailored" in response.text
    assert "manual test" in response.text


def test_add_interview_event(authed_client: TestClient) -> None:
    created = authed_client.post(
        "/leads",
        data={
            "company": "Gamma Inc",
            "role_title": "Platform Engineer",
            "jd_text": "Scale platforms.",
        },
        follow_redirects=False,
    )
    lead_id = created.headers["location"].rsplit("/", maxsplit=1)[-1]

    response = authed_client.post(
        f"/leads/{lead_id}/interview-events",
        data={
            "scheduled_at": "2026-10-05T10:00",
            "event_type": "phone_screen",
            "location_or_link": "",
            "notes": "",
        },
    )
    assert response.status_code == 200
    assert "phone_screen" in response.text


def test_leads_list_sorts_by_soonest_event(authed_client: TestClient) -> None:
    soonest = authed_client.post(
        "/leads",
        data={"company": "Soonest Co", "role_title": "Role A", "jd_text": "x"},
        follow_redirects=False,
    ).headers["location"]
    later = authed_client.post(
        "/leads",
        data={"company": "Later Co", "role_title": "Role B", "jd_text": "x"},
        follow_redirects=False,
    ).headers["location"]
    authed_client.post(
        "/leads",
        data={"company": "No Event Co", "role_title": "Role C", "jd_text": "x"},
        follow_redirects=False,
    )

    authed_client.post(
        f"{soonest}/interview-events",
        data={"scheduled_at": "2026-10-01T09:00", "event_type": "call"},
    )
    authed_client.post(
        f"{later}/interview-events",
        data={"scheduled_at": "2026-10-10T09:00", "event_type": "call"},
    )

    listing = authed_client.get("/leads").text
    assert listing.index("Soonest Co") < listing.index("Later Co") < listing.index("No Event Co")
