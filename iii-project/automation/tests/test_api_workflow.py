import time

from fastapi.testclient import TestClient
import pytest

from app.auth import sign_test_token
from app.main import create_app
from app.models import Donor
from tests.fakes import MemoryRepository, RecordingMessenger


AUTH_SECRET = "test-secret"


@pytest.fixture
def repo() -> MemoryRepository:
    repo = MemoryRepository(clock=lambda: "2026-06-06T12:00:00Z")
    repo.put_donor(
        Donor(
            id="D1",
            name="Dev",
            blood_group="O-",
            city="Dehradun",
            eligible=True,
            reliability=90,
            fatigue=5,
            email="dev@example.com",
            phone="+15555550100",
        )
    )
    return repo


@pytest.fixture
def api_client(monkeypatch, repo: MemoryRepository) -> TestClient:
    from app import dependencies

    monkeypatch.setenv("AUTH_SECRET", AUTH_SECRET)
    app = create_app()
    app.dependency_overrides[dependencies.get_repository] = lambda: repo
    app.dependency_overrides[dependencies.get_messenger] = (
        lambda: RecordingMessenger()
    )
    app.dependency_overrides[dependencies.get_clock] = (
        lambda: "2026-06-06T12:00:00Z"
    )
    app.dependency_overrides[dependencies.get_outreach_mode] = (
        lambda: "simulation"
    )
    return TestClient(app)


@pytest.fixture
def patient_token() -> str:
    return _token("patient@example.com", "patient")


@pytest.fixture
def other_patient_token() -> str:
    return _token("other@example.com", "patient")


@pytest.fixture
def admin_token() -> str:
    return _token("admin@example.com", "admin")


def test_simulated_case_lifecycle(
    api_client: TestClient, patient_token: str, admin_token: str
) -> None:
    created = api_client.post(
        "/automation/cases",
        headers={
            "Authorization": f"Bearer {patient_token}",
            "Idempotency-Key": "case-1",
        },
        json={
            "patient_name": "Asha",
            "blood_group": "O-",
            "units": 1,
            "hospital": "Doon Hospital",
            "city": "Dehradun",
            "deadline": "2026-06-10",
            "urgency": "critical",
        },
    )
    assert created.status_code == 201
    case_id = created.json()["id"]

    listed = api_client.get(
        "/automation/cases",
        headers={"Authorization": f"Bearer {patient_token}"},
    )
    assert [case["id"] for case in listed.json()] == [case_id]

    planned = api_client.post(
        f"/automation/cases/{case_id}/plan",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert planned.status_code == 200
    assert planned.json()["state"] == "PLANNED"
    assert planned.json()["plan"] == {
        "primary": ["D1"],
        "backup": [],
        "emergency": [],
    }

    started = api_client.post(
        f"/automation/cases/{case_id}/start",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert started.status_code == 200
    assert started.json()["state"] == "OUTREACH_ACTIVE"

    response = api_client.post(
        f"/automation/cases/{case_id}/responses",
        json={"donor_id": "D1", "status": "accepted"},
    )
    assert response.status_code == 200
    assert response.json()["state"] == "DONOR_CONFIRMED"

    closed = api_client.post(
        f"/automation/cases/{case_id}/close",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"outcome": "fulfilled"},
    )
    assert closed.status_code == 200
    assert closed.json()["state"] == "FULFILLED"


def test_patient_cannot_approve(
    api_client: TestClient, patient_token: str
) -> None:
    response = api_client.post(
        "/automation/approvals/approval-1/approve",
        headers={"Authorization": f"Bearer {patient_token}"},
    )

    assert response.status_code == 403


def test_patient_cannot_read_another_patients_case(
    api_client: TestClient,
    patient_token: str,
    other_patient_token: str,
) -> None:
    created = api_client.post(
        "/automation/cases",
        headers={
            "Authorization": f"Bearer {patient_token}",
            "Idempotency-Key": "case-1",
        },
        json=_request_payload(),
    )

    response = api_client.get(
        f"/automation/cases/{created.json()['id']}",
        headers={"Authorization": f"Bearer {other_patient_token}"},
    )

    assert response.status_code == 404


def test_missing_idempotency_key_is_rejected(
    api_client: TestClient, patient_token: str
) -> None:
    response = api_client.post(
        "/automation/cases",
        headers={"Authorization": f"Bearer {patient_token}"},
        json=_request_payload(),
    )

    assert response.status_code == 400


def test_public_match_creates_planned_case_without_bearer(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    repo: MemoryRepository,
) -> None:
    from app import main as main_module
    from app import ml_service

    monkeypatch.setattr(main_module, "_load_dataset", lambda: {"donors": []})
    monkeypatch.setattr(ml_service, "predict_donor_active_status", lambda **_: True)
    monkeypatch.setattr(ml_service, "predict_patient_frequency", lambda **_: 28.0)

    response = api_client.post(
        "/automation/public-match",
        headers={"Idempotency-Key": "public-match-1"},
        json=_request_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "PLANNED"
    assert body["plan"] == {
        "primary": ["D1"],
        "backup": [],
        "emergency": [],
    }
    assert body["ranked_donors"][0]["donor"]["id"] == "D1"
    assert body["ranked_donors"][0]["score"] > 0
    assert body["model"]["framework"] == "pytorch"
    assert repo.list_cases()[0].owner_email.endswith("@carecircle.local")


def test_public_donor_registration_saves_cloud_donor_with_ml_prediction(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    repo: MemoryRepository,
) -> None:
    from app import ml_service

    monkeypatch.setattr(ml_service, "predict_donor_active_status", lambda **_: True)

    response = api_client.post(
        "/automation/donors",
        json={
            "name": "Neha Sharma",
            "blood_group": "A+",
            "city": "Hyderabad",
            "country": "India",
            "last_donation_date": "2026-01-01",
            "phone": "+919876543210",
            "email": "neha@example.com",
            "gender": "Unknown",
            "donor_type": "Emergency Donor",
            "donations_till_date": 3,
            "total_calls": 3,
            "cycle_of_donations": 90,
        },
    )

    assert response.status_code == 201
    body = response.json()
    donor_id = body["donor"]["id"]
    assert body["model"] == {
        "framework": "pytorch",
        "donor_active_prediction": True,
    }
    assert repo.get_donor(donor_id).active_status == "Active"


def test_assistant_returns_proposed_action_without_mutation(
    api_client: TestClient,
    patient_token: str,
    repo: MemoryRepository,
) -> None:
    response = api_client.post(
        "/automation/assistant",
        headers={"Authorization": f"Bearer {patient_token}"},
        json={"message": "Please create an O- blood request for Asha"},
    )

    assert response.status_code == 200
    assert response.json()["proposed_action"] == "create_case"
    assert response.json()["mutated"] is False
    assert repo.cases == {}


def _token(email: str, role: str) -> str:
    return sign_test_token(
        {
            "email": email,
            "role": role,
            "exp": int(time.time() * 1000) + 60000,
        },
        AUTH_SECRET,
    )


def _request_payload() -> dict:
    return {
        "patient_name": "Asha",
        "blood_group": "O-",
        "units": 1,
        "hospital": "Doon Hospital",
        "city": "Dehradun",
        "deadline": "2026-06-10",
        "urgency": "critical",
    }
