from datetime import UTC, datetime
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_roles
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
            user_id=user.id if user else None,
            username=user.username if user else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            details=details,
        )
    )


def get_event_or_active(db: Session, event_id: int | None = None) -> CKGEventORM:
    event = db.get(CKGEventORM, event_id) if event_id else (
        db.query(CKGEventORM).filter(CKGEventORM.is_active.is_(True)).first()
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
    if user.role == ROLE_ADMIN:
        return

    assignment = (
        db.query(CKGStationAssignmentORM)
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
    patient = db.get(PatientORM, student.nis)
    if patient is None:
        db.add(
            PatientORM(
                id=student.nis,
                name=student.full_name,
                gender=student.gender,
                class_name=student.class_name,
                birth_date=student.birth_date,
                age=0,
            )
        )
    else:
        patient.name = student.full_name
        patient.gender = student.gender
        patient.class_name = student.class_name
        patient.birth_date = student.birth_date
        db.add(patient)


@router.post("/events", response_model=CKGEventResponse, status_code=status.HTTP_201_CREATED)
def create_event(
    payload: CKGEventCreate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN)),
) -> CKGEventResponse:
    if payload.is_active:
        db.query(CKGEventORM).update({CKGEventORM.is_active: False})
    event = CKGEventORM(**payload.model_dump())
    db.add(event)
    db.flush()
    write_ckg_audit(db, current_user, "create_ckg_event", "ckg_event", event.id, event.event_name)
    db.commit()
    db.refresh(event)
    return CKGEventResponse(**event.__dict__)


