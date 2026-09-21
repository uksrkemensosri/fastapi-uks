from fastapi.testclient import TestClient


def auth_headers(client: TestClient) -> dict:
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_public_complaint_flow_and_staff_follow_up(client: TestClient):
    headers = auth_headers(client)
    patient = client.post(
        "/api/patients",
        headers=headers,
        json={"id": "KELUHAN-001", "name": "Siswa Keluhan", "age": 16, "gender": "P", "class_name": "XI A"},
    )
    assert patient.status_code == 201

    public_page = client.get("/keluhan")
    assert public_page.status_code == 200
    assert "Nama pelapor" in public_page.text
    assert "wali asuh, wali asrama, atau guru" in public_page.text
    search = client.get("/api/public/complaints/students?school=SR-DEMO&q=KELUHAN-001")
    assert search.status_code == 200
    result = search.json()[0]
    assert set(result) == {"selection_token", "name", "class_name"}
    assert result["name"] == "Siswa Keluhan"
    assert "id" not in result and "nik" not in result

    missing_reporter = client.post(
        "/api/public/complaints",
        json={"selection_token": result["selection_token"], "complaint": "Pusing sejak pagi"},
    )
    assert missing_reporter.status_code == 422

    created = client.post(
        "/api/public/complaints",
        json={
            "selection_token": result["selection_token"],
            "reporter_name": "  Ibu   Wali Asrama  ",
            "complaint": "Pusing sejak pagi",
        },
    )
    assert created.status_code == 201
    complaint_id = created.json()["id"]
    assert created.json()["status"] == "MENUNGGU"
    assert client.get("/api/complaints/pending-count", headers=headers).json()["count"] == 1

    listed = client.get("/api/complaints", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["reporter_name"] == "Ibu Wali Asrama"

    followed_up = client.post(f"/api/complaints/{complaint_id}/follow-up", headers=headers)
    assert followed_up.status_code == 200
    assert followed_up.json()["status"] == "DITINDAKLANJUTI"
    assert followed_up.json()["handled_by"] is not None

    prefill = client.get(f"/api/complaints/{complaint_id}/visit-prefill", headers=headers)
    assert prefill.status_code == 200
    assert prefill.json()["patient_id"] == "KELUHAN-001"
    assert prefill.json()["complaint"] == "Pusing sejak pagi"

    assert client.get("/api/complaints/qr.svg", headers=headers).headers["content-type"].startswith("image/svg+xml")
    assert client.get("/api/complaints/qr.png", headers=headers).headers["content-type"].startswith("image/png")
