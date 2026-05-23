from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_roles
from app.auth.security import (
    create_access_token,
    get_access_token_expire_seconds,
    hash_password,
    verify_password,
)
from app.core.expert_system import NursingExpertSystem
from app.db.dependencies import get_db
from app.db.models import (
    AssessmentORM,
    PatientORM,
    RecommendationORM,
    UKSMedicationORM,
    UKSVisitORM,
    UserORM,
)
from app.models.schemas import (
    AICareSuggestionRequest,
    AICareSuggestionResponse,
    AssessmentResponse,
    AssessmentSummary,
    ChangePasswordRequest,
    ComplaintStat,
    LoginRequest,
    NursingAssessment,
    Patient,
    PatientCreate,
    PatientAssessmentsResponse,
    PatientSummary,
    TokenResponse,
    UKSDailyReportResponse,
    UKSMedicationCreate,
    UKSMedicationResponse,
    UKSMonthlyReportResponse,
    UKSReferralUpdate,
    UKSVisitCreate,
    UKSVisitResponse,
    UserCreate,
    UserResponse,
)

router = APIRouter(prefix="/api", tags=["EMR Keperawatan"])
expert_system = NursingExpertSystem()


def _build_top_complaints(visits: list[UKSVisitORM], limit: int = 5) -> list[ComplaintStat]:
    counts: dict[str, int] = {}
    for visit in visits:
        key = visit.complaint.strip()
        counts[key] = counts.get(key, 0) + 1
    sorted_items = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [ComplaintStat(complaint=complaint, total=total) for complaint, total in sorted_items[:limit]]


