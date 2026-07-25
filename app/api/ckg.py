from datetime import UTC, datetime
from html import escape
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.recommendations import letterhead_flowable, qr_code_flowable
from app.auth.dependencies import get_current_user, require_roles
from app.auth.tenant import tenant_get, tenant_query
from app.db.dependencies import get_db
from app.db.models import (
    AuditLogORM,
    CKGAnthropometryORM,
    CKGDentalORM,
    CKGEventORM,
    CKGGeneralScreeningORM,
    CKGReferralORM,
    CKGStationAssignmentORM,
    CKGStudentORM,
    CKGTTVORM,
    CKGVisionORM,
    PatientORM,
    UserORM,
)
from app.models.ckg_schemas import (
    CKGAnthropometrySubmit,
    CKGDashboardResponse,
    CKGDentalSubmit,
    CKGEventCreate,
    CKGEventResponse,
    CKGEventUpdate,
    CKGGeneralSubmit,
    CKGQueueItem,
    CKGReferralCreate,
    CKGStationAssignmentCreate,
    CKGStationAssignmentResponse,
    CKGStudentCreate,
    CKGStudentImportRequest,
    CKGStudentResponse,
    CKGSummaryResponse,
    CKGTTVSubmit,
    CKGVisionSubmit,
    STATIONS,
    normalize_station,
)

router = APIRouter(prefix="/api/ckg", tags=["CKG"])

ROLE_ADMIN = "admin"
ROLE_PERAWAT = "perawat"
ROLE_SUPER_ADMIN = "super_admin"
ROLE_KEPALA_UKSR = "kepala_sekolah"
ROLE_TIM_UKSR = "tim_uksr"
ROLE_CKG_ACCESS = (ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_TIM_UKSR)
ROLE_CKG_REPORT_ACCESS = (ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR)

QUEUE_STATUS_BY_STATION = {
    "REGISTRATION": None,
    "ANTROPOMETRI": "REGISTERED",
    "TTV": "ANTROPOMETRI_DONE",
    "VISUS": "TTV_DONE",
    "GIGI": "VISUS_DONE",
    "SCREENING_UMUM": "GIGI_DONE",
}

NEXT_STATUS_BY_STATION = {
    "ANTROPOMETRI": "ANTROPOMETRI_DONE",
    "TTV": "TTV_DONE",
    "VISUS": "VISUS_DONE",
    "GIGI": "GIGI_DONE",
    "SCREENING_UMUM": "SCREENING_DONE",
}

NEXT_STATION_BY_STATUS = {
    "REGISTERED": "ANTROPOMETRI",
    "ANTROPOMETRI_DONE": "TTV",
    "TTV_DONE": "VISUS",
    "VISUS_DONE": "GIGI",
    "GIGI_DONE": "SCREENING_UMUM",
    "SCREENING_DONE": "COMPLETED",
    "COMPLETED": None,
}


def append_pdf_letterhead(elements: list, doc: SimpleDocTemplate, title: str, subtitle: str | None, styles) -> None:
    letterhead = letterhead_flowable(doc.width)
    if letterhead:
        elements.append(letterhead)
        elements.append(Spacer(1, 8))
    elements.append(Paragraph(title, styles["Title"]))
    if subtitle:
        elements.append(Paragraph(subtitle, styles["Normal"]))
    elements.append(Paragraph(f"Tanggal Cetak: {datetime.now().strftime('%d-%m-%Y %H:%M')}", styles["Normal"]))
    elements.append(Spacer(1, 12))


def pdf_cell(value: object, style: ParagraphStyle) -> Paragraph:
    text = "-" if value is None or value == "" else str(value)
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def ckg_pdf_styles():
    styles = getSampleStyleSheet()
    styles["Title"].fontSize = 15
    styles["Title"].leading = 18
    styles["Heading3"].fontSize = 11
    styles["Heading3"].leading = 14
    styles["Normal"].fontSize = 8.5
    styles["Normal"].leading = 11
    small = ParagraphStyle(
        "CKGSmall",
        parent=styles["Normal"],
        fontSize=7.2,
        leading=9,
        wordWrap="CJK",
    )
    tiny = ParagraphStyle(
        "CKGTiny",
        parent=styles["Normal"],
        fontSize=6.3,
        leading=7.8,
        wordWrap="CJK",
    )
    section = ParagraphStyle(
        "CKGSection",
        parent=styles["Heading3"],
        fontSize=10,
        leading=12,
        textColor=colors.HexColor("#312e81"),
        spaceBefore=8,
        spaceAfter=5,
    )
    return styles, small, tiny, section


