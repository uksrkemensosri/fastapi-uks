from datetime import datetime
from html import escape
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.ckg import append_pdf_letterhead, append_pdf_signature
from app.api.recommendations import pdf_school_for_user
from app.api.routes import friendly_whatsapp_message, send_whatsapp_message
from app.auth.dependencies import require_roles
from app.auth.tenant import tenant_get, tenant_query
from app.db.dependencies import get_db
from app.db.models import AuditLogORM, FitnessEventORM, FitnessExaminationORM, FitnessStudentORM, PatientORM, UserORM
from app.models.fitness_schemas import (
    FitnessDashboardResponse,
    FitnessEventCreate,
    FitnessEventResponse,
    FitnessEventUpdate,
    FitnessExaminationSubmit,
    FitnessQueueItem,
    FitnessStudentCreate,
    FitnessStudentResponse,
    FitnessSummaryResponse,
)

router = APIRouter(prefix="/api/fitness", tags=["Cek Kebugaran"])

ROLE_ADMIN = "admin"
ROLE_PERAWAT = "perawat"
ROLE_KEPALA_UKSR = "kepala_sekolah"
ROLE_TIM_UKSR = "tim_uksr"
ROLE_FITNESS_ACCESS = (ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_TIM_UKSR)
ROLE_FITNESS_REPORT_ACCESS = (ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR)


def write_fitness_audit(
    db: Session,
    user: UserORM | None,
    action: str,
    entity_type: str,
    entity_id: str | int | None = None,
    details: str | None = None,
) -> None:
    db.add(
        AuditLogORM(
            school_id=getattr(user, "school_id", None) if user else None,
            user_id=user.id if user else None,
            username=user.username if user else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            details=details,
        )
    )


def get_event_or_active(db: Session, user: UserORM, event_id: int | None = None) -> FitnessEventORM:
    event = tenant_get(db, FitnessEventORM, event_id, user) if event_id else (
        tenant_query(db.query(FitnessEventORM), FitnessEventORM, user).filter(FitnessEventORM.is_active.is_(True)).first()
    )
    if event is None:
        raise HTTPException(status_code=404, detail="Fitness event not found")
    return event


def next_station_for_status(status_value: str) -> str | None:
    if status_value == "REGISTERED":
        return "PEMERIKSAAN_KEBUGARAN"
    return None


def student_response(
    student: FitnessStudentORM,
    whatsapp_status: str | None = None,
    whatsapp_message: str | None = None,
) -> FitnessStudentResponse:
    exam = student.examination
    return FitnessStudentResponse(
        id=student.id,
        event_id=student.event_id,
        nis=student.nis,
        full_name=student.full_name,
        gender=student.gender,
        birth_date=student.birth_date,
        class_name=student.class_name,
        section=student.section,
        parent_name=student.parent_name,
        parent_phone=student.parent_phone,
        status=student.status,
        queue_number=student.queue_number,
        next_station=next_station_for_status(student.status),
        whatsapp_status=whatsapp_status or (exam.whatsapp_status if exam else None),
        whatsapp_message=whatsapp_message or (friendly_whatsapp_message(exam.whatsapp_status, exam.whatsapp_message) if exam else None),
    )


def next_queue_number(db: Session, event_id: int) -> int:
    max_number = db.query(func.max(FitnessStudentORM.queue_number)).filter(FitnessStudentORM.event_id == event_id).scalar()
    return int(max_number or 0) + 1


def sync_patient_from_fitness(db: Session, student: FitnessStudentORM) -> None:
    patient = (
        db.query(PatientORM)
        .filter(PatientORM.school_id == student.school_id, PatientORM.id == student.nis)
        .first()
    )
    if patient is None:
        db.add(
            PatientORM(
                school_id=student.school_id,
                id=student.nis,
                name=student.full_name,
                age=0,
                gender=student.gender,
                class_name=student.class_name,
                parent_name=student.parent_name,
                parent_phone=student.parent_phone,
                birth_date=student.birth_date,
            )
        )
        return

    patient.name = student.full_name
    patient.gender = student.gender
    patient.class_name = student.class_name
    patient.parent_name = student.parent_name
    patient.parent_phone = student.parent_phone
    patient.birth_date = student.birth_date


