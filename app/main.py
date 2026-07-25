import base64
import hashlib
import hmac
import json
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import settings  # noqa: F401
from app.api.ckg import router as ckg_router
from app.api.monthly_reports import router as monthly_reports_router
from app.api.recommendations import router as recommendations_router
from app.api.routes import router
from app.auth.security import hash_password
from app.auth.tenant import get_default_school
from app.db import models  # noqa: F401
from app.db.database import Base, SessionLocal, engine
from app.db.models import PatientORM
from app.db.models import SchoolORM
from app.db.models import UserORM

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None

SESSION_COOKIE_NAME = "emr_session"
SESSION_SECRET = os.getenv("SECRET_KEY", "dev-secret-key-change-me").encode("utf-8")


def encode_session(data: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode()
    signature = hmac.new(SESSION_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def decode_session(value: str | None) -> dict:
    if not value or "." not in value:
        return {}
    payload, signature = value.rsplit(".", 1)
    expected = hmac.new(SESSION_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return {}
    try:
        return json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
    except Exception:
        return {}


app = FastAPI(title="EMR Keperawatan + Expert System NANDA-NIC-NOC")


@app.middleware("http")
async def signed_session_middleware(request: Request, call_next):
    request.scope["session"] = decode_session(request.cookies.get(SESSION_COOKIE_NAME))
    response = await call_next(request)
    session_data = request.scope.get("session", {})
    if session_data:
        response.set_cookie(
            SESSION_COOKIE_NAME,
            encode_session(session_data),
            httponly=True,
            samesite="lax",
            secure=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
            max_age=60 * 60 * 8,
        )
    else:
        response.delete_cookie(SESSION_COOKIE_NAME)
    return response


app.include_router(router)
app.include_router(ckg_router)
app.include_router(monthly_reports_router)
app.include_router(recommendations_router)

Base.metadata.create_all(bind=engine)


def ensure_database_columns() -> None:
    tenant_tables = [
        "users",
        "audit_logs",
        "recommendation_letters",
        "ckg_events",
        "ckg_students",
        "ckg_station_assignments",
        "ckg_anthropometry",
        "ckg_ttv",
        "ckg_vision",
        "ckg_dental",
        "ckg_general_screening",
        "ckg_referrals",
        "patients",
        "assessments",
        "recommendations",
        "uks_visits",
        "uks_medications",
        "medicine_inventory",
        "school_settings",
        "medicine_transactions",
    ]
    if engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            user_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()}
            if "created_at" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN created_at DATETIME"))
            if "updated_at" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN updated_at DATETIME"))
            if "nip" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN nip VARCHAR(50)"))
            if "jabatan" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN jabatan VARCHAR(100)"))
            if "signature_image" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN signature_image TEXT"))
            if "school_id" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN school_id INTEGER"))

            patient_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(patients)")).fetchall()}
            if "class_name" not in patient_cols:
                conn.execute(text("ALTER TABLE patients ADD COLUMN class_name VARCHAR(50)"))
            if "parent_name" not in patient_cols:
                conn.execute(text("ALTER TABLE patients ADD COLUMN parent_name VARCHAR(200)"))
            if "parent_phone" not in patient_cols:
                conn.execute(text("ALTER TABLE patients ADD COLUMN parent_phone VARCHAR(30)"))
            if "school_id" not in patient_cols:
                conn.execute(text("ALTER TABLE patients ADD COLUMN school_id INTEGER"))

            visit_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(uks_visits)")).fetchall()}
            if "diagnosis" not in visit_cols:
                conn.execute(text("ALTER TABLE uks_visits ADD COLUMN diagnosis VARCHAR(255)"))
            if "referral_place" not in visit_cols:
                conn.execute(text("ALTER TABLE uks_visits ADD COLUMN referral_place VARCHAR(255)"))
            if "control_date" not in visit_cols:
                conn.execute(text("ALTER TABLE uks_visits ADD COLUMN control_date DATE"))
            if "referral_status" not in visit_cols:
                conn.execute(text("ALTER TABLE uks_visits ADD COLUMN referral_status VARCHAR(50)"))
            if "whatsapp_status" not in visit_cols:
                conn.execute(text("ALTER TABLE uks_visits ADD COLUMN whatsapp_status VARCHAR(30)"))
            if "whatsapp_message" not in visit_cols:
                conn.execute(text("ALTER TABLE uks_visits ADD COLUMN whatsapp_message TEXT"))
            if "school_id" not in visit_cols:
                conn.execute(text("ALTER TABLE uks_visits ADD COLUMN school_id INTEGER"))

            ckg_student_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(ckg_students)")).fetchall()}
            if "parent_phone" not in ckg_student_cols:
                conn.execute(text("ALTER TABLE ckg_students ADD COLUMN parent_phone VARCHAR(30)"))
            for table_name in tenant_tables:
                cols = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()}
                if "school_id" not in cols:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN school_id INTEGER"))
        return

    if engine.dialect.name.startswith("postgresql"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE users "
                    "ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE users "
                    "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP"
                )
            )
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS nip VARCHAR(50)"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS jabatan VARCHAR(100)"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS signature_image TEXT"))
            conn.execute(text("ALTER TABLE patients ADD COLUMN IF NOT EXISTS class_name VARCHAR(50)"))
            conn.execute(text("ALTER TABLE patients ADD COLUMN IF NOT EXISTS parent_name VARCHAR(200)"))
            conn.execute(text("ALTER TABLE patients ADD COLUMN IF NOT EXISTS parent_phone VARCHAR(30)"))
            conn.execute(text("ALTER TABLE uks_visits ADD COLUMN IF NOT EXISTS diagnosis VARCHAR(255)"))
            conn.execute(text("ALTER TABLE uks_visits ADD COLUMN IF NOT EXISTS referral_place VARCHAR(255)"))
            conn.execute(text("ALTER TABLE uks_visits ADD COLUMN IF NOT EXISTS control_date DATE"))
            conn.execute(text("ALTER TABLE uks_visits ADD COLUMN IF NOT EXISTS referral_status VARCHAR(50)"))
            conn.execute(text("ALTER TABLE uks_visits ADD COLUMN IF NOT EXISTS whatsapp_status VARCHAR(30)"))
            conn.execute(text("ALTER TABLE uks_visits ADD COLUMN IF NOT EXISTS whatsapp_message TEXT"))
            conn.execute(text("ALTER TABLE ckg_students ADD COLUMN IF NOT EXISTS parent_phone VARCHAR(30)"))
            for table_name in tenant_tables:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS school_id INTEGER"))
            conn.execute(text("ALTER TABLE medicine_inventory DROP CONSTRAINT IF EXISTS medicine_inventory_name_key"))


