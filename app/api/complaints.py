"""Public QR complaint intake and authenticated staff follow-up workflow."""

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from io import BytesIO
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, status
import qrcode
import requests
from reportlab.graphics import renderSVG
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.auth.tenant import get_default_school, tenant_get, tenant_query
from app.db.dependencies import get_db
from app.db.models import PatientORM, SchoolORM, StudentComplaintORM, UKSVisitORM, UserORM
from app.models.schemas import (
    PublicComplaintCreate,
    PublicComplaintResponse,
    PublicComplaintStudent,
    StudentComplaintResponse,
)

router = APIRouter(tags=["Keluhan Siswa"])
logger = logging.getLogger(__name__)

ROLE_ADMIN = "admin"
ROLE_PERAWAT = "perawat"
ROLE_TIM_UKSR = "tim_uksr"
ROLE_STAFF = (ROLE_ADMIN, ROLE_PERAWAT, ROLE_TIM_UKSR)
COMPLAINT_STATUSES = {"MENUNGGU", "DITINDAKLANJUTI", "SELESAI", "DIBATALKAN"}
_RATE_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


def _notify_complaint_group(
    patient_name: str,
    class_name: str | None,
    reporter_name: str,
    complaint: str,
    complaint_id: int,
    submitted_at: datetime,
) -> None:
    """Send a best-effort WhatsApp notification without delaying intake."""
    token = os.getenv("FONNTE_TOKEN", "").strip()
    group_id = os.getenv("FONNTE_GROUP_ID", "").strip()
    if not token or not group_id:
        return

    submitted = submitted_at
    if submitted.tzinfo is None:
        submitted = submitted.replace(tzinfo=ZoneInfo("UTC"))
    local_time = submitted.astimezone(ZoneInfo("Asia/Jakarta"))
    message = (
        "KELUHAN SISWA BARU - SEHATI\n\n"
        f"Nama: {patient_name}\n"
        f"Kelas: {class_name or '-'}\n"
        f"Dilaporkan oleh: {reporter_name}\n"
        f"Keluhan: {complaint}\n"
        f"Waktu: {local_time.strftime('%d-%m-%Y %H:%M')} WIB\n\n"
        f"Nomor laporan: KEL-{complaint_id:06d}\n"
        "Silakan buka SEHATI untuk menindaklanjuti."
    )
    try:
        response = requests.post(
            os.getenv("FONNTE_API_URL", "https://api.fonnte.com/send"),
            headers={"Authorization": token},
            data={"target": group_id, "message": message},
            timeout=10,
        )
        if not response.ok:
            logger.warning("Fonnte complaint notification failed with HTTP %s", response.status_code)
    except requests.RequestException:
        logger.exception("Fonnte complaint notification request failed")


def _rate_limit(request: Request, bucket: str, limit: int, seconds: int) -> None:
    client_ip = request.client.host if request.client else "unknown"
    key = f"{bucket}:{client_ip}"
    now = time.monotonic()
    entries = _RATE_BUCKETS[key]
    while entries and entries[0] <= now - seconds:
        entries.popleft()
    if len(entries) >= limit:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Terlalu banyak permintaan. Silakan coba lagi sebentar.")
    entries.append(now)


def _selection_secret() -> bytes:
    return os.getenv("SECRET_KEY", "dev-secret-key-change-me").encode("utf-8")