def append_pdf_signature(elements: list, doc: SimpleDocTemplate, current_user: UserORM, styles, label: str = "Petugas UKS") -> None:
    generated_at = datetime.now()
    signer_name = current_user.full_name or "-"
    signer_nip = current_user.nip or "-"
    signer_title = current_user.jabatan or label
    qr_payload = "\n".join(
        [
            f"Nama: {signer_name}",
            f"NIP: {signer_nip}",
            f"Jabatan: {signer_title}",
            f"Tanggal cetak: {generated_at.strftime('%d/%m/%Y')}",
        ]
    )
    signature_qr = qr_code_flowable(qr_payload, size=58)
    signature_qr.hAlign = "RIGHT"
    table = Table(
        [
            [
                "",
                [
                    Paragraph(f"Bekasi, {generated_at.strftime('%d/%m/%Y')}", styles["Normal"]),
                    Paragraph(signer_title, styles["Normal"]),
                    signature_qr,
                    Paragraph(signer_name, styles["Normal"]),
                    Paragraph(f"NIP. {signer_nip}", styles["Normal"]),
                ],
            ]
        ],
        colWidths=[doc.width - 190, 190],
    )
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT")]))
    elements.append(Spacer(1, 18))
    elements.append(table)


def write_ckg_audit(
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


def get_event_or_active(db: Session, user: UserORM, event_id: int | None = None) -> CKGEventORM:
    event = tenant_get(db, CKGEventORM, event_id, user) if event_id else (
        tenant_query(db.query(CKGEventORM), CKGEventORM, user).filter(CKGEventORM.is_active.is_(True)).first()
    )
    if event is None:
        raise HTTPException(status_code=404, detail="CKG event not found")
    return event


def next_station_for_status(status_value: str) -> str | None:
    return NEXT_STATION_BY_STATUS.get(status_value)


def student_response(student: CKGStudentORM) -> CKGStudentResponse:
    return CKGStudentResponse(
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
        needs_referral=student.needs_referral,
        next_station=next_station_for_status(student.status),
    )


def require_station_access(
    db: Session,
    user: UserORM,
    event_id: int,
    station: str,
) -> None:
    station = normalize_station(station)
    if station not in STATIONS:
        raise HTTPException(status_code=400, detail="Invalid station")
    if user.role in {ROLE_ADMIN, ROLE_SUPER_ADMIN}:
        return

    assignment = (
        tenant_query(db.query(CKGStationAssignmentORM), CKGStationAssignmentORM, user)
        .filter(
            CKGStationAssignmentORM.event_id == event_id,
            CKGStationAssignmentORM.user_id == user.id,
            CKGStationAssignmentORM.station == station,
        )
        .first()
    )
    if assignment is None:
        raise HTTPException(status_code=403, detail="Forbidden for this CKG station")


def next_queue_number(db: Session, event_id: int) -> int:
    current_max = (
        db.query(func.max(CKGStudentORM.queue_number))
        .filter(CKGStudentORM.event_id == event_id)
        .scalar()
    )
    return int(current_max or 0) + 1


def sync_patient_from_ckg(db: Session, student: CKGStudentORM) -> None:
    patient = (
        db.query(PatientORM)
        .filter(PatientORM.id == student.nis, PatientORM.school_id == student.school_id)
        .first()
    )
    if patient is None:
        db.add(
            PatientORM(
                school_id=student.school_id,
                id=student.nis,
                name=student.full_name,
                gender=student.gender,
                class_name=student.class_name,
                birth_date=student.birth_date,
                age=0,
                parent_name=student.parent_name,
                parent_phone=student.parent_phone,
            )
        )
    else:
        patient.name = student.full_name
        patient.gender = student.gender
        patient.class_name = student.class_name
        patient.birth_date = student.birth_date
        patient.parent_name = student.parent_name
        patient.parent_phone = student.parent_phone
        db.add(patient)


@router.post("/events", response_model=CKGEventResponse, status_code=status.HTTP_201_CREATED)
def create_event(
    payload: CKGEventCreate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN)),
) -> CKGEventResponse:
    if payload.is_active:
        tenant_query(db.query(CKGEventORM), CKGEventORM, current_user).update({CKGEventORM.is_active: False})
    event = CKGEventORM(school_id=current_user.school_id, **payload.model_dump())
    db.add(event)
    db.flush()
    write_ckg_audit(db, current_user, "create_ckg_event", "ckg_event", event.id, event.event_name)
    db.commit()
    db.refresh(event)
    return CKGEventResponse(**event.__dict__)


@router.get("/events", response_model=list[CKGEventResponse])
def list_events(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_CKG_ACCESS)),
) -> list[CKGEventResponse]:
    events = tenant_query(db.query(CKGEventORM), CKGEventORM, current_user).order_by(CKGEventORM.id.desc()).all()
    return [CKGEventResponse(**event.__dict__) for event in events]