def ensure_default_school_data() -> None:
    db: Session = SessionLocal()
    try:
        school = get_default_school(db)
        db.commit()
        db.refresh(school)

        tenant_models = [
            UserORM,
            models.AuditLogORM,
            models.RecommendationLetterORM,
            models.CKGEventORM,
            models.CKGStudentORM,
            models.CKGStationAssignmentORM,
            models.CKGAnthropometryORM,
            models.CKGTTVORM,
            models.CKGVisionORM,
            models.CKGDentalORM,
            models.CKGGeneralScreeningORM,
            models.CKGReferralORM,
            PatientORM,
            models.AssessmentORM,
            models.RecommendationORM,
            models.UKSVisitORM,
            models.UKSMedicationORM,
            models.MedicineInventoryORM,
            models.SchoolSettingORM,
            models.MedicineTransactionORM,
        ]
        for model in tenant_models:
            db.query(model).filter(model.school_id.is_(None)).update(
                {model.school_id: school.id},
                synchronize_session=False,
            )
        db.commit()
    finally:
        db.close()


ensure_database_columns()
ensure_default_school_data()

UI_INDEX_PATH = Path(__file__).resolve().parent / "ui" / "index.html"
UI_LOGIN_PATH = Path(__file__).resolve().parent / "ui" / "login.html"
UI_STUDENTS_PATH = Path(__file__).resolve().parent / "ui" / "students.html"
UI_STUDENT_DETAIL_PATH = Path(__file__).resolve().parent / "ui" / "student_detail.html"
UI_SETTINGS_PATH = Path(__file__).resolve().parent / "ui" / "settings.html"
UI_REPORTS_PATH = Path(__file__).resolve().parent / "ui" / "reports.html"
UI_USERS_PATH = Path(__file__).resolve().parent / "ui" / "users.html"
UI_AUDIT_LOGS_PATH = Path(__file__).resolve().parent / "ui" / "audit_logs.html"
UI_CKG_PATH = Path(__file__).resolve().parent / "ui" / "ckg.html"
UI_SCHOOLS_PATH = Path(__file__).resolve().parent / "ui" / "schools.html"
UI_ACCESS_DENIED_PATH = Path(__file__).resolve().parent / "ui" / "access_denied.html"
UI_ASSETS_PATH = Path(__file__).resolve().parent / "ui" / "assets"