def calculate_bmi(weight: float, height: float) -> float:
    meters = height / 100
    return round(weight / (meters * meters), 2) if meters else 0


def pdf_cell(value: object, style: ParagraphStyle) -> Paragraph:
    text = "-" if value is None or value == "" else str(value)
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def pdf_styles():
    styles = getSampleStyleSheet()
    styles["Title"].fontSize = 15
    styles["Title"].leading = 18
    styles["Normal"].fontSize = 8.5
    styles["Normal"].leading = 11
    small = ParagraphStyle("FitnessSmall", parent=styles["Normal"], fontSize=7.4, leading=9, wordWrap="CJK")
    return styles, small


def build_fitness_whatsapp_message(student: FitnessStudentORM, exam: FitnessExaminationORM, event: FitnessEventORM | None) -> str:
    parent_name = student.parent_name or "Wali Asuh"
    event_name = event.event_name if event else "Cek Kebugaran"
    return f"""[EMR UKS Sekolah Rakyat]
Yth. {parent_name},

Siswa {student.full_name} telah menyelesaikan {event_name}.

Hasil pemeriksaan:
- Berat badan: {exam.weight} kg
- Tinggi badan: {exam.height} cm
- BMI: {exam.bmi}
- Tensi: {exam.blood_pressure}
- Saturasi: {exam.oxygen_saturation}%
- Suhu: {exam.temperature} C

Catatan: {exam.notes or "-"}

Terima kasih."""


@router.post("/events", response_model=FitnessEventResponse, status_code=status.HTTP_201_CREATED)
def create_event(
    payload: FitnessEventCreate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> FitnessEventResponse:
    if payload.is_active:
        tenant_query(db.query(FitnessEventORM), FitnessEventORM, current_user).update({FitnessEventORM.is_active: False})
    event = FitnessEventORM(school_id=current_user.school_id, **payload.model_dump())
    db.add(event)
    db.flush()
    write_fitness_audit(db, current_user, "create_fitness_event", "fitness_event", event.id, event.event_name)
    db.commit()
    db.refresh(event)
    return FitnessEventResponse(**event.__dict__)


@router.get("/events", response_model=list[FitnessEventResponse])
def list_events(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_FITNESS_ACCESS)),
) -> list[FitnessEventResponse]:
    events = tenant_query(db.query(FitnessEventORM), FitnessEventORM, current_user).order_by(FitnessEventORM.id.desc()).all()
    return [FitnessEventResponse(**event.__dict__) for event in events]


@router.get("/events/active", response_model=FitnessEventResponse)
def active_event(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_FITNESS_ACCESS)),
) -> FitnessEventResponse:
    event = get_event_or_active(db, current_user)
    return FitnessEventResponse(**event.__dict__)


@router.patch("/events/{event_id}", response_model=FitnessEventResponse)
def update_event(
    event_id: int,
    payload: FitnessEventUpdate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> FitnessEventResponse:
    event = tenant_get(db, FitnessEventORM, event_id, current_user)
    if event is None:
        raise HTTPException(status_code=404, detail="Fitness event not found")
    update_data = payload.model_dump(exclude_unset=True)
    if update_data.get("is_active") is True:
        tenant_query(db.query(FitnessEventORM), FitnessEventORM, current_user).filter(FitnessEventORM.id != event_id).update({FitnessEventORM.is_active: False})
    for key, value in update_data.items():
        setattr(event, key, value)
    write_fitness_audit(db, current_user, "edit_fitness_event", "fitness_event", event.id, event.event_name)
    db.commit()
    db.refresh(event)
    return FitnessEventResponse(**event.__dict__)


@router.post("/students", response_model=FitnessStudentResponse, status_code=status.HTTP_201_CREATED)
def register_student(
    payload: FitnessStudentCreate,
    event_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_FITNESS_ACCESS)),
) -> FitnessStudentResponse:
    event = get_event_or_active(db, current_user, event_id)
    student = FitnessStudentORM(
        school_id=event.school_id,
        event_id=event.id,
        queue_number=next_queue_number(db, event.id),
        **payload.model_dump(),
    )
    db.add(student)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="NIS already registered for this fitness event")
    sync_patient_from_fitness(db, student)
    write_fitness_audit(db, current_user, "register_fitness_student", "fitness_student", student.id, student.full_name)
    db.commit()
    db.refresh(student)
    return student_response(student)


