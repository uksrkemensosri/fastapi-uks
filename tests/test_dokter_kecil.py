"""Regression coverage for removal of the Dokter Kecil feature."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from app.auth.dependencies import get_current_user
from app.main import app
from app.models.schemas import UserCreate, UserUpdate


def test_retired_routes_are_not_registered():
    assert not any("dokter-kecil" in getattr(route, "path", "") for route in app.routes)


@pytest.mark.parametrize("role", ["dokter_kecil", "Dokter Kecil", "dokter-kecil"])
def test_retired_role_cannot_be_assigned(role):
    with pytest.raises(ValidationError):
        UserCreate(username="student", full_name="Student", password="test-password", role=role)
    with pytest.raises(ValidationError):
        UserUpdate(role=role)


def test_existing_student_session_cannot_access_general_api():
    request = Request({"type": "http", "method": "GET", "path": "/api/auth/me", "session": {"user": {"id": 123}}})
    db = SimpleNamespace(get=lambda *args: SimpleNamespace(is_active=True, role="dokter_kecil"))
    with pytest.raises(HTTPException) as exc:
        get_current_user(request, credentials=None, db=db)
    assert exc.value.status_code == 403
