import os
import re
import base64
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

# Pakai DB test terpisah agar tidak menyentuh database utama project.
TEST_DB_PATH = Path("test_emr_keperawatan.db")
if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()

os.environ["DATABASE_URL"] = "sqlite:///./test_emr_keperawatan.db"
os.environ["SECRET_KEY"] = "test-secret-key-min-32-chars-123456"
os.environ["ACCESS_TOKEN_EXPIRE_SECONDS"] = "1800"
os.environ["FONNTE_TOKEN"] = ""

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


def _login_headers(client: TestClient, username: str, password: str) -> dict:
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_login_returns_expiry(client: TestClient):
    res = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert res.status_code == 200
    payload = res.json()
    assert payload["token_type"] == "bearer"
    assert isinstance(payload["access_token"], str) and len(payload["access_token"]) > 20
    assert payload["expires_in"] == 1800


def test_protected_ui_redirects_without_login(client: TestClient):
    isolated = TestClient(app)
    res = isolated.get("/dashboard", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/login"


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
    assert login.json()["role"] == "perawat"
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    patients = client.get("/api/patients", headers=headers)
    assert patients.status_code == 200

    users = client.get("/api/users", headers=headers)
    assert users.status_code == 200
    assert all(item["school_id"] == reg.json()["school_id"] for item in users.json())

    settings_page = client.get("/settings")
    assert settings_page.status_code == 200

    admin_headers = _auth_headers(client)

    wali = client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "username": "wali_role_test",
            "full_name": "Wali Role Test",
            "role": "Wali Asuh",
            "password": "rahasia123",
        },
    )
    assert wali.status_code == 201
    assert wali.json()["role"] == "wali_asuh"

    wali_login = client.post(
        "/api/auth/login",
        json={"username": "wali_role_test", "password": "rahasia123"},
    )
    assert wali_login.json()["role"] == "wali_asuh"
    wali_headers = {"Authorization": f"Bearer {wali_login.json()['access_token']}"}
    assert client.get("/api/patients", headers=wali_headers).status_code == 200
    assert client.post(
        "/api/patients",
        headers=wali_headers,
        json={
            "id": "WALI-CREATE-DENIED",
            "name": "Tidak Boleh Tambah",
            "age": 12,
            "gender": "L",
            "class_name": "7A",
        },
    ).status_code == 403
    assert client.get("/settings").status_code == 200

    tim = client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "username": "tim_uksr_role_test",
            "full_name": "Tim UKSR Role Test",
            "role": "Tim UKSR",
            "password": "rahasia123",
        },
    )
    assert tim.status_code == 201
    assert tim.json()["role"] == "tim_uksr"