@router.get("/events/active", response_model=CKGEventResponse)
def get_active_event(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_CKG_ACCESS)),
) -> CKGEventResponse:
    event = get_event_or_active(db, current_user)
    return CKGEventResponse(**event.__dict__)


@router.patch("/events/{event_id}", response_model=CKGEventResponse)
def update_event(
    event_id: int,
    payload: CKGEventUpdate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN)),
) -> CKGEventResponse:
    event = tenant_get(db, CKGEventORM, event_id, current_user)
    if event is None:
        raise HTTPException(status_code=404, detail="CKG event not found")

    data = payload.model_dump(exclude_unset=True)
    if data.get("is_active") is True:
        tenant_query(db.query(CKGEventORM), CKGEventORM, current_user).filter(CKGEventORM.id != event_id).update({CKGEventORM.is_active: False})
    for key, value in data.items():
        setattr(event, key, value)

    write_ckg_audit(db, current_user, "edit_ckg_event", "ckg_event", event.id, event.event_name)
    db.add(event)
    db.commit()
    db.refresh(event)
    return CKGEventResponse(**event.__dict__)


@router.post("/assignments", response_model=CKGStationAssignmentResponse, status_code=status.HTTP_201_CREATED)
def create_assignment(
    payload: CKGStationAssignmentCreate,
    event_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN)),
) -> CKGStationAssignmentResponse:
    event = get_event_or_active(db, current_user, event_id)
    user = tenant_get(db, UserORM, payload.user_id, current_user)
    if user is None or not user.is_active:
        raise HTTPException(status_code=404, detail="User not found or inactive")

    assignment = CKGStationAssignmentORM(school_id=event.school_id, event_id=event.id, user_id=user.id, station=payload.station)
    db.add(assignment)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Station assignment already exists")

    write_ckg_audit(db, current_user, "assign_ckg_station", "ckg_station_assignment", assignment.id, f"{user.username} -> {payload.station}")
    db.commit()
    db.refresh(assignment)
    return CKGStationAssignmentResponse(
        id=assignment.id,
        event_id=assignment.event_id,
        user_id=user.id,
        username=user.username,
        full_name=user.full_name,
        station=assignment.station,
    )


@router.get("/assignments", response_model=list[CKGStationAssignmentResponse])
def list_assignments(
    event_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN)),
) -> list[CKGStationAssignmentResponse]:
    event = get_event_or_active(db, current_user, event_id)
    assignments = (
        tenant_query(db.query(CKGStationAssignmentORM), CKGStationAssignmentORM, current_user)
        .filter(CKGStationAssignmentORM.event_id == event.id)
        .order_by(CKGStationAssignmentORM.station.asc())
        .all()
    )
    return [
        CKGStationAssignmentResponse(
            id=item.id,
            event_id=item.event_id,
            user_id=item.user_id,
            username=item.user.username,
            full_name=item.user.full_name,
            station=item.station,
        )
        for item in assignments
    ]


@router.post("/students", response_model=CKGStudentResponse, status_code=status.HTTP_201_CREATED)
def register_student(
    payload: CKGStudentCreate,
    event_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_CKG_ACCESS)),
) -> CKGStudentResponse:
    event = get_event_or_active(db, current_user, event_id)
    require_station_access(db, current_user, event.id, "REGISTRATION")

    student = CKGStudentORM(
        school_id=event.school_id,
        event_id=event.id,
        queue_number=next_queue_number(db, event.id),
        status="REGISTERED",
        **payload.model_dump(),
    )
    db.add(student)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="NIS already registered for this CKG event")

    sync_patient_from_ckg(db, student)
    write_ckg_audit(db, current_user, "register_ckg_student", "ckg_student", student.id, student.full_name)
    db.commit()
    db.refresh(student)
    return student_response(student)


@router.post("/students/import")
def import_students(
    payload: CKGStudentImportRequest,
    event_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_CKG_ACCESS)),
) -> dict:
    event = get_event_or_active(db, current_user, event_id)
    require_station_access(db, current_user, event.id, "REGISTRATION")
    created = 0
    skipped = 0

    for item in payload.students:
        exists = (
            tenant_query(db.query(CKGStudentORM), CKGStudentORM, current_user)
            .filter(CKGStudentORM.event_id == event.id, CKGStudentORM.nis == item.nis)
            .first()
        )
        if exists:
            skipped += 1
            continue
        student = CKGStudentORM(
            school_id=event.school_id,
            event_id=event.id,
            queue_number=next_queue_number(db, event.id),
            status="REGISTERED",
            **item.model_dump(),
        )
        db.add(student)
        db.flush()
        sync_patient_from_ckg(db, student)
        created += 1

    write_ckg_audit(db, current_user, "import_ckg_students", "ckg_student", event.id, f"created={created}, skipped={skipped}")
    db.commit()
    return {"created": created, "skipped": skipped}