@router.get("/students", response_model=list[FitnessStudentResponse])
def list_students(
    event_id: int | None = Query(default=None),
    q: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_FITNESS_ACCESS)),
) -> list[FitnessStudentResponse]:
    event = get_event_or_active(db, current_user, event_id)
    query = tenant_query(db.query(FitnessStudentORM), FitnessStudentORM, current_user).filter(FitnessStudentORM.event_id == event.id)
    if q:
        like_expr = f"%{q.strip()}%"
        query = query.filter((FitnessStudentORM.full_name.ilike(like_expr)) | (FitnessStudentORM.nis.ilike(like_expr)))
    students = query.order_by(FitnessStudentORM.queue_number.asc(), FitnessStudentORM.full_name.asc()).all()
    return [student_response(student) for student in students]


@router.delete("/students/{student_id}")
def delete_student(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_FITNESS_ACCESS)),
) -> dict:
    student = tenant_get(db, FitnessStudentORM, student_id, current_user)
    if student is None:
        raise HTTPException(status_code=404, detail="Fitness student not found")
    write_fitness_audit(db, current_user, "delete_fitness_student", "fitness_student", student.id, student.full_name)
    db.delete(student)
    db.commit()
    return {"message": "Siswa dihapus dari cek kebugaran"}


@router.get("/queue", response_model=list[FitnessQueueItem])
def queue(
    event_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_FITNESS_ACCESS)),
) -> list[FitnessQueueItem]:
    event = get_event_or_active(db, current_user, event_id)
    students = (
        tenant_query(db.query(FitnessStudentORM), FitnessStudentORM, current_user)
        .filter(FitnessStudentORM.event_id == event.id, FitnessStudentORM.status == "REGISTERED")
        .order_by(FitnessStudentORM.queue_number.asc(), FitnessStudentORM.full_name.asc())
        .all()
    )
    return [
        FitnessQueueItem(
            id=student.id,
            queue_number=student.queue_number,
            student_name=student.full_name,
            class_name=student.class_name,
            section=student.section,
            current_status=student.status,
            next_station=next_station_for_status(student.status),
        )
        for student in students
    ]


@router.post("/students/{student_id}/examination", response_model=FitnessStudentResponse)
def submit_examination(
    student_id: int,
    payload: FitnessExaminationSubmit,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_FITNESS_ACCESS)),
) -> FitnessStudentResponse:
    student = tenant_get(db, FitnessStudentORM, student_id, current_user)
    if student is None:
        raise HTTPException(status_code=404, detail="Fitness student not found")
    record = student.examination or FitnessExaminationORM(school_id=student.school_id, student_id=student.id)
    record.weight = payload.weight
    record.height = payload.height
    record.bmi = calculate_bmi(payload.weight, payload.height)
    record.blood_pressure = payload.blood_pressure
    record.oxygen_saturation = payload.oxygen_saturation
    record.temperature = payload.temperature
    record.notes = payload.notes
    record.examined_by = current_user.id
    student.status = "COMPLETED"
    db.add(record)
    write_fitness_audit(db, current_user, "complete_fitness_examination", "fitness_student", student.id, f"BMI={record.bmi}")
    phone = student.parent_phone
    if not phone:
        patient = (
            db.query(PatientORM)
            .filter(PatientORM.school_id == student.school_id, PatientORM.id == student.nis)
            .first()
        )
        phone = patient.parent_phone if patient else None
    whatsapp_status, whatsapp_detail = send_whatsapp_message(
        phone,
        build_fitness_whatsapp_message(student, record, student.event),
    )
    record.whatsapp_status = whatsapp_status
    record.whatsapp_message = whatsapp_detail
    write_fitness_audit(
        db,
        current_user,
        "notify_fitness_completed",
        "fitness_student",
        student.id,
        f"{whatsapp_status}: {whatsapp_detail}",
    )
    db.commit()
    db.refresh(student)
    return student_response(student, whatsapp_status, friendly_whatsapp_message(whatsapp_status, whatsapp_detail))