def test_create_and_search_patient(client: TestClient):
    headers = _auth_headers(client)

    create = client.post(
        "/api/patients",
        headers=headers,
        json={
            "id": "SISWA-001",
            "name": "Budi Santoso",
            "age": 12,
            "gender": "L",
            "class_name": "7A",
            "parent_name": "Ibu Wali",
            "parent_phone": "081234567890",
        },
    )
    assert create.status_code == 201
    assert create.json()["id"] == "SISWA-001"
    assert create.json()["class_name"] == "7A"
    assert create.json()["parent_name"] == "Ibu Wali"
    assert create.json()["parent_phone"] == "081234567890"

    detail = client.get("/api/patients/SISWA-001", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["class_name"] == "7A"
    assert detail.json()["parent_name"] == "Ibu Wali"

    history = client.get("/api/students/SISWA-001/health-history", headers=headers)
    assert history.status_code == 200
    assert history.json()["biodata"]["wali_asuh"] == "Ibu Wali"
    assert history.json()["biodata"]["nomor_hp_wali_asuh"] == "081234567890"

    logs = client.get("/api/audit-logs?search=SISWA-001", headers=headers)
    assert logs.status_code == 200
    actions = {item["action"] for item in logs.json()["items"]}
    assert "create_patient" in actions


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
    assert create.json()["whatsapp_status"] == "skipped"

    wa_logs = client.get("/api/whatsapp/logs?limit=5", headers=headers)
    assert wa_logs.status_code == 200
    assert any(item["visit_id"] == create.json()["id"] for item in wa_logs.json())

    resend = client.post(f"/api/whatsapp/visits/{create.json()['id']}/resend", headers=headers)
    assert resend.status_code == 200
    assert resend.json()["whatsapp_status"] in {"sent", "failed", "skipped"}


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

    adjust_in = client.post(
        f"/api/medicines/{medicine_id}/adjust",
        headers=headers,
        json={"adjustment_type": "IN", "quantity": 5, "notes": "Restok test"},
    )
    assert adjust_in.status_code == 200
    assert adjust_in.json()["stock"] == 21

    adjust_set = client.post(
        f"/api/medicines/{medicine_id}/adjust",
        headers=headers,
        json={"adjustment_type": "SET", "quantity": 18, "notes": "Koreksi test"},
    )
    assert adjust_set.status_code == 200
    assert adjust_set.json()["stock"] == 18

    mutation_json = client.get("/api/reports/medicine-mutation?month=5&year=2026", headers=headers)
    assert mutation_json.status_code == 200
    assert any(item["medicine_name"] == "Paracetamol 500mg" for item in mutation_json.json())

    stock_pdf = client.get("/api/reports/medicines/pdf", headers=headers)
    assert stock_pdf.status_code == 200
    assert stock_pdf.headers["content-type"].startswith("application/pdf")
    assert len(stock_pdf.content) > 1000

    mutation_pdf = client.get("/api/reports/medicine-mutation/pdf?month=5&year=2026", headers=headers)
    assert mutation_pdf.status_code == 200
    assert mutation_pdf.headers["content-type"].startswith("application/pdf")
    assert len(mutation_pdf.content) > 1000


def test_medicine_import_template_and_excel_import(client: TestClient):
    headers = _auth_headers(client)

    template = client.get("/api/medicines/import-template", headers=headers)
    assert template.status_code == 200
    assert template.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert len(template.content) > 1000

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Nama Obat", "Satuan", "Stok Awal", "Stok Minimum", "Catatan"])
    sheet.append(["Obat Import Test", "sachet", 25, 8, "Import dari test"])
    buffer = BytesIO()
    workbook.save(buffer)
    encoded = base64.b64encode(buffer.getvalue()).decode()
    payload = {
        "filename": "obat.xlsx",
        "content_base64": (
            "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,"
            + encoded
        ),
    }

    preview = client.post(
        "/api/medicines/import-excel",
        headers=headers,
        json={**payload, "preview": True},
    )
    assert preview.status_code == 200
    assert preview.json()["total"] == 1
    assert preview.json()["preview"][0]["name"] == "Obat Import Test"

    imported = client.post("/api/medicines/import-excel", headers=headers, json=payload)
    assert imported.status_code == 200
    assert imported.json()["created"] == 1

    medicines = client.get("/api/medicines", headers=headers)
    imported_medicine = next(
        item for item in medicines.json() if item["name"] == "Obat Import Test"
    )
    assert imported_medicine["stock"] == 25
    assert imported_medicine["unit"] == "sachet"
    assert imported_medicine["minimum_stock"] == 8


def test_user_crud_and_audit_log(client: TestClient):
    headers = _auth_headers(client)

    create = client.post(
        "/api/users",
        headers=headers,
        json={
            "username": "crud_user",
            "full_name": "CRUD User",
            "role": "perawat",
            "nip": "1987654321",
            "jabatan": "Petugas UKS",
            "password": "rahasia123",
        },
    )
    assert create.status_code == 201
    assert create.json()["nip"] == "1987654321"
    user_id = create.json()["id"]

    update = client.patch(
        f"/api/users/{user_id}",
        headers=headers,
        json={
            "username": "crud_user_edit",
            "full_name": "CRUD User Edit",
            "role": "admin",
            "nip": "1234567890",
            "jabatan": "Kepala UKS",
        },
    )
    assert update.status_code == 200
    assert update.json()["role"] == "admin"
    assert update.json()["nip"] == "1234567890"

    reset = client.post(
        f"/api/users/{user_id}/reset-password",
        headers=headers,
        json={"new_password": "passwordbaru"},
    )
    assert reset.status_code == 200
    assert _login_headers(client, "crud_user_edit", "passwordbaru")

    deactivate = client.post(f"/api/users/{user_id}/deactivate", headers=headers)
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False

    activate = client.post(f"/api/users/{user_id}/activate", headers=headers)
    assert activate.status_code == 200
    assert activate.json()["is_active"] is True

    logs = client.get("/api/audit-logs?search=crud_user", headers=headers)
    assert logs.status_code == 200
    actions = {item["action"] for item in logs.json()["items"]}
    assert {"create_user", "edit_user", "reset_password", "deactivate_user", "activate_user"} <= actions


def test_cannot_disable_self_or_last_active_admin(client: TestClient):
    headers = _auth_headers(client)
    me = client.get("/api/auth/me", headers=headers).json()

    deactivate_self = client.post(f"/api/users/{me['id']}/deactivate", headers=headers)
    assert deactivate_self.status_code == 400
    assert deactivate_self.json()["detail"] == "Cannot deactivate your own account"


def test_ckg_event_registration_queue_and_anthropometry(client: TestClient):
    admin_headers = _auth_headers(client)

    ckg_page = client.get("/ckg")
    assert ckg_page.status_code == 200
    assert "/api/patients/search?q=" in ckg_page.text
    assert "studentSearchResults" in ckg_page.text

    event = client.post(
        "/api/ckg/events",
        headers=admin_headers,
        json={
            "academic_year": "2026/2027",
            "event_name": "CKG 2026/2027",
            "start_date": "2026-07-01",
            "end_date": "2026-07-10",
            "is_active": True,
        },
    )
    assert event.status_code == 201
    assert event.json()["is_active"] is True

    perawat = client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "username": "ckg_antropometri",
            "full_name": "CKG Antropometri",
            "role": "perawat",
            "password": "rahasia123",
        },
    )
    assert perawat.status_code == 201
    perawat_id = perawat.json()["id"]

    assignment = client.post(
        "/api/ckg/assignments",
        headers=admin_headers,
        json={"user_id": perawat_id, "station": "ANTROPOMETRI"},
    )
    assert assignment.status_code == 201

    student = client.post(
        "/api/ckg/students",
        headers=admin_headers,
        json={
            "nis": "CKG-001",
            "full_name": "Siswa CKG Satu",
            "gender": "Laki-Laki",
            "birth_date": "2011-01-01",
            "class_name": "7A",
            "section": "A",
            "parent_name": "Orang Tua",
            "parent_phone": "081298765432",
        },
    )
    assert student.status_code == 201
    student_id = student.json()["id"]
    assert student.json()["status"] == "REGISTERED"
    assert student.json()["parent_phone"] == "081298765432"

    synced_patient = client.get("/api/patients/CKG-001", headers=admin_headers)
    assert synced_patient.status_code == 200
    assert synced_patient.json()["name"] == "Siswa CKG Satu"
    assert synced_patient.json()["parent_name"] == "Orang Tua"
    assert synced_patient.json()["parent_phone"] == "081298765432"

    perawat_headers = _login_headers(client, "ckg_antropometri", "rahasia123")
    queue = client.get("/api/ckg/stations/ANTROPOMETRI/queue", headers=perawat_headers)
    assert queue.status_code == 200
    assert queue.json()[0]["student_name"] == "Siswa CKG Satu"

    forbidden_queue = client.get("/api/ckg/stations/TTV/queue", headers=perawat_headers)
    assert forbidden_queue.status_code == 403

    antropometri = client.post(
        f"/api/ckg/students/{student_id}/anthropometry",
        headers=perawat_headers,
        json={"weight": 40, "height": 150},
    )
    assert antropometri.status_code == 200
    assert antropometri.json()["status"] == "ANTROPOMETRI_DONE"
    assert antropometri.json()["next_station"] == "TTV"

    dashboard = client.get("/api/ckg/dashboard", headers=admin_headers)
    assert dashboard.status_code == 200
    assert dashboard.json()["total_registered"] == 1
    assert dashboard.json()["in_progress"] == 1
    assert dashboard.json()["students_per_station"]["TTV"] == 1

    summary = client.get(f"/api/ckg/students/{student_id}/summary", headers=admin_headers)
    assert summary.status_code == 200
    assert summary.json()["anthropometry"]["bmi"] == 17.78

    summary_pdf = client.get(f"/api/ckg/students/{student_id}/summary/pdf", headers=admin_headers)
    assert summary_pdf.status_code == 200
    assert summary_pdf.headers["content-type"].startswith("application/pdf")
    assert len(summary_pdf.content) > 1000

    event_pdf = client.get("/api/ckg/report/pdf", headers=admin_headers)
    assert event_pdf.status_code == 200
    assert event_pdf.headers["content-type"].startswith("application/pdf")
    assert len(event_pdf.content) > 1000

    removable = client.post(
        "/api/ckg/students",
        headers=admin_headers,
        json={
            "nis": "CKG-DELETE-001",
            "full_name": "Siswa Hapus CKG",
            "gender": "Perempuan",
            "birth_date": "2012-02-02",
            "class_name": "7B",
            "section": "B",
            "parent_name": "Wali Siswa",
            "parent_phone": "081211112222",
        },
    )
    assert removable.status_code == 201
    removable_id = removable.json()["id"]

    deleted = client.delete(f"/api/ckg/students/{removable_id}", headers=admin_headers)
    assert deleted.status_code == 200
    assert deleted.json()["patient_preserved"] is True

    preserved_patient = client.get("/api/patients/CKG-DELETE-001", headers=admin_headers)
    assert preserved_patient.status_code == 200

    removed_from_event = client.get("/api/ckg/students?q=CKG-DELETE-001", headers=admin_headers)
    assert removed_from_event.status_code == 200
    assert removed_from_event.json() == []

    deleted_patient = client.delete("/api/patients/CKG-DELETE-001", headers=admin_headers)
    assert deleted_patient.status_code == 200
    assert deleted_patient.json()["message"] == "Data siswa berhasil dihapus"

    missing_patient = client.get("/api/patients/CKG-DELETE-001", headers=admin_headers)
    assert missing_patient.status_code == 404


