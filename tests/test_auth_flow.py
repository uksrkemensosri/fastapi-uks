import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Pakai DB test terpisah agar tidak menyentuh database utama project.
TEST_DB_PATH = Path("test_emr_keperawatan.db")
if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()

os.environ["DATABASE_URL"] = "sqlite:///./test_emr_keperawatan.db"
os.environ["SECRET_KEY"] = "test-secret-key-min-32-chars-123456"
os.environ["ACCESS_TOKEN_EXPIRE_SECONDS"] = "1800"

from app.main import app  # noqa: E402
from app.db.database import engine  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

    engine.dispose()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


def _auth_headers(client: TestClient) -> dict:
    login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_login_returns_expiry(client: TestClient):
    res = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert res.status_code == 200
    payload = res.json()
    assert payload["token_type"] == "bearer"
    assert isinstance(payload["access_token"], str) and len(payload["access_token"]) > 20
    assert payload["expires_in"] == 1800


def test_auth_me_and_refresh(client: TestClient):
    headers = _auth_headers(client)

    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["username"] == "admin"

    refresh = client.post("/api/auth/refresh", headers=headers)
    assert refresh.status_code == 200
    refreshed = refresh.json()
    assert refreshed["token_type"] == "bearer"
    assert refreshed["expires_in"] == 1800


def test_invalid_token_detail(client: TestClient):
    res = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-valid-token"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid token"


def test_register_role_normalization_and_access(client: TestClient):
    reg = client.post(
        "/api/auth/register",
        json={
            "username": "PerawatRoleTest",
            "full_name": "Perawat Role Test",
            "role": "PerAWat",
            "password": "rahasia123",
        },
    )
    assert reg.status_code == 201
    assert reg.json()["role"] == "perawat"

    login = client.post(
        "/api/auth/login",
        json={"username": "PerawatRoleTest", "password": "rahasia123"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    patients = client.get("/api/patients", headers=headers)
    assert patients.status_code == 200


def test_create_and_search_patient(client: TestClient):
    headers = _auth_headers(client)

    create = client.post(
        "/api/patients",
        headers=headers,
        json={"id": "SISWA-001", "name": "Budi Santoso", "age": 12, "gender": "L", "class_name": "7A"},
    )
    assert create.status_code == 201
    assert create.json()["id"] == "SISWA-001"
    assert create.json()["class_name"] == "7A"

    detail = client.get("/api/patients/SISWA-001", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["class_name"] == "7A"


def test_create_and_list_uks_visits(client: TestClient):
    headers = _auth_headers(client)

    create = client.post(
        "/api/uks/visits",
        headers=headers,
        json={
            "patient_id": "SISWA-001",
            "visit_date": "2026-05-17",
            "complaint": "Pusing saat upacara",
            "examination": "Tekanan darah normal, suhu normal",
            "treatment": "Istirahat dan minum air",
            "diagnosis": "Nyeri akut",
            "notes": "Observasi 20 menit",
            "referral_to": None,
            "referral_status": None,
        },
    )
    assert create.status_code == 201
    assert create.json()["diagnosis"] == "Nyeri akut"


def test_excel_daily_report(client: TestClient):
    headers = _auth_headers(client)
    res = client.get("/api/reports/uks/daily/excel?date=2026-05-17", headers=headers)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert "attachment; filename=\"laporan_harian_uks_2026-05-17.xlsx\"" in res.headers["content-disposition"]


def test_ai_suggest_care(client: TestClient):
    headers = _auth_headers(client)
    res = client.post(
        "/api/ai/suggest-care",
        headers=headers,
        json={
            "complaint": "pusing dan lemas",
            "examination": "suhu normal, tampak lemah",
        },
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["diagnosis"]
    assert payload["intervention"]
    assert payload["implementation"]
    assert payload["follow_up"]


def test_health_and_ui_endpoint(client: TestClient):
    health = client.get("/health")
    assert health.status_code == 200

    ui = client.get("/ui")
    assert ui.status_code == 200
    assert "EMR UKS Sekolah Rakyat" in ui.text


def test_medicine_inventory_and_stock_deduction(client: TestClient):
    headers = _auth_headers(client)

    create_medicine = client.post(
        "/api/medicines",
        headers=headers,
        json={
            "name": "Paracetamol 500mg",
            "unit": "tablet",
            "stock": 20,
            "minimum_stock": 5,
        },
    )
    assert create_medicine.status_code == 201
    medicine_id = create_medicine.json()["id"]

    low_stock_attempt = client.post(
        "/api/uks/visits/1/medications",
        headers=headers,
        json={
            "medicine_name": "Paracetamol 500mg",
            "dosage": "3x1",
            "quantity": 25,
            "notes": "Sesudah makan",
        },
    )
    assert low_stock_attempt.status_code == 400
    assert "Insufficient stock" in low_stock_attempt.json()["detail"]

    consume = client.post(
        "/api/uks/visits/1/medications",
        headers=headers,
        json={
            "medicine_name": "Paracetamol 500mg",
            "dosage": "3x1",
            "quantity": 4,
            "notes": "Sesudah makan",
        },
    )
    assert consume.status_code == 201
    assert consume.json()["remaining_stock"] == 16

    medicines = client.get("/api/medicines", headers=headers)
    assert medicines.status_code == 200
    med = next((m for m in medicines.json() if m["id"] == medicine_id), None)
    assert med is not None
    assert med["stock"] == 16