@router.get("/dashboard", response_model=FitnessDashboardResponse)
def dashboard(
    event_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_FITNESS_REPORT_ACCESS)),
) -> FitnessDashboardResponse:
    event = get_event_or_active(db, current_user, event_id)
    query = tenant_query(db.query(FitnessStudentORM), FitnessStudentORM, current_user).filter(FitnessStudentORM.event_id == event.id)
    total = query.count()
    completed = query.filter(FitnessStudentORM.status == "COMPLETED").count()
    waiting = query.filter(FitnessStudentORM.status == "REGISTERED").count()
    recent = query.order_by(FitnessStudentORM.id.desc()).limit(8).all()
    return FitnessDashboardResponse(
        total_registered=total,
        completed=completed,
        in_progress=max(total - completed - waiting, 0),
        waiting_queue=waiting,
        completion_percentage=round((completed / total * 100), 2) if total else 0,
        recent_students=[student_response(student) for student in recent],
    )


def build_summary(student: FitnessStudentORM) -> FitnessSummaryResponse:
    exam = student.examination
    return FitnessSummaryResponse(
        student=student_response(student),
        examination=None if not exam else {
            "weight": exam.weight,
            "height": exam.height,
            "bmi": exam.bmi,
            "blood_pressure": exam.blood_pressure,
            "oxygen_saturation": exam.oxygen_saturation,
        "temperature": exam.temperature,
        "notes": exam.notes,
        "whatsapp_status": exam.whatsapp_status,
        "whatsapp_message": friendly_whatsapp_message(exam.whatsapp_status, exam.whatsapp_message),
    },
        generated_at=datetime.now(),
    )


@router.get("/students/{student_id}/summary", response_model=FitnessSummaryResponse)
def summary(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_FITNESS_REPORT_ACCESS)),
) -> FitnessSummaryResponse:
    student = tenant_get(db, FitnessStudentORM, student_id, current_user)
    if student is None:
        raise HTTPException(status_code=404, detail="Fitness student not found")
    return build_summary(student)


@router.get("/report/pdf")
def report_pdf(
    event_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_FITNESS_REPORT_ACCESS)),
) -> StreamingResponse:
    event = get_event_or_active(db, current_user, event_id)
    students = (
        tenant_query(db.query(FitnessStudentORM), FitnessStudentORM, current_user)
        .filter(FitnessStudentORM.event_id == event.id)
        .order_by(FitnessStudentORM.queue_number.asc(), FitnessStudentORM.full_name.asc())
        .all()
    )
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=28, rightMargin=28, topMargin=24, bottomMargin=24)
    styles, small = pdf_styles()
    elements = []
    school = pdf_school_for_user(db, current_user)
    append_pdf_letterhead(elements, doc, "LAPORAN CEK KEBUGARAN SISWA", f"{event.event_name} | {event.start_date} s.d. {event.end_date}", styles, school)
    rows = [[
        "No", "NIS", "Nama", "Kelas", "BB", "TB", "BMI", "Tensi", "Saturasi", "Suhu", "Status", "Catatan"
    ]]
    for index, student in enumerate(students, start=1):
        exam = student.examination
        rows.append([
            str(index),
            student.nis,
            student.full_name,
            student.class_name or "-",
            "-" if not exam else exam.weight,
            "-" if not exam else exam.height,
            "-" if not exam else exam.bmi,
            "-" if not exam else exam.blood_pressure,
            "-" if not exam else f"{exam.oxygen_saturation}%",
            "-" if not exam else f"{exam.temperature} C",
            student.status,
            "-" if not exam else (exam.notes or "-"),
        ])
    table = Table([[pdf_cell(cell, small) for cell in row] for row in rows], repeatRows=1, colWidths=[24, 58, 116, 45, 36, 36, 36, 54, 54, 45, 62, 136])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#8b5cf6")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    elements.append(table)
    append_pdf_signature(elements, doc, current_user, styles, label="Petugas Pemeriksa", school=school)
    doc.build(elements)
    buffer.seek(0)
    filename = f"laporan_cek_kebugaran_{event.academic_year.replace('/', '-')}.pdf"
    return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