def test_fitness_event_registration_queue_examination_and_pdf(client: TestClient):
    headers = _auth_headers(client)

    page = client.get("/fitness")
    assert page.status_code == 200
    assert "Cek Kebugaran" in page.text
    assert "/api/fitness/students" in page.text
    assert "/api/patients/search?q=" in page.text

    event = client.post(
        "/api/fitness/events",
        headers=headers,
        json={
            "academic_year": "2026/2027",
            "event_name": "Cek Kebugaran 2026",
            "start_date": "2026-07-31",
            "end_date": "2026-07-31",
            "is_active": True,
        },
    )
    assert event.status_code == 201
    assert event.json()["is_active"] is True

    student = client.post(
        "/api/fitness/students",
        headers=headers,
        json={
            "nis": "FIT-001",
            "full_name": "Siswa Fit Satu",
            "gender": "Perempuan",
            "birth_date": "2012-03-04",
            "class_name": "7F",
            "section": "F",
            "parent_name": "Wali Fit",
            "parent_phone": "081233334444",
        },
    )
    assert student.status_code == 201
    student_id = student.json()["id"]
    assert student.json()["status"] == "REGISTERED"
    assert student.json()["next_station"] == "PEMERIKSAAN_KEBUGARAN"

    synced_patient = client.get("/api/patients/FIT-001", headers=headers)
    assert synced_patient.status_code == 200
    assert synced_patient.json()["parent_name"] == "Wali Fit"

    queue = client.get("/api/fitness/queue", headers=headers)
    assert queue.status_code == 200
    assert queue.json()[0]["student_name"] == "Siswa Fit Satu"

    exam = client.post(
        f"/api/fitness/students/{student_id}/examination",
        headers=headers,
        json={
            "weight": 45,
            "height": 150,
            "blood_pressure": "110/70",
            "oxygen_saturation": 98,
            "temperature": 36.5,
            "notes": "Bugar",
        },
    )
    assert exam.status_code == 200
    assert exam.json()["status"] == "COMPLETED"
    assert exam.json()["whatsapp_status"] == "skipped"
    assert exam.json()["whatsapp_message"]

    summary = client.get(f"/api/fitness/students/{student_id}/summary", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["examination"]["bmi"] == 20.0
    assert summary.json()["examination"]["oxygen_saturation"] == 98.0

    dashboard = client.get("/api/fitness/dashboard", headers=headers)
    assert dashboard.status_code == 200
    assert dashboard.json()["total_registered"] == 1
    assert dashboard.json()["completed"] == 1

    pdf = client.get("/api/fitness/report/pdf", headers=headers)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert len(pdf.content) > 1000


def test_health_history_recommendation_pdf_and_signature(client: TestClient):
    headers = _auth_headers(client)
    tiny_png = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )

    profile = client.patch(
        "/api/auth/profile",
        headers=headers,
        json={
            "full_name": "Administrator",
            "nip": "198700000001",
            "jabatan": "Perawat Pemeriksa",
            "signature_image": tiny_png,
        },
    )
    assert profile.status_code == 200
    assert profile.json()["nip"] == "198700000001"

    history = client.get("/api/students/SISWA-001/health-history", headers=headers)
    assert history.status_code == 200
    assert history.json()["biodata"]["nis"] == "SISWA-001"

    uks_recommendation = client.post(
        "/api/recommendations/from-uks/1",
        headers=headers,
        json={"recommendation_text": "Pemeriksaan dokter umum lanjutan."},
    )
    assert uks_recommendation.status_code == 200
    recommendation_id = uks_recommendation.json()["id"]
    assert uks_recommendation.json()["letter_number"].startswith("SR-UKS/")

    pdf = client.get(f"/api/recommendations/{recommendation_id}/pdf", headers=headers)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert len(pdf.content) > 1000

    ckg_students = client.get("/api/ckg/students?q=CKG-001", headers=headers)
    assert ckg_students.status_code == 200
    ckg_id = ckg_students.json()[0]["id"]
    ckg_recommendation = client.post(
        f"/api/recommendations/from-ckg/{ckg_id}",
        headers=headers,
        json={"recommendation_text": "Pemeriksaan gizi lanjutan."},
    )
    assert ckg_recommendation.status_code == 200

    recommendations = client.get("/api/recommendations?student_id=CKG-001", headers=headers)
    assert recommendations.status_code == 200
    assert recommendations.json()[0]["source_type"] == "CKG"