def _selection_token(patient: PatientORM, school: SchoolORM) -> str:
    payload = {
        "patient_id": patient.id,
        "school_id": school.id,
        "exp": int(time.time()) + 10 * 60,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii").rstrip("=")
    signature = hmac.new(_selection_secret(), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _resolve_selection_token(token: str) -> dict:
    try:
        encoded, signature = token.rsplit(".", 1)
        expected = hmac.new(_selection_secret(), encoded.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        if int(payload["exp"]) < int(time.time()):
            raise ValueError("expired")
        return {"patient_id": str(payload["patient_id"]), "school_id": int(payload["school_id"])}
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pilihan siswa sudah tidak berlaku. Cari nama kembali.")


def _public_school(db: Session, school_code: str | None) -> SchoolORM:
    if school_code:
        school = db.query(SchoolORM).filter(SchoolORM.school_code == school_code, SchoolORM.is_active.is_(True)).first()
    else:
        school = get_default_school(db)
    if school is None or not school.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sekolah tidak ditemukan")
    return school


def _complaint_response(item: StudentComplaintORM) -> StudentComplaintResponse:
    patient = item.patient
    return StudentComplaintResponse(
        id=item.id,
        patient_id=item.patient_id,
        patient_name=patient.name if patient else "Siswa tidak ditemukan",
        class_name=patient.class_name if patient else None,
        reporter_name=item.reporter_name,
        complaint=item.complaint,
        submitted_at=item.submitted_at,
        status=item.status,
        handled_by=item.handled_by,
        handled_by_name=item.handler.full_name if item.handler else None,
        handled_at=item.handled_at,
        visit_id=item.visit_id,
    )


def _complaint_qr_drawing(url: str, size: int = 900) -> Drawing:
    widget = QrCodeWidget(url)
    x1, y1, x2, y2 = widget.getBounds()
    width, height = x2 - x1, y2 - y1
    drawing = Drawing(size, size, transform=[size / width, 0, 0, size / height, 0, 0])
    drawing.add(widget)
    return drawing


def _complaint_qr_url(request: Request, school: SchoolORM) -> str:
    configured_base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    base_url = configured_base_url or str(request.base_url).rstrip("/")
    return f"{base_url}/keluhan?{urlencode({'school': school.school_code})}"


def _school_for_staff_qr(db: Session, current_user: UserORM) -> SchoolORM:
    school_id = getattr(current_user, "school_id", None)
    school = db.get(SchoolORM, school_id) if school_id is not None else None
    return school or get_default_school(db)


@router.get("/api/public/complaints/students", response_model=list[PublicComplaintStudent])
def search_public_complaint_students(
    request: Request,
    q: str = Query(min_length=2, max_length=100),
    school: str | None = Query(default=None, max_length=50),
    db: Session = Depends(get_db),
) -> list[PublicComplaintStudent]:
    _rate_limit(request, "complaint-search", limit=30, seconds=60)
    selected_school = _public_school(db, school)
    keyword = q.strip()
    if len(keyword) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Masukkan minimal 2 karakter")
    like = f"%{keyword}%"
    patients = (
        db.query(PatientORM)
        .filter(PatientORM.school_id == selected_school.id)
        .filter((PatientORM.name.ilike(like)) | (PatientORM.id.ilike(like)))
        .order_by(PatientORM.name.asc())
        .limit(8)
        .all()
    )
    return [
        PublicComplaintStudent(
            selection_token=_selection_token(patient, selected_school),
            name=patient.name,
            class_name=patient.class_name,
        )
        for patient in patients
    ]


@router.get("/api/public/complaints/school")
def public_complaint_school(
    school: str | None = Query(default=None, max_length=50),
    db: Session = Depends(get_db),
) -> dict:
    selected_school = _public_school(db, school)
    return {"school_name": selected_school.school_name}


@router.post("/api/public/complaints", response_model=PublicComplaintResponse, status_code=status.HTTP_201_CREATED)
def create_public_complaint(
    payload: PublicComplaintCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> PublicComplaintResponse:
    _rate_limit(request, "complaint-submit", limit=10, seconds=10 * 60)
    selected = _resolve_selection_token(payload.selection_token)
    patient = (
        db.query(PatientORM)
        .filter(PatientORM.id == selected["patient_id"], PatientORM.school_id == selected["school_id"])
        .first()
    )
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Siswa tidak ditemukan")
    recent = (
        db.query(StudentComplaintORM)
        .filter(
            StudentComplaintORM.patient_id == patient.id,
            StudentComplaintORM.school_id == patient.school_id,
            StudentComplaintORM.complaint == payload.complaint,
            StudentComplaintORM.submitted_at >= datetime.now() - timedelta(minutes=3),
        )
        .order_by(StudentComplaintORM.id.desc())
        .first()
    )
    if recent:
        return PublicComplaintResponse(id=recent.id, status=recent.status, submitted_at=recent.submitted_at, duplicate=True)
    item = StudentComplaintORM(
        school_id=patient.school_id,
        patient_id=patient.id,
        reporter_name=payload.reporter_name,
        complaint=payload.complaint,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    background_tasks.add_task(
        _notify_complaint_group,
        patient.name,
        patient.class_name,
        item.reporter_name,
        item.complaint,
        item.id,
        item.submitted_at,
    )
    return PublicComplaintResponse(id=item.id, status=item.status, submitted_at=item.submitted_at)


@router.get("/api/complaints/qr.svg")
def download_complaint_qr_svg(
    request: Request,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN)),
) -> Response:
    school = _school_for_staff_qr(db, current_user)
    svg = renderSVG.drawToString(_complaint_qr_drawing(_complaint_qr_url(request, school)))
    return Response(content=svg, media_type="image/svg+xml", headers={"Content-Disposition": 'attachment; filename="qr_keluhan_siswa.svg"'})


@router.get("/api/complaints/qr.png")
def download_complaint_qr_png(
    request: Request,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN)),
) -> Response:
    school = _school_for_staff_qr(db, current_user)
    generator = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=18, border=4)
    generator.add_data(_complaint_qr_url(request, school))
    generator.make(fit=True)
    stream = BytesIO()
    generator.make_image(fill_color="black", back_color="white").save(stream, format="PNG", optimize=True)
    return Response(content=stream.getvalue(), media_type="image/png", headers={"Content-Disposition": 'attachment; filename="qr_keluhan_siswa.png"'})