def _validate_date_yyyy_mm_dd(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Date format must be YYYY-MM-DD")
    return value


def _validate_month_yyyy_mm(value: str) -> str:
    try:
        datetime.strptime(f"{value}-01", "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Month format must be YYYY-MM")
    return value


@router.post("/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(payload: UserCreate, db: Session = Depends(get_db)) -> UserResponse:
    existing = db.query(UserORM).filter(UserORM.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    user = UserORM(
        username=payload.username,
        full_name=payload.full_name,
        role=payload.role,
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return UserResponse(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
    )


@router.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(UserORM).filter(UserORM.username == payload.username).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User inactive")

    token = create_access_token(subject=str(user.id), role=user.role)
    return TokenResponse(access_token=token, expires_in=get_access_token_expire_seconds())


@router.post("/auth/refresh", response_model=TokenResponse)
def refresh_token(current_user: UserORM = Depends(get_current_user)) -> TokenResponse:
    token = create_access_token(subject=str(current_user.id), role=current_user.role)
    return TokenResponse(access_token=token, expires_in=get_access_token_expire_seconds())


@router.get("/auth/me", response_model=UserResponse)
def get_me(current_user: UserORM = Depends(get_current_user)) -> UserResponse:
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        full_name=current_user.full_name,
        role=current_user.role,
        is_active=current_user.is_active,
    )


@router.post("/auth/change-password")
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> dict:
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    current_user.password_hash = hash_password(payload.new_password)
    db.add(current_user)
    db.commit()
    return {"message": "Password updated successfully"}


@router.post("/assessment", response_model=AssessmentResponse)
def assess_patient(
    payload: NursingAssessment,
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles("admin", "perawat")),
) -> AssessmentResponse:
    recommendations = expert_system.infer(payload)

    patient = db.get(PatientORM, payload.patient.id)
    if patient is None:
        patient = PatientORM(
            id=payload.patient.id,
            name=payload.patient.name,
            age=payload.patient.age,
            gender=payload.patient.gender,
        )
        db.add(patient)
    else:
        patient.name = payload.patient.name
        patient.age = payload.patient.age
        patient.gender = payload.patient.gender

    assessment = AssessmentORM(
        patient_id=payload.patient.id,
        complaints=payload.complaints,
        observations=payload.observations,
        vital_signs=payload.vital_signs,
    )
    db.add(assessment)
    db.flush()

    for rec in recommendations:
        db.add(
            RecommendationORM(
                assessment_id=assessment.id,
                nanda_code=rec.nanda_code,
                nanda_label=rec.nanda_label,
                confidence=rec.confidence,
                nic=rec.nic,
                noc=rec.noc,
            )
        )

    db.commit()

    return AssessmentResponse(
        patient_id=payload.patient.id,
        recommendations=recommendations,
    )


@router.post("/ai/suggest-care", response_model=AICareSuggestionResponse)
def suggest_care_with_ai(
    payload: AICareSuggestionRequest,
    _: UserORM = Depends(require_roles("admin", "perawat")),
) -> AICareSuggestionResponse:
    assessment = NursingAssessment(
        patient=Patient(id="AI-DRAFT", name="AI Draft", age=0, gender="-"),
        complaints=[payload.complaint],
        observations=[payload.examination],
    )
    recs = expert_system.infer(assessment)

    if recs:
        top = recs[0]
        diagnosis = top.nanda_label
        intervention = "; ".join(top.nic[:3]) if top.nic else "Edukasi dan observasi lanjutan"
        implementation = f"Lakukan {intervention.lower()} sesuai kondisi pasien."
        follow_up = "; ".join(top.noc[:3]) if top.noc else "Evaluasi ulang keluhan dalam 1x24 jam"
        confidence = top.confidence
    else:
        diagnosis = "Perlu asesmen lanjutan"
        intervention = "Observasi tanda vital dan pengkajian keluhan lebih lanjut"
        implementation = "Catat perkembangan keluhan, lakukan observasi, dan berikan edukasi awal."
        follow_up = "Evaluasi ulang kondisi pasien dan pertimbangkan rujukan bila memburuk."
        confidence = 0.2

    return AICareSuggestionResponse(
        diagnosis=diagnosis,
        intervention=intervention,
        implementation=implementation,
        follow_up=follow_up,
        confidence=round(confidence, 2),
    )


@router.post("/patients", response_model=PatientSummary, status_code=status.HTTP_201_CREATED)
def create_patient(
    payload: PatientCreate,
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles("admin", "perawat")),
) -> PatientSummary:
    existing = db.get(PatientORM, payload.id)
    if existing is not None:
        raise HTTPException(status_code=400, detail="Patient ID already exists")

    patient = PatientORM(
        id=payload.id,
        name=payload.name,
        age=payload.age,
        gender=payload.gender,
        class_name=payload.class_name,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return PatientSummary(
        id=patient.id,
        name=patient.name,
        age=patient.age,
        gender=patient.gender,
        class_name=patient.class_name,
    )


@router.get("/patients", response_model=list[PatientSummary])
def get_patients(
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles("admin", "perawat")),
) -> list[PatientSummary]:
    patients = db.query(PatientORM).order_by(PatientORM.name.asc()).all()
    return [
        PatientSummary(id=p.id, name=p.name, age=p.age, gender=p.gender, class_name=p.class_name)
        for p in patients
    ]


@router.get("/patients/search", response_model=list[PatientSummary])
def search_patients(
    q: str,
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles("admin", "perawat")),
) -> list[PatientSummary]:
    keyword = q.strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    like_expr = f"%{keyword}%"
    patients = (
        db.query(PatientORM)
        .filter((PatientORM.id.ilike(like_expr)) | (PatientORM.name.ilike(like_expr)))
        .order_by(PatientORM.name.asc())
        .all()
    )
    return [
        PatientSummary(id=p.id, name=p.name, age=p.age, gender=p.gender, class_name=p.class_name)
        for p in patients
    ]