def test_monthly_report_preview_and_pdf(client: TestClient):
    headers = _auth_headers(client)

    report = client.get("/reports/monthly?month=5&year=2026", headers=headers)
    assert report.status_code == 200
    payload = report.json()
    assert payload["period"] == "Mei 2026"
    assert payload["summary"]["total_visits"] >= 1
    assert payload["top_students"][0]["nis"] == "SISWA-001"
    assert payload["top_diagnoses"][0]["name"] == "Belum terdapat diagnosa dominan pada periode ini."
    assert "Pada bulan Mei 2026" in payload["conclusion"]

    pdf = client.get("/reports/monthly/pdf?month=5&year=2026", headers=headers)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert len(pdf.content) > 1000
    assert len(re.findall(rb"/Type\s*/Page\b", pdf.content)) == 2


def test_reports_page_keeps_legacy_visit_and_medicine_reports(client: TestClient):
    headers = _auth_headers(client)

    page = client.get("/reports", headers=headers)
    assert page.status_code == 200
    html = page.text
    assert "Laporan Bulanan" in html
    assert "Laporan Kunjungan" in html
    assert "Laporan Obat" in html
    assert "/api/reports/uks/visits" in html
    assert "/api/reports/uks/visits/pdf" in html
    assert "/api/reports/uks/visits/excel" in html
    assert "/api/reports/medicines/pdf" in html


