import time
from fastapi.testclient import TestClient
import pytest
from app.auth import sign_test_token
from app.main import create_app
from app.ml_service import predict_patient_frequency, predict_donor_active_status, train_and_save_models

AUTH_SECRET = "test-secret"

def _token(email: str, role: str) -> str:
    return sign_test_token(
        {
            "email": email,
            "role": role,
            "exp": int(time.time() * 1000) + 60000,
        },
        AUTH_SECRET,
    )

def test_predict_patient_frequency_returns_float() -> None:
    frequency = predict_patient_frequency(
        condition="Thalassemia Major",
        gender="Female",
        quantity_required=2
    )
    assert isinstance(frequency, float)
    assert 5.0 <= frequency <= 60.0

def test_predict_donor_active_status_returns_bool() -> None:
    is_active = predict_donor_active_status(
        gender="Male",
        donor_type="Bridge Donor",
        donations_till_date=3,
        total_calls=2,
        cycle_of_donations=90
    )
    assert isinstance(is_active, bool)

def test_train_and_save_models_updates_files() -> None:
    mock_data = {
        "patients": [
            {"condition": "Thalassemia Major", "gender": "Female", "quantity_required": 2, "frequency_days": 15},
            {"condition": "Sickle Cell Disease", "gender": "Male", "quantity_required": 1, "frequency_days": 21},
            {"condition": "Thalassemia Intermedia", "gender": "Female", "quantity_required": 1, "frequency_days": 30},
            {"condition": "Thalassemia Major", "gender": "Male", "quantity_required": 2, "frequency_days": 14},
            {"condition": "Sickle Cell Disease", "gender": "Female", "quantity_required": 1, "frequency_days": 20},
        ],
        "donors": [
            {"gender": "Male", "donor_type": "Bridge Donor", "donations_till_date": 3, "total_calls": 2, "cycle_of_donations": 90, "active_status": "Active"},
            {"gender": "Female", "donor_type": "Emergency Donor", "donations_till_date": 1, "total_calls": 1, "cycle_of_donations": 90, "active_status": "Active"},
            {"gender": "Male", "donor_type": "Bridge Donor", "donations_till_date": 0, "total_calls": 8, "cycle_of_donations": 90, "active_status": "Inactive"},
            {"gender": "Female", "donor_type": "Bridge Donor", "donations_till_date": 4, "total_calls": 3, "cycle_of_donations": 90, "active_status": "Active"},
            {"gender": "Male", "donor_type": "Emergency Donor", "donations_till_date": 0, "total_calls": 12, "cycle_of_donations": 90, "active_status": "Inactive"},
        ]
    }
    metrics = train_and_save_models(mock_data)
    assert "patient_cycle_model" in metrics
    assert "donor_active_model" in metrics
    assert "trained_at" in metrics
    assert "Accuracy" in metrics["donor_active_model"]

def test_train_api_endpoint(monkeypatch) -> None:
    from app import dependencies
    from tests.fakes import MemoryRepository
    
    monkeypatch.setenv("AUTH_SECRET", AUTH_SECRET)
    app = create_app()
    app.dependency_overrides[dependencies.get_repository] = lambda: MemoryRepository()
    
    client = TestClient(app)
    admin_token = _token("admin@example.com", "admin")
    
    response = client.post(
        "/automation/train",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "metrics" in response.json()

def test_predict_cycle_api_endpoint(monkeypatch) -> None:
    from app import dependencies
    from tests.fakes import MemoryRepository
    
    monkeypatch.setenv("AUTH_SECRET", AUTH_SECRET)
    app = create_app()
    app.dependency_overrides[dependencies.get_repository] = lambda: MemoryRepository()
    
    client = TestClient(app)
    patient_token = _token("patient@example.com", "patient")
    
    payload = {
        "condition": "Thalassemia Major",
        "gender": "Female",
        "quantity_required": 2,
        "last_transfusion_date": "2026-06-01"
    }
    response = client.post(
        "/automation/predict-cycle",
        headers={"Authorization": f"Bearer {patient_token}"},
        json=payload
    )
    assert response.status_code == 200
    data = response.json()
    assert "predicted_frequency_days" in data
    assert "predicted_next_date" in data
    assert data["last_transfusion_date"] == "2026-06-01"