@router.get("/students", response_model=list[CKGStudentResponse])
def list_students(
    event_id: int | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_CKG_ACCESS)),
) -> list[CKGStudentResponse]:
    event = get_event_or_active(db, current_user, event_id)
    query = tenant_query(db.query(CKGStudentORM), CKGStudentORM, current_user).filter(CKGStudentORM.event_id == event.id)
    if q:
        like_expr = f"%{q.strip()}%"
        query = query.filter((CKGStudentORM.full_name.ilike(like_expr)) | (CKGStudentORM.nis.ilike(like_expr)))
    students = query.order_by(CKGStudentORM.queue_number.asc(), CKGStudentORM.full_name.asc()).all()
    return [student_response(student) for student in students]


@router.delete("/students/{student_id}")
def delete_ckg_student(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_CKG_ACCESS)),
) -> dict:
    student = tenant_get(db, CKGStudentORM, student_id, current_user)
    if student is None:
        raise HTTPException(status_code=404, detail="CKG student not found")

    require_station_access(db, current_user, student.event_id, "REGISTRATION")
    student_name = student.full_name
    student_nis = student.nis
    write_ckg_audit(
        db,
        current_user,
        "delete_ckg_student",
        "ckg_student",
        student.id,
        f"{student_name} ({student_nis})",
    )
    db.delete(student)
    db.commit()
    return {
        "message": "Siswa dihapus dari event CKG",
        "student_id": student_id,
        "patient_preserved": True,
    }


@router.get("/stations/{station}/queue", response_model=list[CKGQueueItem])
def station_queue(
    station: str,
    event_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_CKG_ACCESS)),
) -> list[CKGQueueItem]:
    station = normalize_station(station)
    event = get_event_or_active(db, current_user, event_id)
    require_station_access(db, current_user, event.id, station)

    if station == "SCREENING_UMUM":
        statuses = ("GIGI_DONE", "SCREENING_DONE")
    else:
        statuses = (QUEUE_STATUS_BY_STATION[station],)

    students = (
        tenant_query(db.query(CKGStudentORM), CKGStudentORM, current_user)
        .filter(CKGStudentORM.event_id == event.id, CKGStudentORM.status.in_(statuses))
        .order_by(CKGStudentORM.queue_number.asc(), CKGStudentORM.full_name.asc())
        .all()
    )
    return [
        CKGQueueItem(
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


def get_student_for_station(db: Session, student_id: int, station: str, current_user: UserORM) -> CKGStudentORM:
    student = tenant_get(db, CKGStudentORM, student_id, current_user)
    if student is None:
        raise HTTPException(status_code=404, detail="CKG student not found")
    expected = QUEUE_STATUS_BY_STATION[station]
    if station != "SCREENING_UMUM" and student.status not in (expected, NEXT_STATUS_BY_STATION[station]):
        raise HTTPException(status_code=400, detail=f"Student is not in {station} queue")
    if station == "SCREENING_UMUM" and student.status not in ("GIGI_DONE", "SCREENING_DONE", "COMPLETED"):
        raise HTTPException(status_code=400, detail="Student is not in general screening queue")
    return student


@router.post("/students/{student_id}/anthropometry", response_model=CKGStudentResponse)
def submit_anthropometry(
    student_id: int,
    payload: CKGAnthropometrySubmit,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_CKG_ACCESS)),
) -> CKGStudentResponse:
    student = get_student_for_station(db, student_id, "ANTROPOMETRI", current_user)
    require_station_access(db, current_user, student.event_id, "ANTROPOMETRI")
    height_m = payload.height / 100
    bmi = round(payload.weight / (height_m * height_m), 2)
    record = student.anthropometry or CKGAnthropometryORM(school_id=student.school_id, student_id=student.id)
    record.school_id = student.school_id
    record.weight = payload.weight
    record.height = payload.height
    record.bmi = bmi
    record.examined_by = current_user.id
    student.status = "ANTROPOMETRI_DONE"
    db.add(record)
    db.add(student)
    write_ckg_audit(db, current_user, "complete_ckg_anthropometry", "ckg_student", student.id, f"BMI={bmi}")
    db.commit()
    db.refresh(student)
    return student_response(student)


