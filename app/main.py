from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import settings  # noqa: F401
from app.api.routes import router
from app.auth.security import hash_password
from app.db import models  # noqa: F401
from app.db.database import Base, SessionLocal, engine
from app.db.models import PatientORM
from app.db.models import UserORM

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None

app = FastAPI(title="EMR Keperawatan + Expert System NANDA-NIC-NOC")
app.include_router(router)

Base.metadata.create_all(bind=engine)
def ensure_sqlite_columns() -> None:

    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as conn:

        visit_cols = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info(uks_visits)")
            ).fetchall()
        }

        if "diagnosis" not in visit_cols:
            conn.execute(
                text(
                    "ALTER TABLE uks_visits ADD COLUMN diagnosis VARCHAR(255)"
                )
            )

        if "referral_place" not in visit_cols:
            conn.execute(
                text(
                    "ALTER TABLE uks_visits ADD COLUMN referral_place VARCHAR(255)"
                )
            )

        if "control_date" not in visit_cols:
            conn.execute(
                text(
                    "ALTER TABLE uks_visits ADD COLUMN control_date DATE"
                )
            )

        if "referral_status" not in visit_cols:
            conn.execute(
                text(
                    "ALTER TABLE uks_visits ADD COLUMN referral_status VARCHAR(50)"
                )
            )
ensure_sqlite_columns()

UI_INDEX_PATH = Path(__file__).resolve().parent / "ui" / "index.html"
UI_LOGIN_PATH = Path(__file__).resolve().parent / "ui" / "login.html"
UI_STUDENTS_PATH = Path(__file__).resolve().parent / "ui" / "students.html"
UI_SETTINGS_PATH = Path(__file__).resolve().parent / "ui" / "settings.html"
UI_REPORTS_PATH = Path(__file__).resolve().parent / "ui" / "reports.html"
UI_USERS_PATH = Path(__file__).resolve().parent / "ui" / "users.html"
UI_ASSETS_PATH = Path(__file__).resolve().parent / "ui" / "assets"

app.mount("/ui/assets", StaticFiles(directory=UI_ASSETS_PATH), name="ui-assets")


def ensure_sqlite_columns() -> None:
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as conn:
        patient_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(patients)")).fetchall()}
        if "class_name" not in patient_cols:
            conn.execute(text("ALTER TABLE patients ADD COLUMN class_name VARCHAR(50)"))

        visit_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(uks_visits)")).fetchall()}
        if "diagnosis" not in visit_cols:
            conn.execute(text("ALTER TABLE uks_visits ADD COLUMN diagnosis VARCHAR(255)"))


def seed_admin_user() -> None:
    db: Session = SessionLocal()
    try:
        admin = db.query(UserORM).filter(UserORM.username == "admin").first()
        if admin is None:
            db.add(
                UserORM(
                    username="admin",
                    full_name="Administrator",
                    role="admin",
                    password_hash=hash_password("admin123"),
                    is_active=True,
                )
            )
            db.commit()
    finally:
        db.close()


ensure_sqlite_columns()
def import_students_once() -> None:
    if pd is None:
        return

    db: Session = SessionLocal()

    try:

        existing = db.query(PatientORM).count()

        if existing > 0:
            return

        df = pd.read_excel(
            "students_clean_import.xlsx"
        )

        for _, row in df.iterrows():

            student = PatientORM(
                id=str(row["id"]),
                name=row["name"],
                gender=row["gender"],
                class_name=row["class_name"],
                birth_date=str(row["birth_date"]),
                age=0,
            )

            db.add(student)

        db.commit()

        print("Students imported 😄🔥")

    finally:

        db.close()
seed_admin_user()
import_students_once()


@app.get("/")
def root() -> dict:
    return {"message": "EMR Keperawatan API aktif"}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}

@app.get("/dashboard", response_class=FileResponse)
def dashboard() -> FileResponse:
    return FileResponse(UI_INDEX_PATH)


@app.get("/login", response_class=FileResponse)
def login_page() -> FileResponse:
    return FileResponse(UI_LOGIN_PATH)
@app.get("/students", response_class=FileResponse)
def students_page() -> FileResponse:
    return FileResponse(UI_STUDENTS_PATH)
@app.get("/reports", response_class=FileResponse)
def reports_page() -> FileResponse:
    return FileResponse(UI_REPORTS_PATH)
@app.get("/settings", response_class=FileResponse)
def settings_page() -> FileResponse:
    return FileResponse(UI_SETTINGS_PATH)
@app.get("/users", response_class=FileResponse)
def users_page() -> FileResponse:
    return FileResponse(UI_USERS_PATH)
