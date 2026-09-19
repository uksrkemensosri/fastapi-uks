import base64
from io import BytesIO

from openpyxl import Workbook

from test_auth_flow import _auth_headers


def test_nik_import_preserves_identity_and_legacy_import(client):
    headers = _auth_headers(client)

    def upload(nik, include=True):
        wb = Workbook()
        wb.active.append(["NIS", "Nama Lengkap"] + (["NIK"] if include else []))
        wb.active.append(["TEST-NIK-001", "Siswa Uji NIK"] + ([nik] if include else []))
        stream = BytesIO()
        wb.save(stream)
        return client.post("/api/patients/import-excel", headers=headers, json={
            "content_base64": base64.b64encode(stream.getvalue()).decode(),
        })

    result = upload("0000000000000001")
    assert result.status_code == 200, result.text
    assert result.json()["created"] == 1
    for value, include in [(None, True), (None, False), ("0000000000000001", True)]:
        result = upload(value, include)
        assert result.status_code == 200, result.text
        assert result.json()["created"] == 0
        assert result.json()["updated"] == 1
        patient = client.get("/api/patients/TEST-NIK-001", headers=headers)
        assert patient.json()["nik"] == "0000000000000001"
    for invalid in [1234567890123456, "1234", "abcdefghijklmnop"]:
        assert upload(invalid).status_code == 400
    patient = client.get("/api/patients/TEST-NIK-001", headers=headers)
    assert patient.json()["nik"] == "0000000000000001"