@router.get("/api/complaints", response_model=list[StudentComplaintResponse])
def list_student_complaints(
    complaint_status: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_STAFF)),
) -> list[StudentComplaintResponse]:
    query = tenant_query(db.query(StudentComplaintORM), StudentComplaintORM, current_user)
    if complaint_status:
        normalized_status = complaint_status.upper()
        if normalized_status not in COMPLAINT_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Status keluhan tidak valid")
        query = query.filter(StudentComplaintORM.status == normalized_status)
    items = query.order_by(StudentComplaintORM.submitted_at.desc(), StudentComplaintORM.id.desc()).all()
    return [_complaint_response(item) for item in items]


@router.get("/api/complaints/pending-count")
def pending_complaint_count(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_STAFF)),
) -> dict:
    count = tenant_query(db.query(StudentComplaintORM), StudentComplaintORM, current_user).filter(StudentComplaintORM.status == "MENUNGGU").count()
    return {"count": count}


@router.post("/api/complaints/{complaint_id}/follow-up", response_model=StudentComplaintResponse)
def follow_up_student_complaint(
    complaint_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_STAFF)),
) -> StudentComplaintResponse:
    item = tenant_get(db, StudentComplaintORM, complaint_id, current_user)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Keluhan tidak ditemukan")
    if item.status in {"SELESAI", "DIBATALKAN"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Keluhan ini sudah ditutup")
    item.status = "DITINDAKLANJUTI"
    item.handled_by = current_user.id
    item.handled_at = datetime.now()
    db.commit()
    db.refresh(item)
    return _complaint_response(item)


@router.get("/api/complaints/{complaint_id}/visit-prefill")
def complaint_visit_prefill(
    complaint_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_STAFF)),
) -> dict:
    item = tenant_get(db, StudentComplaintORM, complaint_id, current_user)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Keluhan tidak ditemukan")
    if item.visit_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Keluhan ini sudah memiliki kunjungan UKS")
    if item.status == "MENUNGGU":
        item.status = "DITINDAKLANJUTI"
        item.handled_by = current_user.id
        item.handled_at = datetime.now()
        db.commit()
    patient = item.patient
    return {"complaint_id": item.id, "patient_id": patient.id, "patient_name": patient.name, "class_name": patient.class_name, "complaint": item.complaint}


@router.post("/api/complaints/{complaint_id}/attach-visit/{visit_id}", response_model=StudentComplaintResponse)
def attach_visit_to_complaint(
    complaint_id: int,
    visit_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_STAFF)),
) -> StudentComplaintResponse:
    item = tenant_get(db, StudentComplaintORM, complaint_id, current_user)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Keluhan tidak ditemukan")
    if item.visit_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Keluhan ini sudah memiliki kunjungan UKS")
    visit = tenant_get(db, UKSVisitORM, visit_id, current_user)
    if visit is None or visit.patient_id != item.patient_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Kunjungan tidak sesuai dengan siswa keluhan")
    item.visit_id = visit.id
    item.status = "SELESAI"
    item.handled_by = current_user.id
    item.handled_at = datetime.now()
    db.commit()
    db.refresh(item)
    return _complaint_response(item)


@router.post("/api/complaints/{complaint_id}/complete", response_model=StudentComplaintResponse)
def complete_student_complaint(
    complaint_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_STAFF)),
) -> StudentComplaintResponse:
    item = tenant_get(db, StudentComplaintORM, complaint_id, current_user)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Keluhan tidak ditemukan")
    item.status = "SELESAI"
    item.handled_by = current_user.id
    item.handled_at = datetime.now()
    db.commit()
    db.refresh(item)
    return _complaint_response(item)
