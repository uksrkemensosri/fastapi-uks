import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TEST_DB_PATH = Path("test_emr_keperawatan.db")
if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()

os.environ["DATABASE_URL"] = "sqlite:///./test_emr_keperawatan.db"
os.environ["SECRET_KEY"] = "test-secret-key-min-32-chars-123456"
os.environ["ACCESS_TOKEN_EXPIRE_SECONDS"] = "1800"
os.environ["FONNTE_TOKEN"] = ""
os.environ["FONNTE_GROUP_ID"] = ""

from app.db.database import engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