@router.get("/patients/{patient_id}", response_model=PatientSummary)
def get_patient_detail(
    patient_id: str,
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles("admin", "perawat")),
) -> PatientSummary:
    patient = db.get(PatientORM, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return PatientSummary(
        id=patient.id,
        name=patient.name,
        age=patient.age,
        gender=patient.gender,
        class_name=patient.class_name,
    )


@router.post("/uks/visits", response_model=UKSVisitResponse, status_code=status.HTTP_201_CREATED)
def create_uks_visit(
    payload: UKSVisitCreate,
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles("admin", "perawat")),
) -> UKSVisitResponse:
    patient = db.get(PatientORM, payload.patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    visit = UKSVisitORM(
        patient_id=payload.patient_id,
        visit_date=payload.visit_date,
        complaint=payload.complaint,
        examination=payload.examination,
        treatment=payload.treatment,
        diagnosis=payload.diagnosis,
        notes=payload.notes,
        referral_to=payload.referral_to,
        referral_status=payload.referral_status,
    )
    db.add(visit)
    db.commit()
    db.refresh(visit)

    return UKSVisitResponse(
        id=visit.id,
        patient_id=visit.patient_id,
        visit_date=visit.visit_date,
        complaint=visit.complaint,
        examination=visit.examination,
        treatment=visit.treatment,
        diagnosis=visit.diagnosis,
        notes=visit.notes,
        referral_to=visit.referral_to,
        referral_status=visit.referral_status,
    )
@router.get("/uks/visits")
def get_all_uks_visits(
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles("admin", "perawat")),
):

    visits = (
        db.query(UKSVisitORM)
        .order_by(UKSVisitORM.id.desc())
        .all()
    )

    results = []

    for visit in visits:

        patient = db.get(PatientORM, visit.patient_id)

        results.append({
            "id": visit.id,
            "patient_id": visit.patient_id,
            "patient_name": patient.name if patient else visit.patient_id,
            "visit_date": visit.visit_date,
            "complaint": visit.complaint,
            "diagnosis": visit.diagnosis,
            "treatment": visit.treatment,
        })

    return results


@router.get("/uks/visits/{visit_id}", response_model=UKSVisitResponse)
def get_uks_visit_detail(
    visit_id: int,
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles("admin", "perawat")),
) -> UKSVisitResponse:
    visit = db.get(UKSVisitORM, visit_id)
    if visit is None:
        raise HTTPException(status_code=404, detail="UKS visit not found")

    return UKSVisitResponse(
        id=visit.id,
        patient_id=visit.patient_id,
        visit_date=visit.visit_date,
        complaint=visit.complaint,
        examination=visit.examination,
        treatment=visit.treatment,
        diagnosis=visit.diagnosis,
        notes=visit.notes,
        referral_to=visit.referral_to,
        referral_status=visit.referral_status,
    )


@router.get("/patients/{patient_id}/uks-visits", response_model=list[UKSVisitResponse])
def list_patient_uks_visits(
    patient_id: str,
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles("admin", "perawat")),
) -> list[UKSVisitResponse]:
    patient = db.get(PatientORM, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    visits = (
        db.query(UKSVisitORM)
        .filter(UKSVisitORM.patient_id == patient_id)
        .order_by(UKSVisitORM.id.desc())
        .all()
    )
    return [
        UKSVisitResponse(
            id=v.id,
            patient_id=v.patient_id,
            visit_date=v.visit_date,
            complaint=v.complaint,
            examination=v.examination,
            treatment=v.treatment,
            diagnosis=v.diagnosis,
            notes=v.notes,
            referral_to=v.referral_to,
            referral_status=v.referral_status,
        )
        for v in visits
    ]


@router.post("/uks/visits/{visit_id}/medications", response_model=UKSMedicationResponse, status_code=status.HTTP_201_CREATED)
def add_uks_medication(
    visit_id: int,
    payload: UKSMedicationCreate,
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles("admin", "perawat")),
) -> UKSMedicationResponse:
    visit = db.get(UKSVisitORM, visit_id)
    if visit is None:
        raise HTTPException(status_code=404, detail="UKS visit not found")

    medication = UKSMedicationORM(
        visit_id=visit_id,
        medicine_name=payload.medicine_name,
        dosage=payload.dosage,
        quantity=payload.quantity,
        notes=payload.notes,
    )
    db.add(medication)
    db.commit()
    db.refresh(medication)

    return UKSMedicationResponse(
        id=medication.id,
        visit_id=medication.visit_id,
        medicine_name=medication.medicine_name,
        dosage=medication.dosage,
        quantity=medication.quantity,
        notes=medication.notes,
    )