@router.post("/students/{student_id}/ttv", response_model=CKGStudentResponse)
def submit_ttv(
    student_id: int,
    payload: CKGTTVSubmit,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_CKG_ACCESS)),
) -> CKGStudentResponse:
    student = get_student_for_station(db, student_id, "TTV", current_user)
    require_station_access(db, current_user, student.event_id, "TTV")
    record = student.ttv or CKGTTVORM(school_id=student.school_id, student_id=student.id)
    record.school_id = student.school_id
    record.blood_pressure = payload.blood_pressure
    record.pulse = payload.pulse
    record.respiratory_rate = payload.respiratory_rate
    record.temperature = payload.temperature
    record.examined_by = current_user.id
    student.status = "TTV_DONE"
    db.add(record)
    db.add(student)
    write_ckg_audit(db, current_user, "complete_ckg_ttv", "ckg_student", student.id, payload.blood_pressure)
    db.commit()
    db.refresh(student)
    return student_response(student)


@router.post("/students/{student_id}/vision", response_model=CKGStudentResponse)
def submit_vision(
    student_id: int,
    payload: CKGVisionSubmit,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_CKG_ACCESS)),
) -> CKGStudentResponse:
    student = get_student_for_station(db, student_id, "VISUS", current_user)
    require_station_access(db, current_user, student.event_id, "VISUS")
    record = student.vision or CKGVisionORM(school_id=student.school_id, student_id=student.id)
    record.school_id = student.school_id
    record.right_eye = payload.right_eye
    record.left_eye = payload.left_eye
    record.examined_by = current_user.id
    student.status = "VISUS_DONE"
    db.add(record)
    db.add(student)
    write_ckg_audit(db, current_user, "complete_ckg_vision", "ckg_student", student.id, f"{payload.right_eye}/{payload.left_eye}")
    db.commit()
    db.refresh(student)
    return student_response(student)


@router.post("/students/{student_id}/dental", response_model=CKGStudentResponse)
def submit_dental(
    student_id: int,
    payload: CKGDentalSubmit,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_CKG_ACCESS)),
) -> CKGStudentResponse:
    student = get_student_for_station(db, student_id, "GIGI", current_user)
    require_station_access(db, current_user, student.event_id, "GIGI")
    record = student.dental or CKGDentalORM(school_id=student.school_id, student_id=student.id)
    record.school_id = student.school_id
    record.caries = payload.caries
    record.oral_hygiene = payload.oral_hygiene
    record.notes = payload.notes
    record.examined_by = current_user.id
    student.status = "GIGI_DONE"
    db.add(record)
    db.add(student)
    write_ckg_audit(db, current_user, "complete_ckg_dental", "ckg_student", student.id, payload.caries)
    db.commit()
    db.refresh(student)
    return student_response(student)


@router.post("/students/{student_id}/general-screening", response_model=CKGStudentResponse)
def submit_general_screening(
    student_id: int,
    payload: CKGGeneralSubmit,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_CKG_ACCESS)),
) -> CKGStudentResponse:
    student = get_student_for_station(db, student_id, "SCREENING_UMUM", current_user)
    require_station_access(db, current_user, student.event_id, "SCREENING_UMUM")
    record = student.general_screening or CKGGeneralScreeningORM(school_id=student.school_id, student_id=student.id)
    record.school_id = student.school_id
    record.physical_findings = payload.physical_findings
    record.notes = payload.notes
    record.recommendation = payload.recommendation
    record.examined_by = current_user.id
    student.status = "SCREENING_DONE"
    db.add(record)
    db.add(student)
    write_ckg_audit(db, current_user, "complete_ckg_general_screening", "ckg_student", student.id, payload.recommendation)
    db.commit()
    db.refresh(student)
    return student_response(student)


@router.post("/students/{student_id}/complete", response_model=CKGStudentResponse)
def complete_student(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_CKG_ACCESS)),
) -> CKGStudentResponse:
    student = tenant_get(db, CKGStudentORM, student_id, current_user)
    if student is None:
        raise HTTPException(status_code=404, detail="CKG student not found")
    require_station_access(db, current_user, student.event_id, "SCREENING_UMUM")
    if student.status != "SCREENING_DONE":
        raise HTTPException(status_code=400, detail="Student has not finished general screening")
    student.status = "COMPLETED"
    db.add(student)
    write_ckg_audit(db, current_user, "complete_ckg_student", "ckg_student", student.id, student.full_name)
    db.commit()
    db.refresh(student)
    return student_response(student)


