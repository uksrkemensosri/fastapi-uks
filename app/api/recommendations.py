import base64
from datetime import datetime
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.styles import ParagraphStyle
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_roles
from app.auth.tenant import tenant_get, tenant_query
from app.db.dependencies import get_db
from app.db.models import (
    AuditLogORM,
    CKGStudentORM,
    PatientORM,
    RecommendationLetterORM,
    SchoolORM,
    UKSMedicationORM,
    UKSVisitORM,
    UserORM,
)
from app.models.recommendation_schemas import (
    HealthHistoryResponse,
    RecommendationCreate,
    RecommendationResponse,
)

router = APIRouter(prefix="/api", tags=["Student Health Record"])

ROLE_ADMIN = "admin"
ROLE_PERAWAT = "perawat"
ROLE_WALI_ASUH = "wali_asuh"
ROLE_KEPALA_UKSR = "kepala_sekolah"
ROLE_TIM_UKSR = "tim_uksr"
ASSETS_DIR = Path(__file__).resolve().parent.parent / "ui" / "assets"
LOGO_PATH = ASSETS_DIR / "logo-sekolah-rakyat.png"
KEMENSOS_LOGO_PATH = ASSETS_DIR / "logo-kemensoss.png"


def write_audit(
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


def recommendation_response(item: RecommendationLetterORM) -> RecommendationResponse:
    return RecommendationResponse(
        id=item.id,
        letter_number=item.letter_number,
        student_id=item.student_id,
        student_name=item.student_name,
        source_type=item.source_type,
        source_id=item.source_id,
        recommendation_text=item.recommendation_text,
        findings=item.findings,
        created_by=item.created_by,
        created_at=item.created_at,
    )


def generate_letter_number(db: Session, current_user: UserORM) -> str:
    now = datetime.now()
    prefix = f"SR-UKS/{now.year}/{now.month:02d}"
    count = (
        tenant_query(db.query(RecommendationLetterORM), RecommendationLetterORM, current_user)
        .filter(RecommendationLetterORM.letter_number.like(f"{prefix}/%"))
        .count()
    )
    return f"{prefix}/{count + 1:04d}"


def get_patient_or_404(db: Session, patient_id: str, current_user: UserORM) -> PatientORM:
    patient = tenant_get(db, PatientORM, patient_id, current_user)
    if patient is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return patient


def uks_findings(db: Session, visit: UKSVisitORM, current_user: UserORM) -> list[dict]:
    meds = (
        tenant_query(db.query(UKSMedicationORM), UKSMedicationORM, current_user)
        .filter(UKSMedicationORM.visit_id == visit.id)
        .order_by(UKSMedicationORM.id.asc())
        .all()
    )
    return [
        {"label": "Keluhan", "value": visit.complaint},
        {"label": "Hasil Pemeriksaan", "value": visit.examination},
        {"label": "Tindakan", "value": visit.treatment},
        {"label": "Obat", "value": ", ".join(f"{m.medicine_name} ({m.quantity})" for m in meds) or "-"},
    ]


def ckg_abnormal_findings(student: CKGStudentORM) -> list[dict]:
    findings: list[dict] = []
    if student.anthropometry:
        bmi = student.anthropometry.bmi
        if bmi < 18.5 or bmi >= 25:
            findings.append({"label": "Anthropometry", "value": f"BB {student.anthropometry.weight} kg, TB {student.anthropometry.height} cm, BMI {bmi}"})
    if student.ttv:
        findings.append(
            {
                "label": "Vital Signs",
                "value": f"TD {student.ttv.blood_pressure}, Nadi {student.ttv.pulse}, RR {student.ttv.respiratory_rate}, Suhu {student.ttv.temperature}",
            }
        )
    if student.vision and (student.vision.right_eye != "6/6" or student.vision.left_eye != "6/6"):
        findings.append({"label": "Vision", "value": f"Kanan {student.vision.right_eye}, kiri {student.vision.left_eye}"})
    if student.dental:
        dental_text = f"Karies {student.dental.caries}, oral hygiene {student.dental.oral_hygiene}"
        if "tidak" not in student.dental.caries.lower() or "baik" not in student.dental.oral_hygiene.lower():
            findings.append({"label": "Dental", "value": dental_text})
    if student.general_screening and (
        student.general_screening.physical_findings
        or student.general_screening.recommendation
    ):
        findings.append(
            {
                "label": "General Screening",
                "value": f"{student.general_screening.physical_findings or '-'}; {student.general_screening.recommendation or '-'}",
            }
        )
    for referral in student.referrals:
        findings.append({"label": "Referral", "value": f"{referral.reason} -> {referral.referral_destination}"})
    return findings


@router.get("/students/{patient_id}/health-history", response_model=HealthHistoryResponse)
def student_health_history(
    patient_id: str,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_TIM_UKSR, ROLE_WALI_ASUH)),
) -> HealthHistoryResponse:
    patient = get_patient_or_404(db, patient_id, current_user)
    visits = (
        tenant_query(db.query(UKSVisitORM), UKSVisitORM, current_user)
        .filter(UKSVisitORM.patient_id == patient.id)
        .order_by(UKSVisitORM.id.desc())
        .all()
    )
    ckg_students = (
        tenant_query(db.query(CKGStudentORM), CKGStudentORM, current_user)
        .filter(CKGStudentORM.nis == patient.id)
        .order_by(CKGStudentORM.id.desc())
        .all()
    )
    recommendations = (
        tenant_query(db.query(RecommendationLetterORM), RecommendationLetterORM, current_user)
        .filter(RecommendationLetterORM.student_id == patient.id)
        .order_by(RecommendationLetterORM.id.desc())
        .all()
    )

    medicine_rows = []
    for visit in visits:
        meds = (
            tenant_query(db.query(UKSMedicationORM), UKSMedicationORM, current_user)
            .filter(UKSMedicationORM.visit_id == visit.id)
            .order_by(UKSMedicationORM.id.asc())
            .all()
        )
        for med in meds:
            medicine_rows.append(
                {
                    "tanggal": visit.visit_date,
                    "nama_obat": med.medicine_name,
                    "jumlah": med.quantity,
                    "petugas": "-",
                }
            )

    return HealthHistoryResponse(
        biodata={
            "nis": patient.id,
            "nama_lengkap": patient.name,
            "jenis_kelamin": patient.gender,
            "tanggal_lahir": patient.birth_date,
            "kelas": patient.class_name,
            "wali_asuh": getattr(patient, "parent_name", None),
            "nomor_hp_wali_asuh": getattr(patient, "parent_phone", None),
            "tanggal_terdaftar": None,
        },
        uks_visits=[
            {
                "id": visit.id,
                "tanggal": visit.visit_date,
                "keluhan": visit.complaint,
                "tindakan": visit.treatment,
                "obat": ", ".join(
                    med.medicine_name
                    for med in tenant_query(db.query(UKSMedicationORM), UKSMedicationORM, current_user).filter(UKSMedicationORM.visit_id == visit.id).all()
                ),
                "petugas": "-",
                "status": visit.referral_status or "-",
            }
            for visit in visits
        ],
        ckg_history=[
            {
                "id": ckg.id,
                "tahun": ckg.event.academic_year if ckg.event else "-",
                "event": ckg.event.event_name if ckg.event else "-",
                "status": ckg.status,
                "tanggal": ckg.updated_at,
                "needs_referral": ckg.needs_referral,
            }
            for ckg in ckg_students
        ],
        medicine_history=medicine_rows,
        recommendations=[recommendation_response(item) for item in recommendations],
    )