@router.get("/uks/visits/{visit_id}/medications", response_model=list[UKSMedicationResponse])
def list_uks_medications(
    visit_id: int,
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles("admin", "perawat")),
) -> list[UKSMedicationResponse]:
    visit = db.get(UKSVisitORM, visit_id)
    if visit is None:
        raise HTTPException(status_code=404, detail="UKS visit not found")

    medications = (
        db.query(UKSMedicationORM)
        .filter(UKSMedicationORM.visit_id == visit_id)
        .order_by(UKSMedicationORM.id.asc())
        .all()
    )
    return [
        UKSMedicationResponse(
            id=m.id,
            visit_id=m.visit_id,
            medicine_name=m.medicine_name,
            dosage=m.dosage,
            quantity=m.quantity,
            notes=m.notes,
        )
        for m in medications
    ]


@router.patch("/uks/visits/{visit_id}/referral", response_model=UKSVisitResponse)
def update_uks_referral(
    visit_id: int,
    payload: UKSReferralUpdate,
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles("admin", "perawat")),
) -> UKSVisitResponse:
    visit = db.get(UKSVisitORM, visit_id)
    if visit is None:
        raise HTTPException(status_code=404, detail="UKS visit not found")

    visit.referral_to = payload.referral_to
    visit.referral_status = payload.referral_status
    db.add(visit)
    db.commit()
    db.refresh(visit)

    return UKSVisitResponse(
        id=visit.id,
        patient_id=visit.patient_id,
        visit_date=visit.visit_date,
        complaint=visit.complaint,
        examination=visit.examination,
        treatment=visit.treatment,
        diagnosis=visit.diagnosis,
        notes=visit.notes,
        referral_to=visit.referral_to,
        referral_status=visit.referral_status,
    )


@router.get("/reports/uks/daily", response_model=UKSDailyReportResponse)
def get_uks_daily_report(
    date: str,
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles("admin", "perawat")),
) -> UKSDailyReportResponse:
    date = _validate_date_yyyy_mm_dd(date)
    visits = db.query(UKSVisitORM).filter(UKSVisitORM.visit_date == date).all()
    total_referrals = sum(1 for visit in visits if visit.referral_status == "dirujuk")
    return UKSDailyReportResponse(
        date=date,
        total_visits=len(visits),
        total_referrals=total_referrals,
        top_complaints=_build_top_complaints(visits),
    )