@router.post("/students/{student_id}/referrals")
def create_referral(
    student_id: int,
    payload: CKGReferralCreate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_CKG_ACCESS)),
) -> dict:
    student = tenant_get(db, CKGStudentORM, student_id, current_user)
    if student is None:
        raise HTTPException(status_code=404, detail="CKG student not found")
    require_station_access(db, current_user, student.event_id, payload.station)
    referral = CKGReferralORM(
        school_id=student.school_id,
        student_id=student.id,
        station=payload.station,
        reason=payload.reason,
        referral_destination=payload.referral_destination,
        notes=payload.notes,
        created_by=current_user.id,
    )
    student.needs_referral = True
    db.add(referral)
    db.add(student)
    write_ckg_audit(db, current_user, "create_ckg_referral", "ckg_student", student.id, payload.reason)
    db.commit()
    return {"message": "Referral saved"}


@router.get("/dashboard", response_model=CKGDashboardResponse)
def dashboard(
    event_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_CKG_REPORT_ACCESS)),
) -> CKGDashboardResponse:
    event = get_event_or_active(db, current_user, event_id)
    query = tenant_query(db.query(CKGStudentORM), CKGStudentORM, current_user).filter(CKGStudentORM.event_id == event.id)
    students = query.all()
    total = len(students)
    completed = sum(1 for student in students if student.status == "COMPLETED")
    in_progress = sum(1 for student in students if student.status not in ("REGISTERED", "COMPLETED"))
    waiting = sum(1 for student in students if student.status != "COMPLETED")

    station_counts = {station: 0 for station in STATIONS if station != "REGISTRATION"}
    for student in students:
        station = next_station_for_status(student.status)
        if station in station_counts:
            station_counts[station] += 1

    daily_rows = (
        tenant_query(db.query(func.substr(CKGStudentORM.created_at, 1, 10), func.count(CKGStudentORM.id)), CKGStudentORM, current_user)
        .filter(CKGStudentORM.event_id == event.id)
        .group_by(func.substr(CKGStudentORM.created_at, 1, 10))
        .all()
        if db.bind and db.bind.dialect.name == "sqlite"
        else tenant_query(db.query(func.date(CKGStudentORM.created_at), func.count(CKGStudentORM.id)), CKGStudentORM, current_user)
        .filter(CKGStudentORM.event_id == event.id)
        .group_by(func.date(CKGStudentORM.created_at))
        .all()
    )

    recent = query.order_by(CKGStudentORM.id.desc()).limit(8).all()
    referral_students = query.filter(CKGStudentORM.needs_referral.is_(True)).order_by(CKGStudentORM.full_name.asc()).limit(20).all()

    return CKGDashboardResponse(
        total_registered=total,
        completed=completed,
        in_progress=in_progress,
        waiting_queue=waiting,
        completion_percentage=round((completed / total * 100), 2) if total else 0,
        students_per_station=station_counts,
        daily_progress={str(day): count for day, count in daily_rows},
        recent_students=[student_response(student) for student in recent],
        students_needing_referral=[student_response(student) for student in referral_students],
    )