@router.get("/recommendations", response_model=list[RecommendationResponse])
def list_recommendations(
    student_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR)),
) -> list[RecommendationResponse]:
    query = tenant_query(db.query(RecommendationLetterORM), RecommendationLetterORM, current_user)
    if student_id:
        query = query.filter(RecommendationLetterORM.student_id == student_id)
    items = query.order_by(RecommendationLetterORM.id.desc()).all()
    return [recommendation_response(item) for item in items]


@router.post("/recommendations/from-uks/{visit_id}", response_model=RecommendationResponse)
def create_recommendation_from_uks(
    visit_id: int,
    payload: RecommendationCreate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> RecommendationResponse:
    visit = tenant_get(db, UKSVisitORM, visit_id, current_user)
    if visit is None:
        raise HTTPException(status_code=404, detail="UKS visit not found")
    patient = get_patient_or_404(db, visit.patient_id, current_user)
    item = RecommendationLetterORM(
        school_id=visit.school_id,
        letter_number=generate_letter_number(db, current_user),
        student_id=patient.id,
        student_name=patient.name,
        source_type="UKS",
        source_id=str(visit.id),
        recommendation_text=payload.recommendation_text,
        findings=uks_findings(db, visit, current_user),
        created_by=current_user.id,
    )
    db.add(item)
    db.flush()
    write_audit(db, current_user, "generate_recommendation", "recommendation_letter", item.id, f"UKS:{visit.id} student:{patient.id}")
    db.commit()
    db.refresh(item)
    return recommendation_response(item)


@router.post("/recommendations/from-ckg/{student_id}", response_model=RecommendationResponse)
def create_recommendation_from_ckg(
    student_id: int,
    payload: RecommendationCreate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> RecommendationResponse:
    ckg_student = tenant_get(db, CKGStudentORM, student_id, current_user)
    if ckg_student is None:
        raise HTTPException(status_code=404, detail="CKG student not found")
    findings = ckg_abnormal_findings(ckg_student)
    if not findings and not ckg_student.needs_referral:
        raise HTTPException(status_code=400, detail="No abnormal CKG finding or referral flag found")
    item = RecommendationLetterORM(
        school_id=ckg_student.school_id,
        letter_number=generate_letter_number(db, current_user),
        student_id=ckg_student.nis,
        student_name=ckg_student.full_name,
        source_type="CKG",
        source_id=str(ckg_student.id),
        recommendation_text=payload.recommendation_text,
        findings=findings,
        created_by=current_user.id,
    )
    db.add(item)
    db.flush()
    write_audit(db, current_user, "generate_recommendation", "recommendation_letter", item.id, f"CKG:{ckg_student.id} student:{ckg_student.nis}")
    db.commit()
    db.refresh(item)
    return recommendation_response(item)


def signature_image_flowable(user: UserORM | None):
    if not user or not user.signature_image or "," not in user.signature_image:
        return None
    try:
        raw = base64.b64decode(user.signature_image.split(",", 1)[1])
        return Image(BytesIO(raw), width=120, height=54)
    except Exception:
        return None


def _local_image_path(value: str | None) -> Path | None:
    if not value:
        return None
    raw = value.strip()
    if raw.startswith(("http://", "https://", "data:")):
        return None
    candidate = Path(raw.lstrip("/"))
    if not candidate.is_absolute():
        candidate = Path(__file__).resolve().parents[2] / candidate
    return candidate if candidate.exists() else None


def pdf_school_for_user(db: Session, user: UserORM | None, school_id: int | None = None) -> SchoolORM | None:
    resolved_school_id = school_id if school_id is not None else getattr(user, "school_id", None)
    if resolved_school_id is None:
        return None
    return db.get(SchoolORM, resolved_school_id)


def letterhead_flowable(max_width: float, school: SchoolORM | None = None):
    styles = getSampleStyleSheet()
    ministry = ParagraphStyle(
        "DynamicLetterheadMinistry",
        parent=styles["Normal"],
        fontName="Times-Bold",
        fontSize=16,
        leading=18,
        spaceAfter=0,
        alignment=TA_CENTER,
        textColor=colors.black,
    )
    school_style = ParagraphStyle(
        "DynamicLetterheadSchool",
        parent=styles["Normal"],
        fontName="Times-Bold",
        fontSize=12,
        leading=15,
        spaceBefore=1,
        spaceAfter=1,
        alignment=TA_CENTER,
        textColor=colors.black,
    )
    detail = ParagraphStyle(
        "DynamicLetterheadDetail",
        parent=styles["Normal"],
        fontName="Times-Bold",
        fontSize=10,
        leading=11,
        spaceBefore=2,
        alignment=TA_CENTER,
        textColor=colors.black,
    )
    left_logo = Image(str(KEMENSOS_LOGO_PATH), width=72, height=72) if KEMENSOS_LOGO_PATH.exists() else ""
    school_logo_path = _local_image_path(getattr(school, "logo_url", None)) or LOGO_PATH
    right_logo = Image(str(school_logo_path), width=72, height=72) if school_logo_path.exists() else ""
    school_name = getattr(school, "school_name", None) or "Sekolah Rakyat"
    address = getattr(school, "address", None)
    city = getattr(school, "city", None)
    province = getattr(school, "province", None)
    postal_code = getattr(school, "postal_code", None)
    location = ", ".join(part for part in [city, province, postal_code] if part)
    address_line = ", ".join(part for part in [address, location] if part)
    info_lines = [
        Paragraph("KEMENTERIAN SOSIAL REPUBLIK INDONESIA", ministry),
        Paragraph("UNIT KESEHATAN SEKOLAH RAKYAT", ministry),
        Paragraph(school_name, school_style),
    ]
    if address_line:
        info_lines.append(Paragraph(address_line, detail))
    table = Table([[left_logo, info_lines, right_logo]], colWidths=[80, max_width - 160, 80])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (0, 0), "CENTER"),
                ("ALIGN", (2, 0), (2, 0), "CENTER"),
                ("LINEBELOW", (0, 0), (-1, 0), 1.2, colors.black),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def qr_code_flowable(text: str, size: int = 58):
    qr = QrCodeWidget(text)
    bounds = qr.getBounds()
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    drawing = Drawing(
        size,
        size,
        transform=[size / width, 0, 0, size / height, 0, 0],
    )
    drawing.add(qr)
    drawing.hAlign = "RIGHT"
    return drawing


@router.get("/recommendations/{recommendation_id}/pdf")
def recommendation_pdf(
    recommendation_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR)),
) -> StreamingResponse:
    item = tenant_get(db, RecommendationLetterORM, recommendation_id, current_user)
    if item is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    signer = tenant_get(db, UserORM, item.created_by, current_user) if item.created_by else None
    school = pdf_school_for_user(db, current_user, item.school_id)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=42, rightMargin=42, topMargin=20, bottomMargin=28)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "RecommendationTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=13,
        textColor=colors.black,
        spaceBefore=2,
        spaceAfter=4,
    )
    heading_style = ParagraphStyle(
        "RecommendationHeading",
        parent=styles["Heading3"],
        fontName="Helvetica-BoldOblique",
        fontSize=10,
        leading=12,
        textColor=colors.black,
        spaceBefore=7,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "RecommendationBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=11,
        textColor=colors.black,
    )
    table_text = ParagraphStyle(
        "RecommendationTableText",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8,
        leading=9.5,
        textColor=colors.black,
    )
    table_header_text = ParagraphStyle(
        "RecommendationTableHeader",
        parent=table_text,
        fontName="Helvetica-Bold",
        textColor=colors.black,
    )
    right_style = ParagraphStyle(
        "RecommendationRight",
        parent=body_style,
        alignment=TA_RIGHT,
    )
    elements = []

    letterhead = letterhead_flowable(doc.width, school)
    if letterhead:
        elements.append(Spacer(1, 2))
        elements.append(letterhead)
        elements.append(Spacer(1, 6))

    elements.extend(
        [
            Paragraph("SURAT REKOMENDASI PEMERIKSAAN KESEHATAN LANJUTAN", title_style),
            Paragraph(f"Nomor: {item.letter_number}", ParagraphStyle("LetterNumber", parent=body_style, alignment=TA_CENTER)),
            Spacer(1, 8),
            Paragraph("Yth.", body_style),
            Paragraph("Wali Asuh / Orang Tua Siswa", body_style),
            Spacer(1, 6),
            Paragraph(
                "Berdasarkan pemeriksaan kesehatan yang dilakukan oleh UKS Sekolah Rakyat, "
                "kami merekomendasikan siswa berikut untuk melakukan pemeriksaan kesehatan "
                "lanjutan di fasilitas kesehatan terdekat.",
                body_style,
            ),
            Spacer(1, 7),
        ]
    )

    source_date = "-"
    if item.source_type == "UKS":
        visit = tenant_get(db, UKSVisitORM, int(item.source_id), current_user)
        source_date = visit.visit_date if visit else "-"
    elif item.source_type == "CKG":
        ckg_student = tenant_get(db, CKGStudentORM, int(item.source_id), current_user)
        source_date = str(ckg_student.updated_at.date()) if ckg_student and ckg_student.updated_at else "-"

    patient = tenant_get(db, PatientORM, item.student_id, current_user)
    identity = [
        [Paragraph("Nama", table_header_text), Paragraph(item.student_name, table_text)],
        [Paragraph("NIS", table_header_text), Paragraph(item.student_id, table_text)],
        [Paragraph("Kelas", table_header_text), Paragraph(patient.class_name if patient and patient.class_name else "-", table_text)],
        [Paragraph("Tanggal Pemeriksaan", table_header_text), Paragraph(source_date, table_text)],
        [Paragraph("Sumber", table_header_text), Paragraph(item.source_type, table_text)],
    ]
    table = Table(identity, colWidths=[128, doc.width - 128])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9ca3af")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    elements.append(table)
    elements.append(Spacer(1, 6))

    elements.append(Paragraph("Temuan Pemeriksaan", heading_style))
    finding_rows = [[Paragraph("Bagian", table_header_text), Paragraph("Temuan", table_header_text)]] + [
        [
            Paragraph(str(f["label"]), table_text),
            Paragraph(str(f["value"]).replace("\n", "<br/>"), table_text),
        ]
        for f in item.findings
    ]
    findings_table = Table(finding_rows, repeatRows=1, colWidths=[128, doc.width - 128])
    findings_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9ca3af")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    elements.append(findings_table)
    elements.append(Spacer(1, 6))
    elements.append(Paragraph("Rekomendasi", heading_style))
    elements.append(Paragraph(item.recommendation_text, body_style))
    elements.append(Spacer(1, 10))

    signer_name = signer.full_name if signer else "-"
    signer_nip = signer.nip if signer and signer.nip else "-"
    signer_title = signer.jabatan if signer and signer.jabatan else "Perawat Pemeriksa"
    signature_city = school.city if school and school.city else "-"
    school_name = school.school_name if school and school.school_name else "Sekolah Rakyat"
    qr_payload = (
        f"SURAT REKOMENDASI UKS\n"
        f"Sekolah: {school_name}\n"
        f"Nomor: {item.letter_number}\n"
        f"Petugas: {signer_name}\n"
        f"Jabatan: {signer_title}\n"
        f"NIP: {signer_nip}"
    )
    signature_table = Table(
        [
            [
                "",
                [
                    Paragraph(f"{signature_city}, {datetime.now().strftime('%d/%m/%Y')}", right_style),
                    Paragraph(signer_title, right_style),
                    qr_code_flowable(qr_payload),
                    Paragraph(signer_name, right_style),
                    Paragraph(f"NIP. {signer_nip}", right_style),
                ],
            ]
        ],
        colWidths=[doc.width - 190, 190],
    )
    signature_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    elements.append(signature_table)

    doc.build(elements)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
    "Content-Disposition": f"attachment; filename=\"{item.letter_number.replace('/', '-')}.pdf\""
},
    )