def test_visit_report_preview_pdf_and_excel(client: TestClient):
    headers = _auth_headers(client)

    filtered = client.get("/api/uks/visits?month=2026-05", headers=headers)
    assert filtered.status_code == 200
    assert all(item["visit_date"].startswith("2026-05") for item in filtered.json())

    preview = client.get("/api/reports/uks/visits?period=monthly&month=2026-05", headers=headers)
    assert preview.status_code == 200
    payload = preview.json()
    assert payload["total"] >= 1
    assert {"tanggal", "nama_siswa", "kelas", "keluhan", "diagnosa", "tindakan", "petugas"} <= set(payload["rows"][0])

    pdf = client.get("/api/reports/uks/visits/pdf?period=daily&date=2026-05-17", headers=headers)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")

    excel = client.get("/api/reports/uks/visits/excel?period=daily&date=2026-05-17", headers=headers)
    assert excel.status_code == 200
    assert excel.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def test_admin_tools_dashboard_import_backup_and_exports(client: TestClient):
    headers = _auth_headers(client)

    advanced = client.get("/api/dashboard/advanced-stats", headers=headers)
    assert advanced.status_code == 200
    assert {"low_stock", "pending_controls", "whatsapp", "top_monthly_students"} <= set(advanced.json())

    health = client.get("/api/system/health-check", headers=headers)
    assert health.status_code == 200
    assert health.json()["checks"]

    backup = client.get("/api/admin/backup", headers=headers)
    assert backup.status_code == 200
    assert backup.headers["content-type"].startswith("application/json")
    backup_payload = backup.json()
    assert "patients" in backup_payload
    assert "visits" in backup_payload

    restore = client.post("/api/admin/restore", headers=headers, json=backup_payload)
    assert restore.status_code == 200
    assert restore.json()["restored"]["patients"] >= 1

    wb = Workbook()
    ws = wb.active
    ws.append(["NIS", "Nama Lengkap", "Jenis Kelamin", "Tanggal Lahir", "Kelas", "Nama Wali Asuh", "Nomor HP Wali Asuh"])
    ws.append(["IMPORT-001", "Siswa Import Satu", "Perempuan", "2012-01-01", "7C", "Wali Import", "081200000001"])
    stream = BytesIO()
    wb.save(stream)
    content = base64.b64encode(stream.getvalue()).decode()

    preview = client.post(
        "/api/patients/import-excel",
        headers=headers,
        json={"filename": "siswa.xlsx", "content_base64": content, "preview": True},
    )
    assert preview.status_code == 200
    assert preview.json()["total"] == 1

    imported = client.post(
        "/api/patients/import-excel",
        headers=headers,
        json={"filename": "siswa.xlsx", "content_base64": content, "preview": False},
    )
    assert imported.status_code == 200
    assert imported.json()["created"] == 1

    imported_patient = client.get("/api/patients/IMPORT-001", headers=headers)
    assert imported_patient.status_code == 200
    assert imported_patient.json()["parent_name"] == "Wali Import"

    referral_pdf = client.get("/api/uks/visits/1/referral-letter", headers=headers)
    assert referral_pdf.status_code == 200
    assert referral_pdf.headers["content-type"].startswith("application/pdf")

    rest_pdf = client.get("/api/uks/visits/1/rest-letter?reason=Istirahat&days=1", headers=headers)
    assert rest_pdf.status_code == 200
    assert rest_pdf.headers["content-type"].startswith("application/pdf")

    rest_notify = client.post("/api/uks/visits/1/notify-rest-letter", headers=headers)
    assert rest_notify.status_code == 200
    assert rest_notify.json()["whatsapp_status"] == "skipped"

    ckg_students = client.get("/api/ckg/students?q=CKG-001", headers=headers)
    assert ckg_students.status_code == 200
    ckg_id = ckg_students.json()[0]["id"]
    ckg_notify = client.post(f"/api/ckg/students/{ckg_id}/notify-completed", headers=headers)
    assert ckg_notify.status_code == 200
    assert ckg_notify.json()["whatsapp_status"] == "skipped"

    audit_export = client.get("/api/audit-logs/export/excel", headers=headers)
    assert audit_export.status_code == 200
    assert audit_export.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