app.mount("/ui/assets", StaticFiles(directory=UI_ASSETS_PATH), name="ui-assets")

def protected_ui_page(request: Request, path: Path, allowed_roles: set[str] | None = None):
    db = SessionLocal()
    try:
        session_user = request.session.get("user")
        if not session_user:
            return RedirectResponse("/login", status_code=303)

        user = db.get(UserORM, session_user.get("id"))
        if user is None or not user.is_active:
            request.session.clear()
            return RedirectResponse("/login", status_code=303)

        request.session["user"] = {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role,
            "school_id": user.school_id,
        }

        if allowed_roles is not None and user.role != "super_admin" and user.role not in allowed_roles:
            return FileResponse(UI_ACCESS_DENIED_PATH, status_code=403)

        return FileResponse(path)
    finally:
        db.close()


def seed_admin_user() -> None:
    if os.getenv("DISABLE_DEFAULT_ADMIN", "false").lower() == "true":
        return
    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD", "admin123")
    admin_full_name = os.getenv("ADMIN_FULL_NAME", "Administrator")

    db: Session = SessionLocal()
    try:
        default_school = get_default_school(db)
        admin = db.query(UserORM).filter(UserORM.username == admin_username).first()
        if admin is None:
            db.add(
                UserORM(
                    school_id=default_school.id,
                    username=admin_username,
                    full_name=admin_full_name,
                    role="admin",
                    password_hash=hash_password(admin_password),
                    is_active=True,
                )
            )
            db.commit()
    finally:
        db.close()


def import_students_once() -> None:
    if pd is None:
        return

    db: Session = SessionLocal()

    try:
        default_school = get_default_school(db)

        existing = db.query(PatientORM).count()

        if existing > 0:
            return

        df = pd.read_excel(
            "students_clean_import.xlsx"
        )

        for _, row in df.iterrows():

            student = PatientORM(
                school_id=default_school.id,
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
def dashboard(request: Request):
    return protected_ui_page(request, UI_INDEX_PATH, {"admin", "perawat", "kepala_sekolah", "tim_uksr", "super_admin"})


@app.get("/login", response_class=FileResponse)
def login_page() -> FileResponse:
    return FileResponse(UI_LOGIN_PATH)
@app.get("/students", response_class=FileResponse)
def students_page(request: Request):
    return protected_ui_page(request, UI_STUDENTS_PATH, {"admin", "perawat", "kepala_sekolah", "tim_uksr", "wali_asuh"})
@app.get("/student-detail", response_class=FileResponse)
def student_detail_page(request: Request):
    return protected_ui_page(request, UI_STUDENT_DETAIL_PATH, {"admin", "perawat", "kepala_sekolah", "tim_uksr", "wali_asuh"})
@app.get("/reports", response_class=FileResponse)
def reports_page(request: Request):
    return protected_ui_page(request, UI_REPORTS_PATH, {"admin", "perawat", "kepala_sekolah", "super_admin"})
@app.get("/settings", response_class=FileResponse)
def settings_page(request: Request):
    return protected_ui_page(request, UI_SETTINGS_PATH)
@app.get("/users", response_class=FileResponse)
def users_page(request: Request):
    return protected_ui_page(request, UI_USERS_PATH, {"admin", "perawat", "super_admin"})


@app.get("/audit-logs", response_class=FileResponse)
def audit_logs_page(request: Request):
    return protected_ui_page(request, UI_AUDIT_LOGS_PATH, {"admin", "super_admin"})


@app.get("/ckg", response_class=FileResponse)
def ckg_page(request: Request):
    return protected_ui_page(request, UI_CKG_PATH, {"admin", "perawat", "kepala_sekolah", "tim_uksr", "super_admin"})


@app.get("/ui", response_class=FileResponse)
def ui_page(request: Request):
    return protected_ui_page(request, UI_INDEX_PATH, {"admin", "perawat", "kepala_sekolah", "tim_uksr", "super_admin"})


@app.get("/schools", response_class=FileResponse)
def schools_page(request: Request):
    return protected_ui_page(request, UI_SCHOOLS_PATH, {"super_admin"})