@router.get("/report/pdf")
def event_report_pdf(
    event_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_CKG_REPORT_ACCESS)),
) -> StreamingResponse:
    event = get_event_or_active(db, current_user, event_id)
    dashboard_data = dashboard(event.id, db, current_user)
    students = (
        tenant_query(db.query(CKGStudentORM), CKGStudentORM, current_user)
        .filter(CKGStudentORM.event_id == event.id)
        .order_by(CKGStudentORM.queue_number.asc(), CKGStudentORM.full_name.asc())
        .all()
    )

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=24,
        rightMargin=24,
        topMargin=24,
        bottomMargin=24,
    )
    styles, small_style, tiny_style, section_style = ckg_pdf_styles()
    elements = []
    append_pdf_letterhead(
        elements,
        doc,
        "LAPORAN CKG",
        f"{event.event_name} - Tahun Ajaran {event.academic_year} | Periode: {event.start_date} s/d {event.end_date}",
        styles,
    )

    summary_rows = [
        ["Total Terdaftar", str(dashboard_data.total_registered)],
        ["Selesai", str(dashboard_data.completed)],
        ["Dalam Proses", str(dashboard_data.in_progress)],
        ["Antrian", str(dashboard_data.waiting_queue)],
        ["Persentase Selesai", f"{dashboard_data.completion_percentage}%"],
    ]
    elements.append(Table(summary_rows, colWidths=[160, 320]))
    elements.append(Spacer(1, 16))

    station_rows = [["Station", "Jumlah Antrian"]]
    for station, total in dashboard_data.students_per_station.items():
        station_rows.append([station, str(total)])
    elements.append(Paragraph("Distribusi Per Station", styles["Heading3"]))
    elements.append(Table(station_rows, repeatRows=1, colWidths=[220, 120]))
    elements.append(Spacer(1, 16))

    student_rows = [
        ["Daftar Siswa", "", "", "", "", ""],
        ["No", "Identitas", "Antropometri", "TTV", "Mata & Gigi", "Screening & Rujukan"],
    ]
    for idx, student in enumerate(students, start=1):
        referral_text = "Tidak"
        if student.referrals:
            referral_text = "; ".join(
                f"{ref.station}: {ref.reason} -> {ref.referral_destination}"
                for ref in student.referrals
            )
        anthropometry_text = "-"
        if student.anthropometry:
            anthropometry_text = (
                f"BB: {student.anthropometry.weight} kg\n"
                f"TB: {student.anthropometry.height} cm\n"
                f"BMI: {student.anthropometry.bmi}"
            )
        ttv_text = "-"
        if student.ttv:
            ttv_text = (
                f"TD: {student.ttv.blood_pressure}\n"
                f"Nadi: {student.ttv.pulse} x/menit\n"
                f"RR: {student.ttv.respiratory_rate} x/menit\n"
                f"Suhu: {student.ttv.temperature} C"
            )
        eye_dental_text = []
        if student.vision:
            eye_dental_text.append(f"Visus: R {student.vision.right_eye} / L {student.vision.left_eye}")
        if student.dental:
            eye_dental_text.append(
                f"Gigi: karies {student.dental.caries}; OH {student.dental.oral_hygiene}; {student.dental.notes or '-'}"
            )
        screening_text = []
        if student.general_screening:
            screening_text.append(f"Temuan: {student.general_screening.physical_findings or '-'}")
            screening_text.append(f"Rekom: {student.general_screening.recommendation or '-'}")
        screening_text.append(f"Rujukan: {referral_text}")

        student_rows.append(
            [
                str(idx),
                pdf_cell(
                    f"{student.full_name}\nNIS: {student.nis}\nKelas: {student.class_name or '-'} {student.section or ''}\nStatus: {student.status}",
                    tiny_style,
                ),
                pdf_cell(anthropometry_text, tiny_style),
                pdf_cell(ttv_text, tiny_style),
                pdf_cell("\n".join(eye_dental_text) if eye_dental_text else "-", tiny_style),
                pdf_cell("\n".join(screening_text), tiny_style),
            ]
        )

    table = Table(
        student_rows,
        repeatRows=2,
        colWidths=[24, 116, 76, 88, 150, 270],
    )
    table.setStyle(
        TableStyle(
            [
                ("SPAN", (0, 0), (-1, 0)),
                ("BACKGROUND", (0, 0), (-1, 0), colors.white),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#312e81")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-BoldOblique"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#8b5cf6")),
                ("TEXTCOLOR", (0, 1), (-1, 1), colors.white),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                ("LINEABOVE", (0, 0), (-1, 0), 0, colors.white),
                ("LINEBELOW", (0, 0), (-1, 0), 0, colors.white),
                ("FONTSIZE", (0, 1), (-1, 1), 7),
                ("FONTSIZE", (0, 2), (0, -1), 6.5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    elements.append(table)
    append_pdf_signature(elements, doc, current_user, styles)
    doc.build(elements)
    buffer.seek(0)

    filename = f"laporan_ckg_{event.academic_year.replace('/', '-')}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

def build_summary(student: CKGStudentORM) -> CKGSummaryResponse:
    return CKGSummaryResponse(
        student=student_response(student),
        anthropometry=(
            {"weight": student.anthropometry.weight, "height": student.anthropometry.height, "bmi": student.anthropometry.bmi}
            if student.anthropometry else None
        ),
        ttv=(
            {
                "blood_pressure": student.ttv.blood_pressure,
                "pulse": student.ttv.pulse,
                "respiratory_rate": student.ttv.respiratory_rate,
                "temperature": student.ttv.temperature,
            }
            if student.ttv else None
        ),
        vision=(
            {"right_eye": student.vision.right_eye, "left_eye": student.vision.left_eye}
            if student.vision else None
        ),
        dental=(
            {"caries": student.dental.caries, "oral_hygiene": student.dental.oral_hygiene, "notes": student.dental.notes}
            if student.dental else None
        ),
        general_screening=(
            {
                "physical_findings": student.general_screening.physical_findings,
                "notes": student.general_screening.notes,
                "recommendation": student.general_screening.recommendation,
            }
            if student.general_screening else None
        ),
        referrals=[
            {
                "station": referral.station,
                "reason": referral.reason,
                "referral_destination": referral.referral_destination,
                "notes": referral.notes,
            }
            for referral in student.referrals
        ],
        generated_at=datetime.now(UTC),
    )


@router.get("/students/{student_id}/summary", response_model=CKGSummaryResponse)
def student_summary(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*ROLE_CKG_REPORT_ACCESS)),
) -> CKGSummaryResponse:
    student = tenant_get(db, CKGStudentORM, student_id, current_user)
    if student is None:
        raise HTTPException(status_code=404, detail="CKG student not found")
    return build_summary(student)


@router.get("/students/{student_id}/summary/pdf")
def student_summary_pdf(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> StreamingResponse:
    student = tenant_get(db, CKGStudentORM, student_id, current_user)
    if student is None:
        raise HTTPException(status_code=404, detail="CKG student not found")
    summary = build_summary(student)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=24, bottomMargin=24)
    styles, small_style, _, section_style = ckg_pdf_styles()
    elements = []
    append_pdf_letterhead(elements, doc, "RINGKASAN CKG SISWA", f"NIS: {summary.student.nis}", styles)

    def simple_table(rows: list[list[object]], widths: list[int] | None = None) -> Table:
        table = Table(
            [[pdf_cell(cell, small_style) for cell in row] for row in rows],
            colWidths=widths or [150, doc.width - 150],
            hAlign="LEFT",
        )
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#cbd5e1")),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f5f3ff")),
                    ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#312e81")),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        return table

    identity_rows = [
        ["Nama", summary.student.full_name],
        ["NIS", summary.student.nis],
        ["Kelas", f"{summary.student.class_name or '-'} {summary.student.section or ''}".strip()],
        ["Jenis Kelamin", summary.student.gender],
        ["Tanggal Lahir", summary.student.birth_date or "-"],
        ["Wali Asuh / Orang Tua", summary.student.parent_name or "-"],
        ["No. HP Wali", summary.student.parent_phone or "-"],
        ["Status CKG", summary.student.status],
    ]
    elements.append(Paragraph("Identitas Siswa", section_style))
    elements.append(simple_table(identity_rows))
    elements.append(Spacer(1, 8))

    anthropometry_rows = [
        ["Berat Badan", f"{summary.anthropometry['weight']} kg" if summary.anthropometry else "-"],
        ["Tinggi Badan", f"{summary.anthropometry['height']} cm" if summary.anthropometry else "-"],
        ["BMI", summary.anthropometry["bmi"] if summary.anthropometry else "-"],
    ]
    elements.append(Paragraph("Antropometri", section_style))
    elements.append(simple_table(anthropometry_rows))

    ttv_rows = [
        ["Tekanan Darah", summary.ttv["blood_pressure"] if summary.ttv else "-"],
        ["Nadi", f"{summary.ttv['pulse']} x/menit" if summary.ttv else "-"],
        ["Respiratory Rate", f"{summary.ttv['respiratory_rate']} x/menit" if summary.ttv else "-"],
        ["Suhu", f"{summary.ttv['temperature']} C" if summary.ttv else "-"],
    ]
    elements.append(Paragraph("Tanda-Tanda Vital", section_style))
    elements.append(simple_table(ttv_rows))

    vision_dental_rows = [
        ["Visus Kanan", summary.vision["right_eye"] if summary.vision else "-"],
        ["Visus Kiri", summary.vision["left_eye"] if summary.vision else "-"],
        ["Karies", summary.dental["caries"] if summary.dental else "-"],
        ["Oral Hygiene", summary.dental["oral_hygiene"] if summary.dental else "-"],
        ["Catatan Gigi", summary.dental["notes"] if summary.dental and summary.dental.get("notes") else "-"],
    ]
    elements.append(Paragraph("Visus dan Gigi", section_style))
    elements.append(simple_table(vision_dental_rows))

    screening_rows = [
        ["Temuan Fisik", summary.general_screening["physical_findings"] if summary.general_screening else "-"],
        ["Catatan", summary.general_screening["notes"] if summary.general_screening and summary.general_screening.get("notes") else "-"],
        ["Rekomendasi", summary.general_screening["recommendation"] if summary.general_screening else "-"],
    ]
    elements.append(Paragraph("Screening Umum", section_style))
    elements.append(simple_table(screening_rows))

    referral_rows = []
    if summary.referrals:
        for referral in summary.referrals:
            referral_rows.append(
                [
                    referral["station"],
                    f"Alasan: {referral['reason']}\nTujuan: {referral['referral_destination']}\nCatatan: {referral.get('notes') or '-'}",
                ]
            )
    else:
        referral_rows.append(["Status", "Tidak ada rujukan"])
    elements.append(Paragraph("Rujukan", section_style))
    elements.append(simple_table(referral_rows))
    append_pdf_signature(elements, doc, current_user, styles)
    doc.build(elements)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="ringkasan_ckg_{student.nis}.pdf"'},
    )