@router.get("/events", response_model=list[CKGEventResponse])
def list_events(
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> list[CKGEventResponse]:
    events = db.query(CKGEventORM).order_by(CKGEventORM.id.desc()).all()
    return [CKGEventResponse(**event.__dict__) for event in events]


@router.get("/events/active", response_model=CKGEventResponse)
def get_active_event(
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> CKGEventResponse:
    event = get_event_or_active(db)
    return CKGEventResponse(**event.__dict__)


@router.patch("/events/{event_id}", response_model=CKGEventResponse)
def update_event(
    event_id: int,
    payload: CKGEventUpdate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN)),
) -> CKGEventResponse:
    event = db.get(CKGEventORM, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="CKG event not found")

    data = payload.model_dump(exclude_unset=True)
    if data.get("is_active") is True:
        db.query(CKGEventORM).filter(CKGEventORM.id != event_id).update({CKGEventORM.is_active: False})
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
    event = get_event_or_active(db, event_id)
    user = db.get(UserORM, payload.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=404, detail="User not found or inactive")

    assignment = CKGStationAssignmentORM(event_id=event.id, user_id=user.id, station=payload.station)
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
    _: UserORM = Depends(require_roles(ROLE_ADMIN)),
) -> list[CKGStationAssignmentResponse]:
    event = get_event_or_active(db, event_id)
    assignments = (
        db.query(CKGStationAssignmentORM)
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
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> CKGStudentResponse:
    event = get_event_or_active(db, event_id)
    require_station_access(db, current_user, event.id, "REGISTRATION")

    student = CKGStudentORM(
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
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> dict:
    event = get_event_or_active(db, event_id)
    require_station_access(db, current_user, event.id, "REGISTRATION")
    created = 0
    skipped = 0

    for item in payload.students:
        exists = (
            db.query(CKGStudentORM)
            .filter(CKGStudentORM.event_id == event.id, CKGStudentORM.nis == item.nis)
            .first()
        )
        if exists:
            skipped += 1
            continue
        student = CKGStudentORM(
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
    _: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> list[CKGStudentResponse]:
    event = get_event_or_active(db, event_id)
    query = db.query(CKGStudentORM).filter(CKGStudentORM.event_id == event.id)
    if q:
        like_expr = f"%{q.strip()}%"
        query = query.filter((CKGStudentORM.full_name.ilike(like_expr)) | (CKGStudentORM.nis.ilike(like_expr)))
    students = query.order_by(CKGStudentORM.queue_number.asc(), CKGStudentORM.full_name.asc()).all()
    return [student_response(student) for student in students]


@router.get("/stations/{station}/queue", response_model=list[CKGQueueItem])
def station_queue(
    station: str,
    event_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> list[CKGQueueItem]:
    station = normalize_station(station)
    event = get_event_or_active(db, event_id)
    require_station_access(db, current_user, event.id, station)

    if station == "SCREENING_UMUM":
        statuses = ("GIGI_DONE", "SCREENING_DONE")
    else:
        statuses = (QUEUE_STATUS_BY_STATION[station],)

    students = (
        db.query(CKGStudentORM)
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


def get_student_for_station(db: Session, student_id: int, station: str) -> CKGStudentORM:
    student = db.get(CKGStudentORM, student_id)
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
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> CKGStudentResponse:
    student = get_student_for_station(db, student_id, "ANTROPOMETRI")
    require_station_access(db, current_user, student.event_id, "ANTROPOMETRI")
    height_m = payload.height / 100
    bmi = round(payload.weight / (height_m * height_m), 2)
    record = student.anthropometry or CKGAnthropometryORM(student_id=student.id)
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
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> CKGStudentResponse:
    student = get_student_for_station(db, student_id, "TTV")
    require_station_access(db, current_user, student.event_id, "TTV")
    record = student.ttv or CKGTTVORM(student_id=student.id)
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
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> CKGStudentResponse:
    student = get_student_for_station(db, student_id, "VISUS")
    require_station_access(db, current_user, student.event_id, "VISUS")
    record = student.vision or CKGVisionORM(student_id=student.id)
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
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> CKGStudentResponse:
    student = get_student_for_station(db, student_id, "GIGI")
    require_station_access(db, current_user, student.event_id, "GIGI")
    record = student.dental or CKGDentalORM(student_id=student.id)
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
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> CKGStudentResponse:
    student = get_student_for_station(db, student_id, "SCREENING_UMUM")
    require_station_access(db, current_user, student.event_id, "SCREENING_UMUM")
    record = student.general_screening or CKGGeneralScreeningORM(student_id=student.id)
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
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> CKGStudentResponse:
    student = db.get(CKGStudentORM, student_id)
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
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> dict:
    student = db.get(CKGStudentORM, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="CKG student not found")
    require_station_access(db, current_user, student.event_id, payload.station)
    referral = CKGReferralORM(
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
    _: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> CKGDashboardResponse:
    event = get_event_or_active(db, event_id)
    query = db.query(CKGStudentORM).filter(CKGStudentORM.event_id == event.id)
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
        db.query(func.substr(CKGStudentORM.created_at, 1, 10), func.count(CKGStudentORM.id))
        .filter(CKGStudentORM.event_id == event.id)
        .group_by(func.substr(CKGStudentORM.created_at, 1, 10))
        .all()
        if db.bind and db.bind.dialect.name == "sqlite"
        else db.query(func.date(CKGStudentORM.created_at), func.count(CKGStudentORM.id))
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
    _: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> StreamingResponse:
    event = get_event_or_active(db, event_id)
    dashboard_data = dashboard(event.id, db, _)
    students = (
        db.query(CKGStudentORM)
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
    styles = getSampleStyleSheet()
    elements = [
        Paragraph("Laporan CKG", styles["Title"]),
        Paragraph(f"{event.event_name} - Tahun Ajaran {event.academic_year}", styles["Heading2"]),
        Paragraph(f"Periode: {event.start_date} s/d {event.end_date}", styles["Normal"]),
        Spacer(1, 12),
    ]

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
        [
            "No",
            "NIS",
            "Nama",
            "Kelas",
            "BB",
            "TB",
            "BMI",
            "TD",
            "Nadi",
            "RR",
            "Suhu",
            "Visus",
            "Gigi",
            "Screening",
            "Rujukan",
        ]
    ]
    for idx, student in enumerate(students, start=1):
        referral_text = "Tidak"
        if student.referrals:
            referral_text = "; ".join(
                f"{ref.station}: {ref.reason} -> {ref.referral_destination}"
                for ref in student.referrals
            )

        student_rows.append(
            [
                str(idx),
                student.nis,
                student.full_name,
                f"{student.class_name or '-'} {student.section or ''}".strip(),
                str(student.anthropometry.weight) if student.anthropometry else "-",
                str(student.anthropometry.height) if student.anthropometry else "-",
                str(student.anthropometry.bmi) if student.anthropometry else "-",
                student.ttv.blood_pressure if student.ttv else "-",
                str(student.ttv.pulse) if student.ttv else "-",
                str(student.ttv.respiratory_rate) if student.ttv else "-",
                str(student.ttv.temperature) if student.ttv else "-",
                f"R {student.vision.right_eye} / L {student.vision.left_eye}" if student.vision else "-",
                (
                    f"Karies: {student.dental.caries}; OH: {student.dental.oral_hygiene}; "
                    f"{student.dental.notes or ''}"
                    if student.dental else "-"
                ),
                (
                    f"Temuan: {student.general_screening.physical_findings or '-'}; "
                    f"Rekom: {student.general_screening.recommendation or '-'}"
                    if student.general_screening else "-"
                ),
                referral_text,
            ]
        )

    table = Table(
        student_rows,
        repeatRows=1,
        colWidths=[20, 48, 82, 42, 26, 26, 28, 36, 28, 24, 28, 50, 72, 82, 74],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#8b5cf6")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                ("FONTSIZE", (0, 0), (-1, -1), 6),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    elements.append(Paragraph("Daftar Siswa", styles["Heading3"]))
    elements.append(table)
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
    _: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> CKGSummaryResponse:
    student = db.get(CKGStudentORM, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="CKG student not found")
    return build_summary(student)


@router.get("/students/{student_id}/summary/pdf")
def student_summary_pdf(
    student_id: int,
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> StreamingResponse:
    student = db.get(CKGStudentORM, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="CKG student not found")
    summary = build_summary(student)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = [
        Paragraph("Ringkasan CKG Siswa", styles["Title"]),
        Spacer(1, 12),
        Paragraph(f"Nama: {summary.student.full_name}", styles["Normal"]),
        Paragraph(f"NIS: {summary.student.nis}", styles["Normal"]),
        Paragraph(f"Kelas: {summary.student.class_name or '-'} {summary.student.section or ''}", styles["Normal"]),
        Paragraph(f"Status: {summary.student.status}", styles["Normal"]),
        Spacer(1, 12),
    ]

    rows = [["Bagian", "Hasil"]]
    rows.append(["Antropometri", str(summary.anthropometry or "-")])
    rows.append(["TTV", str(summary.ttv or "-")])
    rows.append(["Visus", str(summary.vision or "-")])
    rows.append(["Gigi", str(summary.dental or "-")])
    rows.append(["Screening Umum", str(summary.general_screening or "-")])
    rows.append(["Rujukan", str(summary.referrals or "-")])
    elements.append(Table(rows, colWidths=[120, 360]))
    doc.build(elements)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="ringkasan_ckg_{student.nis}.pdf"'},
    )