@router.get("/reports/uks/daily/excel")
def get_uks_daily_report_excel(
    date: str,
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles("admin", "perawat")),
) -> StreamingResponse:
    date = _validate_date_yyyy_mm_dd(date)
    visits = (
        db.query(UKSVisitORM)
        .filter(UKSVisitORM.visit_date == date)
        .order_by(UKSVisitORM.id.asc())
        .all()
    )

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Laporan Harian"
    headers = [
        "No",
        "TANGGAL / BULAN",
        "NAMA",
        "USIA",
        "KELAS",
        "KELUHAN",
        "DIAGNOSA",
        "HASIL PEMERIKSAAN SINGKAT",
        "IMPLEMENTASI DAN RENCANA TINDAK LANJUT",
    ]
    sheet.append(headers)

    thin = Side(style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    header_fill = PatternFill(fill_type="solid", fgColor="E5E7EB")
    header_font = Font(bold=True)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    wrap = Alignment(vertical="top", wrap_text=True)

    for col, _ in enumerate(headers, start=1):
        cell = sheet.cell(row=1, column=col)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center
        cell.border = border

    for idx, visit in enumerate(visits, start=1):
        patient = db.get(PatientORM, visit.patient_id)
        try:
            formatted_date = datetime.strptime(visit.visit_date, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            formatted_date = visit.visit_date

        diagnosis = visit.diagnosis or "-"
        hasil_pemeriksaan_singkat = visit.examination
        implementasi_dan_tindak_lanjut = (
            f"{visit.treatment}. {visit.notes}" if visit.notes else visit.treatment
        )

        sheet.append(
            [
                idx,
                formatted_date,
                patient.name if patient else visit.patient_id,
                patient.age if patient else "",
                patient.class_name if patient and patient.class_name else "",
                visit.complaint,
                diagnosis,
                hasil_pemeriksaan_singkat,
                implementasi_dan_tindak_lanjut,
            ]
        )

    widths = {
        "A": 6,
        "B": 16,
        "C": 24,
        "D": 10,
        "E": 12,
        "F": 22,
        "G": 18,
        "H": 58,
        "I": 34,
    }
    for col, width in widths.items():
        sheet.column_dimensions[col].width = width

    for row in sheet.iter_rows(min_row=2, max_row=sheet.max_row, min_col=1, max_col=9):
        for cell in row:
            cell.border = border
            if cell.column in (1, 2, 4, 5):
                cell.alignment = center
            else:
                cell.alignment = wrap

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    filename = f"laporan_harian_uks_{date}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/uks/monthly", response_model=UKSMonthlyReportResponse)
def get_uks_monthly_report(
    month: str,
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles("admin", "perawat")),
) -> UKSMonthlyReportResponse:
    month = _validate_month_yyyy_mm(month)
    month_prefix = f"{month}%"
    visits = db.query(UKSVisitORM).filter(UKSVisitORM.visit_date.like(month_prefix)).all()
    total_referrals = sum(1 for visit in visits if visit.referral_status == "dirujuk")
    return UKSMonthlyReportResponse(
        month=month,
        total_visits=len(visits),
        total_referrals=total_referrals,
        top_complaints=_build_top_complaints(visits),
    )


@router.get("/patients/{patient_id}/assessments", response_model=PatientAssessmentsResponse)
def get_patient_assessments(
    patient_id: str,
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles("admin", "perawat")),
) -> PatientAssessmentsResponse:
    patient = db.get(PatientORM, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    assessments = (
        db.query(AssessmentORM)
        .filter(AssessmentORM.patient_id == patient_id)
        .order_by(AssessmentORM.id.desc())
        .all()
    )

    payload = []
    for a in assessments:
        recs = (
            db.query(RecommendationORM)
            .filter(RecommendationORM.assessment_id == a.id)
            .order_by(RecommendationORM.id.asc())
            .all()
        )
        payload.append(
            AssessmentSummary(
                id=a.id,
                patient_id=a.patient_id,
                complaints=a.complaints,
                observations=a.observations,
                vital_signs=a.vital_signs,
                recommendations=[
                    {
                        "nanda_code": r.nanda_code,
                        "nanda_label": r.nanda_label,
                        "confidence": r.confidence,
                        "nic": r.nic,
                        "noc": r.noc,
                    }
                    for r in recs
                ],
            )
        )

    return PatientAssessmentsResponse(
        patient=PatientSummary(
            id=patient.id,
            name=patient.name,
            age=patient.age,
            gender=patient.gender,
            class_name=patient.class_name,
        ),
        assessments=payload,
    )


@router.get("/assessments/{assessment_id}", response_model=AssessmentSummary)
def get_assessment_detail(
    assessment_id: int,
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles("admin", "perawat")),
) -> AssessmentSummary:
    assessment = db.get(AssessmentORM, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")

    recs = (
        db.query(RecommendationORM)
        .filter(RecommendationORM.assessment_id == assessment.id)
        .order_by(RecommendationORM.id.asc())
        .all()
    )

    return AssessmentSummary(
        id=assessment.id,
        patient_id=assessment.patient_id,
        complaints=assessment.complaints,
        observations=assessment.observations,
        vital_signs=assessment.vital_signs,
        recommendations=[
            {
                "nanda_code": r.nanda_code,
                "nanda_label": r.nanda_label,
                "confidence": r.confidence,
                "nic": r.nic,
                "noc": r.noc,
            }
            for r in recs
        ],
    )

