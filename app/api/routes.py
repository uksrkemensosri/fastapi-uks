from datetime import UTC, date, datetime, timedelta
from html import escape
import base64
import json
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
import string
import unicodedata
import uuid
import requests
from urllib.parse import quote, urlencode
import qrcode
from PIL import Image, ImageOps, UnidentifiedImageError
from dotenv import load_dotenv
try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None
load_dotenv()
from io import BytesIO
from app.api.recommendations import (
    letterhead_flowable,
    pdf_school_for_user,
    signature_image_flowable,
    qr_code_flowable,
)

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, StreamingResponse
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from sqlalchemy.orm import Session
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, A5, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader

from app.auth.dependencies import get_current_user, require_roles
from app.auth.security import (
    create_access_token,
    get_access_token_expire_seconds,
    hash_password,
    verify_password,
)
from app.auth.tenant import (
    assign_school,
    ensure_patient_access,
    guardian_patient_ids,
    guardian_patient_query,
    is_super_admin,
    is_wali_asuh,
    tenant_get,
    tenant_query,
)
from app.core.expert_system import NursingExpertSystem
from app.db.dependencies import get_db
from app.db.models import (
    AssessmentORM,
    AuditLogORM,
    BPJSReferralORM,
    CKGStudentORM,
    GuardianStudentAssignmentORM,
    MedicineInventoryORM,
    PatientORM,
    RecommendationORM,
    RecommendationLetterORM,
    SchoolORM,
    UKSMedicationORM,
    UKSVisitORM,
    UserORM,
    MedicineTransactionORM,
)
from app.models.schemas import (
    AICareSuggestionRequest,
    AICareSuggestionResponse,
    AssessmentResponse,
    AssessmentSummary,
    ChangePasswordRequest,
    ComplaintStat,
    LoginRequest,
    MedicineInventoryCreate,
    AuditLogListResponse,
    AuditLogResponse,
    BPJSReferralCreate,
    BPJSReferralControlUpdate,
    BPJSReferralResponse,
    MedicineInventoryResponse,
    MedicineStockAdjustment,
    MedicineInventoryUpdate,
    NursingAssessment,
    Patient,
    PatientCreate,
    PatientAssessmentsResponse,
    PatientSummary,
    PasswordResetRequest,
    SchoolCreate,
    SchoolResponse,
    SchoolUpdate,
    TokenResponse,
    UKSDailyReportResponse,
    UKSMedicationCreate,
    UKSMedicationResponse,
    UKSMonthlyReportResponse,
    UKSReferralUpdate,
    UKSVisitCreate,
    UKSVisitResponse,
    UserCreate,
    UserCredentialExportRequest,
    GuardianAssignmentUpdate,
    UserProfileUpdate,
    UserUpdate,
    UserResponse,
)

router = APIRouter(prefix="/api", tags=["EMR Keperawatan"])
logger = logging.getLogger(__name__)
expert_system = NursingExpertSystem()
client = (
    OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
        timeout=float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "8")),
        max_retries=0,
    )
    if OpenAI is not None and os.getenv("OPENROUTER_API_KEY")
    else None
)
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-120b:free")

# This limited SDKI list is intentionally scoped to common UKS presentations.
# It is a decision-support allowlist, not a substitute for a nurse assessment.
SDKI_UKS_DIAGNOSES = (
    "Nyeri Akut",
    "Gangguan Rasa Nyaman",
    "Nausea",
    "Hipertermia",
    "Bersihan Jalan Napas Tidak Efektif",
    "Pola Napas Tidak Efektif",
    "Gangguan Pertukaran Gas",
    "Risiko Aspirasi",
    "Hipovolemia",
    "Risiko Hipovolemia",
    "Diare",
    "Konstipasi",
    "Gangguan Integritas Kulit/Jaringan",
    "Risiko Infeksi",
    "Risiko Cedera",
    "Risiko Jatuh",
    "Risiko Alergi",
    "Keletihan",
    "Intoleransi Aktivitas",
    "Ansietas",
    "Koping Tidak Efektif",
    "Defisit Pengetahuan",
)
SDKI_REVIEW_REQUIRED = "Perlu pengkajian lanjutan sebelum menetapkan diagnosis SDKI"
SDKI_ALLOWED_DIAGNOSIS_KEYS = {
    re.sub(r"[^a-z0-9]", "", diagnosis.lower())
    for diagnosis in (*SDKI_UKS_DIAGNOSES, SDKI_REVIEW_REQUIRED)
}

ROLE_ADMIN = "admin"
ROLE_PERAWAT = "perawat"
ROLE_WALI_ASUH = "wali_asuh"
ROLE_SUPER_ADMIN = "super_admin"
ROLE_KEPALA_UKSR = "kepala_sekolah"
ROLE_TIM_UKSR = "tim_uksr"

BPJS_REFERRAL_ROLES = (ROLE_ADMIN, ROLE_PERAWAT, ROLE_TIM_UKSR, ROLE_WALI_ASUH)
BPJS_REFERRAL_READ_ROLES = (*BPJS_REFERRAL_ROLES, ROLE_KEPALA_UKSR, ROLE_SUPER_ADMIN)
BPJS_REFERRAL_UPLOAD_DIR = Path("uploads") / "bpjs_referrals"
BPJS_REFERRAL_ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/pdf": ".pdf",
}
BPJS_REFERRAL_MAX_BYTES = 8 * 1024 * 1024


def _add_months(value: date, months: int) -> date:
    """Add calendar months while keeping a valid day at month end."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    last_day = (date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(value.day, last_day))


def _decode_bpjs_referral_document(document_base64: str, document_name: str) -> tuple[bytes, str, str]:
    try:
        header, encoded = document_base64.split(",", 1) if "," in document_base64 else ("", document_base64)
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Dokumen rujukan tidak valid") from exc
    if not content or len(content) > BPJS_REFERRAL_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Dokumen rujukan maksimal 8 MB")

    content_type = ""
    if content.startswith(b"%PDF-"):
        content_type = "application/pdf"
    elif content.startswith(b"\xff\xd8\xff"):
        content_type = "image/jpeg"
    elif content.startswith(b"\x89PNG\r\n\x1a\n"):
        content_type = "image/png"
    if content_type not in BPJS_REFERRAL_ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Format dokumen harus JPG, PNG, atau PDF")
    safe_name = Path(document_name).name or f"rujukan{BPJS_REFERRAL_ALLOWED_TYPES[content_type]}"
    return content, safe_name, content_type


def _bpjs_referral_response(referral: BPJSReferralORM, patient: PatientORM | None, creator: UserORM | None) -> BPJSReferralResponse:
    return BPJSReferralResponse(
        id=referral.id,
        patient_id=referral.patient_id,
        patient_name=patient.name if patient else referral.patient_id,
        referral_date=str(referral.referral_date),
        valid_until_date=str(referral.valid_until_date),
        control_date=str(referral.control_date) if referral.control_date else None,
        control_done=bool(referral.control_done),
        referring_facility=referral.referring_facility,
        destination_facility=referral.destination_facility,
        referral_number=referral.referral_number,
        complaint=referral.complaint,
        notes=referral.notes,
        status=referral.status,
        document_name=referral.document_name,
        created_by_name=creator.full_name if creator else None,
        created_at=referral.created_at,
    )


def build_local_care_suggestion(complaint: str, examination: str) -> str:
    text = f"{complaint or ''} {examination or ''}".lower()

    def has_any(*terms: str) -> bool:
        return any(term in text for term in terms)

    def make_suggestion(diagnosis: str, intervention: str, implementation: str, follow_up: str) -> str:
        return (
            "Diagnosa Keperawatan:\n"
            f"{diagnosis}\n\n"
            "Tindakan Keperawatan:\n"
            f"{intervention}\n\n"
            "Implementasi dan Pemantauan:\n"
            f"{implementation}\n\n"
            "Tindak Lanjut:\n"
            f"{follow_up}"
        )

    emergency_signs = (
        "sesak berat", "sulit bernapas", "sulit bernafas", "pingsan", "tidak sadar",
        "kejang", "nyeri dada", "perdarahan hebat", "muntah darah", "alergi berat",
        "bibir kebiruan", "sianosis", "spo2 9", "saturasi 9",
    )
    if has_any(*emergency_signs):
        respiratory_emergency = has_any(
            "sesak berat", "sulit bernapas", "sulit bernafas", "bibir kebiruan",
            "sianosis", "spo2 9", "saturasi 9",
        )
        return make_suggestion(
            "Gangguan Pertukaran Gas" if respiratory_emergency else SDKI_REVIEW_REQUIRED,
            "Hentikan aktivitas, dampingi siswa, dan lakukan penilaian awal jalan napas, pernapasan, sirkulasi, kesadaran, serta tanda vital sesuai kewenangan UKS.",
            "Jangan meninggalkan siswa sendiri. Catat waktu kejadian, keluhan, tanda vital, dan tindakan yang telah dilakukan.",
            "Rujuk segera ke fasilitas kesehatan dan hubungi wali asuh/orang tua sesuai prosedur sekolah.",
        )

    # Diagnosis aktual requires more than one vague symptom. This prevents the
    # local fallback from treating a single keyword as a confirmed diagnosis.
    if has_any("nyeri", "sakit gigi", "sakit kepala", "nyeri perut") and has_any(
        "skala", "meringis", "gelisah", "nadi", "sulit tidur", "protektif"
    ):
        return make_suggestion(
            "Nyeri Akut",
            "Kaji lokasi, karakter, durasi, pemicu, dan skala nyeri; fasilitasi istirahat serta tindakan nonfarmakologis sesuai protokol UKS.",
            "Evaluasi keluhan dan respons nonverbal setelah tindakan; dokumentasikan perubahan skala nyeri dan tanda vital yang tersedia.",
            "Hubungi wali asuh atau rujuk bila nyeri memberat, menetap, disertai demam, bengkak, perdarahan, atau keterbatasan fungsi.",
        )
    if has_any("suhu 38", "suhu 39", "suhu 40", "demam") and has_any("hangat", "menggigil", "nadi", "suhu"):
        return make_suggestion(
            "Hipertermia",
            "Ukur ulang suhu dan tanda vital, anjurkan istirahat serta cairan oral bila aman, dan lakukan tindakan penurunan suhu sesuai protokol UKS.",
            "Pantau suhu, tingkat kesadaran, asupan cairan, dan respons setelah tindakan; dokumentasikan hasil pengukuran.",
            "Rujuk atau hubungi wali asuh bila suhu tetap tinggi, kondisi memburuk, kejang, penurunan kesadaran, atau ada tanda dehidrasi.",
        )
    if has_any("mual", "nausea"):
        return make_suggestion(
            "Nausea",
            "Kaji waktu mulai, pemicu, kemampuan minum, dan ada tidaknya muntah; posisikan nyaman serta anjurkan istirahat.",
            "Pantau muntah, nyeri perut, asupan cairan, dan perubahan kondisi; catat faktor pemicu yang dilaporkan.",
            "Hubungi wali asuh atau rujuk bila muntah berulang, nyeri perut hebat, tidak mampu minum, atau muncul tanda bahaya.",
        )
    if has_any("diare", "bab cair", "buang air besar cair"):
        return make_suggestion(
            "Diare",
            "Kaji frekuensi dan karakter BAB, nyeri perut, muntah, asupan cairan, serta tanda dehidrasi; anjurkan istirahat dan cairan oral bila aman.",
            "Pantau kondisi umum, frekuensi BAB, kemampuan minum, dan tanda dehidrasi; dokumentasikan hasil pengkajian.",
            "Hubungi wali asuh atau rujuk bila diare berulang, ada darah, demam tinggi, muntah, lemas berat, atau tidak mampu minum.",
        )
    if has_any("luka", "lecet", "sayat", "abrasi"):
        return make_suggestion(
            "Gangguan Integritas Kulit/Jaringan",
            "Kaji lokasi, ukuran, kedalaman, perdarahan, dan kebersihan luka; lakukan perawatan luka sesuai prosedur UKS.",
            "Dokumentasikan kondisi luka dan respons setelah tindakan; pantau perdarahan, nyeri, pembengkakan, atau tanda infeksi.",
            "Rujuk bila luka dalam, perdarahan sulit berhenti, ada benda asing, luka kotor, atau dicurigai cedera lebih berat.",
        )
    if has_any("jatuh", "terkilir", "benturan", "memar"):
        return make_suggestion(
            "Risiko Cedera",
            "Kaji lokasi cedera, nyeri, bengkak, kemampuan gerak, dan mekanisme kejadian; hentikan aktivitas serta lindungi area yang cedera.",
            "Pantau perubahan nyeri, bengkak, kemampuan gerak, dan kesadaran bila ada benturan; dokumentasikan kejadian.",
            "Rujuk bila deformitas, nyeri berat, keterbatasan gerak bermakna, muntah setelah benturan kepala, atau kondisi memburuk.",
        )
    if has_any("cemas", "takut", "khawatir", "panik"):
        return make_suggestion(
            "Ansietas",
            "Kaji pemicu dan tingkat kecemasan, berikan lingkungan tenang, dengarkan keluhan, dan gunakan komunikasi terapeutik.",
            "Pantau perilaku, tanda fisik kecemasan, kemampuan mengikuti arahan, serta respons setelah diberikan dukungan.",
            "Hubungi wali asuh atau rujuk sesuai prosedur bila ada risiko melukai diri, perilaku tidak terkendali, atau kondisi psikologis memburuk.",
        )
    if has_any("lemas", "capek", "kelelahan") and has_any("olahraga", "aktivitas", "kurang tidur", "setelah"):
        return make_suggestion(
            "Keletihan",
            "Kaji pola istirahat, aktivitas sebelumnya, asupan makan/minum, dan tanda vital; fasilitasi istirahat serta cairan oral bila aman.",
            "Pantau pemulihan energi, pusing, kemampuan berdiri/berjalan, dan respons setelah istirahat.",
            "Evaluasi ulang sebelum siswa kembali beraktivitas; hubungi wali asuh atau rujuk bila lemas menetap, pingsan, atau muncul tanda bahaya.",
        )
    if has_any("batuk") and has_any("dahak", "sekret", "sulit mengeluarkan", "bunyi napas"):
        return make_suggestion(
            "Bersihan Jalan Napas Tidak Efektif",
            "Kaji pola napas, kemampuan mengeluarkan sekret, dan suhu; posisikan nyaman, anjurkan minum bila aman, serta terapkan etika batuk.",
            "Pantau frekuensi napas, usaha napas, kemampuan berbicara, dan respons setelah istirahat.",
            "Rujuk segera bila sesak, napas cepat, bibir kebiruan, demam tinggi, atau kondisi memburuk.",
        )

    return make_suggestion(
        SDKI_REVIEW_REQUIRED,
        "Lengkapi pengkajian fokus: tanda vital, keluhan utama beserta durasi/pemicu, tanda dan gejala pendukung, riwayat singkat, serta kondisi umum siswa.",
        "Dampingi dan istirahatkan siswa sesuai kondisi; pantau perubahan keluhan dan dokumentasikan data pengkajian yang diperoleh.",
        "Validasi diagnosis oleh perawat setelah data cukup. Rujuk atau hubungi wali asuh bila muncul tanda bahaya atau kondisi memburuk.",
    )


def _parse_care_suggestion(result: str) -> tuple[str, str, str, str] | None:
    """Accept only the documented UKS format so free-form AI text cannot fill clinical records."""
    pattern = (
        r"Diagnosa Keperawatan\s*:\s*(?P<diagnosis>.*?)"
        r"(?:\n|\r)+\s*Tindakan Keperawatan\s*:\s*(?P<intervention>.*?)"
        r"(?:\n|\r)+\s*Implementasi dan Pemantauan\s*:\s*(?P<implementation>.*?)"
        r"(?:\n|\r)+\s*Tindak Lanjut\s*:\s*(?P<follow_up>.*)$"
    )
    match = re.search(pattern, result.replace("**", "").strip(), flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    values = tuple(re.sub(r"\s+", " ", match.group(name)).strip() for name in (
        "diagnosis", "intervention", "implementation", "follow_up"
    ))
    if not all(values) or any(len(value) > 1200 for value in values):
        return None
    diagnosis_key = re.sub(r"[^a-z0-9]", "", values[0].lower())
    if diagnosis_key not in SDKI_ALLOWED_DIAGNOSIS_KEYS:
        return None
    return values


def get_openrouter_models() -> list[str]:
    raw_models = os.getenv("OPENROUTER_MODELS") or OPENROUTER_MODEL
    models = [model.strip() for model in raw_models.split(",") if model.strip()]
    if OPENROUTER_MODEL and OPENROUTER_MODEL not in models:
        models.insert(0, OPENROUTER_MODEL)
    return models or ["openai/gpt-oss-120b:free"]


def _user_response(user: UserORM) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        school_id=getattr(user, "school_id", None),
        is_active=user.is_active,
        nip=getattr(user, "nip", None),
        jabatan=getattr(user, "jabatan", None),
        signature_image=getattr(user, "signature_image", None),
        created_at=getattr(user, "created_at", None),
        updated_at=getattr(user, "updated_at", None),
    )


def write_audit_log(
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


def _active_admin_count(db: Session, school_id: int | None = None) -> int:
    query = db.query(UserORM).filter(UserORM.role == ROLE_ADMIN, UserORM.is_active.is_(True))
    if school_id is not None:
        query = query.filter(UserORM.school_id == school_id)
    return query.count()


def _school_response(school: SchoolORM) -> SchoolResponse:
    return SchoolResponse(
        id=school.id,
        school_code=school.school_code,
        school_name=school.school_name,
        province=school.province,
        city=school.city,
        postal_code=school.postal_code,
        address=school.address,
        phone=school.phone,
        email=school.email,
        logo_url=school.logo_url,
        principal_name=school.principal_name,
        is_active=school.is_active,
        created_at=school.created_at,
        updated_at=school.updated_at,
    )


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


def _find_inventory_by_name(
    db: Session,
    medicine_name: str,
    current_user: UserORM | None = None,
) -> MedicineInventoryORM | None:
    query = db.query(MedicineInventoryORM)
    if current_user is not None:
        query = tenant_query(query, MedicineInventoryORM, current_user)
    return (
        query
        .filter(MedicineInventoryORM.name.ilike(medicine_name.strip()))
        .first()
    )


def _append_pdf_letterhead(elements: list, doc: SimpleDocTemplate, title: str, subtitle: str | None, styles, school: SchoolORM | None = None) -> None:
    letterhead = letterhead_flowable(doc.width, school)
    if letterhead:
        elements.append(letterhead)
        elements.append(Spacer(1, 8))
    elements.append(Paragraph(title, styles["Title"]))
    if subtitle:
        elements.append(Paragraph(subtitle, styles["Normal"]))
    elements.append(
        Paragraph(
            f"Tanggal Cetak: {datetime.now().strftime('%d-%m-%Y %H:%M')}",
            styles["Normal"],
        )
    )
    elements.append(Spacer(1, 12))


def _append_pdf_signature(elements: list, doc: SimpleDocTemplate, current_user: UserORM, styles, label: str = "Petugas UKS", school: SchoolORM | None = None) -> None:
    generated_at = datetime.now()
    signer_name = current_user.full_name or "-"
    signer_nip = getattr(current_user, "nip", None) or "-"
    signer_title = getattr(current_user, "jabatan", None) or label
    signature_city = school.city if school and school.city else "-"
    qr_payload = "\n".join(
        [
            f"Nama: {signer_name}",
            f"NIP: {signer_nip}",
            f"Jabatan: {signer_title}",
            f"Sekolah: {school.school_name if school else 'Sekolah Rakyat'}",
            f"Tanggal cetak: {generated_at.strftime('%d/%m/%Y')}",
        ]
    )
    signature_style = styles["Normal"]
    signature_qr = qr_code_flowable(qr_payload, size=58)
    signature_qr.hAlign = "RIGHT"
    table = Table(
        [
            [
                "",
                [
                    Paragraph(f"{signature_city}, {generated_at.strftime('%d/%m/%Y')}", signature_style),
                    Paragraph(signer_title, signature_style),
                    signature_qr,
                    Paragraph(signer_name, signature_style),
                    Paragraph(f"NIP. {signer_nip}", signature_style),
                ],
            ]
        ],
        colWidths=[doc.width - 190, 190],
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    elements.append(Spacer(1, 18))
    elements.append(table)


def _build_patient_import_template_workbook() -> Workbook:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Template Import Siswa"
    headers = [
        "NIS",
        "Nama Lengkap",
        "Jenis Kelamin",
        "Tanggal Lahir",
        "Kelas",
        "Nama Wali Asuh",
        "Nomor HP Wali Asuh",
        "NIK",
        "No RM",
    ]
    examples = [
        ["01010001", "Contoh Siswa Laki-Laki", "Laki-Laki", "2010-01-15", "1A", "Ibu Contoh", "081234567890"],
        ["01010002", "Contoh Siswa Perempuan", "Perempuan", "2010-05-21", "1B", "Bapak Contoh", "082123456789"],
    ]
    sheet.append(headers)
    for row in examples:
        sheet.append([*row, None, None])
    for column in ("H", "I"):
        for cell in sheet[column]:
            cell.number_format = "@"

    header_fill = PatternFill("solid", fgColor="8B5CF6")
    header_font = Font(bold=True, color="FFFFFF")
    thin = Side(style="thin", color="CBD5E1")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    for row in sheet.iter_rows(min_row=2, max_row=sheet.max_row, max_col=len(headers)):
        for cell in row:
            cell.border = border
            cell.alignment = Alignment(vertical="center")
    widths = [18, 32, 18, 18, 12, 28, 24, 24, 18]
    for idx, width in enumerate(widths, start=1):
        sheet.column_dimensions[sheet.cell(row=1, column=idx).column_letter].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:I{sheet.max_row}"

    notes = workbook.create_sheet("Petunjuk")
    notes.append(["Kolom", "Keterangan"])
    notes_rows = [
        ["NIS", "Wajib. Nomor induk siswa atau ID siswa. Simpan sebagai teks agar angka 0 di depan tidak hilang."],
        ["NIK", "Opsional. Teks 16 digit, jangan mengganti NIS. Kolom kosong tidak menghapus NIK yang sudah tersimpan."],
        ["No RM", "Opsional. Nomor rekam medis yang sudah ditetapkan sekolah. Kolom kosong tidak menghapus No. RM yang sudah tersimpan."],
        ["Nama Lengkap", "Wajib. Nama lengkap siswa."],
        ["Jenis Kelamin", "Opsional. Contoh: Laki-Laki / Perempuan / L / P."],
        ["Tanggal Lahir", "Opsional. Gunakan format yyyy-mm-dd, contoh 2010-01-15."],
        ["Kelas", "Opsional. Contoh: 1A, 1B, 7A."],
        ["Nama Wali Asuh", "Opsional. Nama wali asuh atau orang tua."],
        ["Nomor HP Wali Asuh", "Opsional. Nomor WhatsApp wali asuh, contoh 081234567890."],
    ]
    for row in notes_rows:
        notes.append(row)
    for cell in notes[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    for row in notes.iter_rows(min_row=2, max_row=notes.max_row, max_col=2):
        for cell in row:
            cell.border = border
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    notes.column_dimensions["A"].width = 24
    notes.column_dimensions["B"].width = 78
    return workbook


def _build_medicine_import_template_workbook() -> Workbook:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Template Import Obat"
    headers = ["Nama Obat", "Satuan", "Stok Awal", "Stok Minimum", "Catatan"]
    examples = [
        ["Paracetamol 500mg", "tablet", 100, 20, "Stok awal UKS"],
        ["Betadine", "botol", 12, 5, "Contoh obat luar"],
        ["Oralit", "sachet", 50, 10, "Contoh stok sachet"],
    ]
    sheet.append(headers)
    for row in examples:
        sheet.append(row)

    header_fill = PatternFill("solid", fgColor="8B5CF6")
    header_font = Font(bold=True, color="FFFFFF")
    thin = Side(style="thin", color="CBD5E1")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    for row in sheet.iter_rows(min_row=2, max_row=sheet.max_row, max_col=len(headers)):
        for cell in row:
            cell.border = border
            cell.alignment = Alignment(vertical="center")
    widths = [32, 18, 14, 16, 36]
    for idx, width in enumerate(widths, start=1):
        sheet.column_dimensions[sheet.cell(row=1, column=idx).column_letter].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:E{sheet.max_row}"

    notes = workbook.create_sheet("Petunjuk")
    notes.append(["Kolom", "Keterangan"])
    notes_rows = [
        ["Nama Obat", "Wajib. Nama obat atau ALKES. Jika nama sudah ada, data stok akan diperbarui."],
        ["Satuan", "Opsional. Contoh: tablet, sirup, sachet, botol. Jika kosong akan diisi tablet."],
        ["Stok Awal", "Opsional. Angka stok terkini. Jika obat sudah ada, stok akan dikoreksi ke angka ini."],
        ["Stok Minimum", "Opsional. Batas minimum stok rendah. Jika kosong akan diisi 10."],
        ["Catatan", "Opsional. Masuk ke catatan mutasi saat import."],
    ]
    for row in notes_rows:
        notes.append(row)
    for cell in notes[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    for row in notes.iter_rows(min_row=2, max_row=notes.max_row, max_col=2):
        for cell in row:
            cell.border = border
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    notes.column_dimensions["A"].width = 22
    notes.column_dimensions["B"].width = 82
    return workbook


def normalize_whatsapp_number(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    if not digits:
        return None
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    elif digits.startswith("8"):
        digits = "62" + digits
    if len(digits) < 10:
        return None
    return digits


def send_whatsapp_message(target_phone: str | None, message: str) -> tuple[str, str]:
    token = os.getenv("FONNTE_TOKEN")

    if not token:
        logger.warning("Fonnte notification skipped: token is not configured")
        return "skipped", "FONNTE_TOKEN belum diisi"

    target = normalize_whatsapp_number(target_phone)
    if not target:
        logger.warning("Fonnte notification skipped: guardian phone number is invalid")
        return "skipped", "Nomor wali asuh belum valid"

    try:
        response = requests.post(
            os.getenv("FONNTE_API_URL", "https://api.fonnte.com/send"),
            headers={"Authorization": token},
            data={
                "target": target,
                "message": message
            },
            timeout=10,
        )

        if response.ok:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            process = str(payload.get("process") or "").lower()
            detail = str(payload.get("detail") or payload.get("message") or response.text)
            if process == "pending" or "message in queue" in detail.lower():
                logger.info("Fonnte notification queued")
                return "queued", "WhatsApp masuk antrean"
            if payload and payload.get("status") is False:
                logger.warning("Fonnte rejected a notification request")
                return "failed", detail[:300]
            logger.info("Fonnte notification sent")
            return "sent", "WhatsApp sukses"

        logger.warning("Fonnte notification failed with HTTP %s", response.status_code)
        return "failed", f"HTTP {response.status_code}: {response.text[:300]}"

    except Exception as exc:
        logger.exception("Fonnte notification request failed")
        return "failed", str(exc)


def friendly_whatsapp_message(status_text: str | None, message: str | None = None) -> str:
    if status_text == "sent":
        return "WhatsApp sukses"
    if status_text == "queued":
        return "WhatsApp masuk antrean"
    if status_text == "skipped":
        return message if message and not message.lstrip().startswith("{") else "WhatsApp belum dikirim"
    if status_text == "failed":
        return "WhatsApp gagal"
    return message or "-"


def build_uks_visit_whatsapp_message(patient: PatientORM, visit: UKSVisitORM) -> str:
    parent_name = patient.parent_name or "Wali Asuh"

    tanggal = (
        visit.visit_date.strftime("%d %B %Y")
        if hasattr(visit.visit_date, "strftime")
        else str(visit.visit_date)
    )

    waktu = (
        visit.created_at.strftime("%H.%M WIB")
        if getattr(visit, "created_at", None)
        else "-"
    )

    return f"""🏥 *EMR UKS - Sekolah Rakyat*

Yth. {parent_name},

Mohon izin menginformasikan bahwa siswa berikut telah mendapatkan pelayanan di Unit Kesehatan Sekolah (UKS).

━━━━━━━━━━━━━━━━━━

👤 *Nama Siswa*
{patient.name}

🏫 *Kelas*
{patient.class_name}

📅 *Tanggal Pemeriksaan*
{tanggal}

🤒 *Keluhan*
{visit.complaint or "-"}

🩺 *Diagnosis*
{visit.diagnosis or "-"}

💊 *Tindakan*
{visit.treatment or "-"}

━━━━━━━━━━━━━━━━━━

Mohon memantau kondisi siswa di asrama. Apabila terdapat keluhan lanjutan atau kondisi memburuk, silakan berkoordinasi dengan petugas UKS.

Terima kasih atas perhatian dan kerja samanya.

━━━━━━━━━━━━━━━━━━
*EMR UKS*
Sekolah Rakyat
Kementerian Sosial RI
"""


def build_referral_whatsapp_message(patient: PatientORM, visit: UKSVisitORM) -> str:
    parent_name = patient.parent_name or "Wali Asuh / Orang Tua"
    return f"""🏥 *EMR UKS - Sekolah Rakyat*

Yth. {parent_name},

Siswa {patient.name} membutuhkan tindak lanjut/rujukan.

📅 Tanggal kunjungan: {visit.visit_date}
🤒 Keluhan: {visit.complaint}
🩺 Diagnosa: {visit.diagnosis or "-"}
📄 Tujuan rujukan: {visit.referral_to or visit.referral_place or "-"}

Mohon dilakukan pemantauan dan tindak lanjut sesuai arahan petugas UKS."""


def build_control_whatsapp_message(patient: PatientORM, visit: UKSVisitORM) -> str:
    parent_name = patient.parent_name or "Wali Asuh / Orang Tua"
    return f"""[EMR UKS Sekolah Rakyat]

Yth. {parent_name},

Pengingat jadwal kontrol siswa {patient.name}.

Tanggal kontrol: {visit.control_date or "-"}
Tempat kontrol: {visit.referral_place or visit.referral_to or "-"}
Diagnosa: {visit.diagnosis or "-"}

Mohon wali asuh/orang tua memastikan jadwal kontrol terlaksana."""


def build_rest_letter_whatsapp_message(patient: PatientORM, visit: UKSVisitORM) -> str:
    parent_name = patient.parent_name or "Wali Asuh / Orang Tua"
    return f"""[EMR UKS Sekolah Rakyat]

Yth. {parent_name},

Surat izin istirahat UKS untuk siswa {patient.name} telah dibuat.

Tanggal kunjungan: {visit.visit_date}
Keluhan: {visit.complaint}
Diagnosa: {visit.diagnosis or "-"}

Silakan cek surat izin dari petugas UKS."""


@router.get("/schools", response_model=list[SchoolResponse])
def list_schools(
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles(ROLE_SUPER_ADMIN)),
) -> list[SchoolResponse]:
    schools = db.query(SchoolORM).order_by(SchoolORM.school_name.asc()).all()
    return [_school_response(school) for school in schools]


@router.post("/schools", response_model=SchoolResponse, status_code=status.HTTP_201_CREATED)
def create_school(
    payload: SchoolCreate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_SUPER_ADMIN)),
) -> SchoolResponse:
    existing = db.query(SchoolORM).filter(SchoolORM.school_code == payload.school_code).first()
    if existing:
        raise HTTPException(status_code=400, detail="School code already exists")
    school = SchoolORM(**payload.model_dump())
    db.add(school)
    db.flush()
    write_audit_log(db, current_user, "create_school", "school", school.id, school.school_name)
    db.commit()
    db.refresh(school)
    return _school_response(school)


@router.put("/schools/{school_id}", response_model=SchoolResponse)
def update_school(
    school_id: int,
    payload: SchoolUpdate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_SUPER_ADMIN)),
) -> SchoolResponse:
    school = db.get(SchoolORM, school_id)
    if school is None:
        raise HTTPException(status_code=404, detail="School not found")
    if payload.school_code and payload.school_code != school.school_code:
        existing = db.query(SchoolORM).filter(SchoolORM.school_code == payload.school_code).first()
        if existing:
            raise HTTPException(status_code=400, detail="School code already exists")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(school, field, value)
    db.add(school)
    write_audit_log(db, current_user, "edit_school", "school", school.id, school.school_name)
    db.commit()
    db.refresh(school)
    return _school_response(school)


@router.delete("/schools/{school_id}")
def delete_school(
    school_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_SUPER_ADMIN)),
) -> dict:
    school = db.get(SchoolORM, school_id)
    if school is None:
        raise HTTPException(status_code=404, detail="School not found")
    school.is_active = False
    db.add(school)
    action = "deactivate_school"
    write_audit_log(db, current_user, action, "school", school_id, school.school_name)
    db.commit()
    return {"message": "School updated"}


@router.post("/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> UserResponse:
    existing = db.query(UserORM).filter(UserORM.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    if is_super_admin(current_user):
        if payload.role != ROLE_SUPER_ADMIN and payload.school_id is None:
            raise HTTPException(status_code=400, detail="school_id is required for school users")
        school_id = payload.school_id
    else:
        if payload.role == ROLE_SUPER_ADMIN:
            raise HTTPException(status_code=403, detail="Only super_admin can create super_admin users")
        school_id = current_user.school_id

    user = UserORM(
        school_id=school_id,
        username=payload.username,
        full_name=payload.full_name,
        role=payload.role,
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    db.flush()
    write_audit_log(db, current_user, "create_user", "user", user.id, f"Created user {user.username}")
    db.commit()
    db.refresh(user)

    return _user_response(user)


@router.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(UserORM).filter(UserORM.username == payload.username).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User inactive")

    token = create_access_token(subject=str(user.id), role=user.role, school_id=user.school_id)
    request.session["user"] = {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "school_id": user.school_id,
    }
    response.set_cookie(
        "access_token",
        token,
        httponly=True,
        samesite="lax",
        secure=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
        max_age=get_access_token_expire_seconds(),
    )
    write_audit_log(db, user, "login", "session", user.id, "User logged in")
    db.commit()
    return TokenResponse(
        access_token=token,
        expires_in=get_access_token_expire_seconds(),
        role=user.role,
        school_id=user.school_id,
    )


@router.post("/auth/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> dict:
    write_audit_log(db, current_user, "logout", "session", current_user.id, "User logged out")
    db.commit()
    request.session.clear()
    response.delete_cookie("access_token")
    return {"message": "Logged out"}


@router.post("/auth/refresh", response_model=TokenResponse)
def refresh_token(current_user: UserORM = Depends(get_current_user)) -> TokenResponse:
    token = create_access_token(subject=str(current_user.id), role=current_user.role, school_id=current_user.school_id)
    return TokenResponse(
        access_token=token,
        expires_in=get_access_token_expire_seconds(),
        role=current_user.role,
        school_id=current_user.school_id,
    )


@router.get("/auth/me", response_model=UserResponse)
def get_me(request: Request, current_user: UserORM = Depends(get_current_user)) -> UserResponse:
    request.session["user"] = {
        "id": current_user.id,
        "username": current_user.username,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "school_id": current_user.school_id,
    }
    return _user_response(current_user)


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


@router.patch("/auth/profile", response_model=UserResponse)
def update_profile(
    payload: UserProfileUpdate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(get_current_user),
) -> UserResponse:
    if payload.full_name is not None:
        current_user.full_name = payload.full_name
    if payload.nip is not None:
        current_user.nip = payload.nip
    if payload.jabatan is not None:
        current_user.jabatan = payload.jabatan
    if payload.signature_image is not None:
        if payload.signature_image and not payload.signature_image.startswith("data:image/"):
            raise HTTPException(status_code=400, detail="Signature image must be a PNG/JPG data URL")
        current_user.signature_image = payload.signature_image

    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return _user_response(current_user)


@router.post("/assessment", response_model=AssessmentResponse)
def assess_patient(
    payload: NursingAssessment,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_TIM_UKSR)),
) -> AssessmentResponse:
    recommendations = expert_system.infer(payload)

    patient = tenant_get(db, PatientORM, payload.patient.id, current_user)
    if patient is None:
        patient = PatientORM(
            school_id=current_user.school_id,
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
        school_id=patient.school_id,
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
                school_id=patient.school_id,
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
    _: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_TIM_UKSR)),
) -> AICareSuggestionResponse:

    allowed_diagnoses = "\n".join(f"- {diagnosis}" for diagnosis in SDKI_UKS_DIAGNOSES)

    prompt = f"""
Anda membantu dokumentasi petugas UKS sekolah di Indonesia, bukan menggantikan dokter.

Gunakan hanya informasi yang tersedia. Jangan mengarang hasil pemeriksaan, obat, diagnosis medis, atau angka tanda vital.
Gunakan satu diagnosis keperawatan SDKI yang paling sesuai dari daftar yang diizinkan. Jangan gabungkan dua diagnosis.
Diagnosis aktual hanya boleh dipilih bila keluhan dan tanda/gejala pendukungnya tertulis. Diagnosis risiko hanya boleh dipilih bila faktor risikonya tertulis.
Bila data tidak cukup untuk menetapkan diagnosis SDKI, tulis persis: "{SDKI_REVIEW_REQUIRED}". Jangan memaksakan diagnosis umum.
Prioritaskan keselamatan: bila ada tanda bahaya seperti sesak, penurunan kesadaran, kejang, perdarahan aktif, nyeri dada, saturasi rendah, atau kondisi memburuk, tulis rujuk segera.
Tindakan hanya yang dapat dilakukan dalam kewenangan dan protokol UKS. Obat hanya boleh disebut sebagai "sesuai protokol UKS" tanpa menentukan dosis baru.

Daftar diagnosis SDKI yang diizinkan untuk UKS:
{allowed_diagnoses}

Keluhan siswa:
{payload.complaint}

Hasil pemeriksaan UKS:
{payload.examination}

Jawab hanya dengan format persis berikut, tanpa pembuka/penutup lain:

Diagnosa Keperawatan:
Tulis tepat satu label dari daftar di atas, tanpa kode, etiologi, atau penjelasan tambahan.

Tindakan Keperawatan:
2-4 tindakan praktis, spesifik, dan aman untuk petugas UKS.

Implementasi dan Pemantauan:
Apa yang dilakukan sekarang dan parameter/kondisi yang perlu dipantau atau dievaluasi ulang.

Tindak Lanjut:
Kapan kembali aktivitas, kapan hubungi wali asuh, dan kapan rujuk bila diperlukan.

Gunakan Bahasa Indonesia profesional, ringkas, dan cocok untuk dokumentasi UKS.
"""

    parsed: tuple[str, str, str, str] | None = None
    ai_source = "local_fallback"
    model_used = None
    if client is not None and os.getenv("OPENROUTER_API_KEY"):
        for model_name in get_openrouter_models():
            try:
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": "Ikuti format dokumentasi UKS yang diminta secara persis dan utamakan keselamatan siswa.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                    max_tokens=420,
                )
                parsed = _parse_care_suggestion(response.choices[0].message.content or "")
                if parsed:
                    ai_source = "online"
                    model_used = model_name
                    break
            except Exception:
                continue

    if not parsed:
        parsed = _parse_care_suggestion(build_local_care_suggestion(payload.complaint, payload.examination))

    assert parsed is not None
    diagnosis, intervention, implementation, follow_up = parsed

    return AICareSuggestionResponse(
        diagnosis=diagnosis,
        intervention=intervention,
        implementation=implementation,
        follow_up=follow_up,
        confidence=0.9 if ai_source == "online" else 0.8,
        source=ai_source,
        model=model_used,
    )
@router.post("/patients", response_model=PatientSummary, status_code=status.HTTP_201_CREATED)
def create_patient(
    payload: PatientCreate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_TIM_UKSR)),
) -> PatientSummary:
    existing = tenant_get(db, PatientORM, payload.id, current_user)
    if existing is not None:
        raise HTTPException(status_code=400, detail="Patient ID already exists")

    patient = PatientORM(
        school_id=current_user.school_id,
        id=payload.id,
        medical_record_number=payload.medical_record_number,
        name=payload.name,
        nik=payload.nik,
        age=payload.age,
        gender=payload.gender,
        class_name=payload.class_name,
        birth_date=payload.birth_date,
        parent_name=payload.parent_name,
        parent_phone=payload.parent_phone,
    )
    db.add(patient)
    write_audit_log(db, current_user, "create_patient", "patient", patient.id, f"Created patient {patient.name}")
    db.commit()
    db.refresh(patient)
    return PatientSummary(
        id=patient.id,
        nik=patient.nik,
        medical_record_number=patient.medical_record_number,
        photo_url=_patient_photo_url(patient),
        name=patient.name,
        age=patient.age,
        gender=patient.gender,
        class_name=patient.class_name,
        birth_date=patient.birth_date,
        parent_name=patient.parent_name,
        parent_phone=patient.parent_phone,
    )


@router.get("/patients", response_model=list[PatientSummary])
def get_patients(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_TIM_UKSR, ROLE_WALI_ASUH)),
) -> list[PatientSummary]:

    patients = (
        guardian_patient_query(
            tenant_query(db.query(PatientORM), PatientORM, current_user), current_user, db
        )
        .order_by(PatientORM.name.asc())
        .all()
    )

    return [

        PatientSummary(
            id=p.id,
            nik=p.nik,
            medical_record_number=p.medical_record_number,
            photo_url=_patient_photo_url(p),
            name=p.name,
            age=p.age,
            gender=p.gender,
            class_name=p.class_name,
            birth_date=p.birth_date,
            parent_name=p.parent_name,
            parent_phone=p.parent_phone,
        )

        for p in patients

    ]


@router.get("/patients/search", response_model=list[PatientSummary])
def search_patients(
    q: str,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_TIM_UKSR, ROLE_WALI_ASUH)),
) -> list[PatientSummary]:
    keyword = q.strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    like_expr = f"%{keyword}%"
    patients = (
        guardian_patient_query(
            tenant_query(db.query(PatientORM), PatientORM, current_user), current_user, db
        )
        .filter((PatientORM.id.ilike(like_expr)) | (PatientORM.name.ilike(like_expr)) | (PatientORM.nik.ilike(like_expr)))
        .order_by(PatientORM.name.asc())
        .all()
    )
    return [
        PatientSummary(
            id=p.id,
            nik=p.nik,
            medical_record_number=p.medical_record_number,
            photo_url=_patient_photo_url(p),
            name=p.name,
            age=p.age,
            gender=p.gender,
            class_name=p.class_name,
            birth_date=p.birth_date,
            parent_name=p.parent_name,
            parent_phone=p.parent_phone,
        )
        for p in patients
    ]


@router.get("/patients/import-template")
def download_patients_import_template(
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> StreamingResponse:
    workbook = _build_patient_import_template_workbook()
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="template_import_siswa_uks.xlsx"'},
    )


@router.get("/patients/card-data-export")
def export_patient_card_data(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> StreamingResponse:
    patients = (
        tenant_query(db.query(PatientORM), PatientORM, current_user)
        .order_by(PatientORM.class_name.asc(), PatientORM.name.asc())
        .all()
    )
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data Kartu Canva"
    headers = ["No RM", "Nama", "NIS", "NIK", "Kelas"]
    sheet.append(headers)
    for patient in patients:
        sheet.append([
            _excel_text(patient.medical_record_number),
            _excel_text(patient.name),
            _excel_text(patient.id),
            _excel_text(patient.nik),
            _excel_text(patient.class_name),
        ])
    header_fill = PatternFill("solid", fgColor="1D4ED8")
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for column in ("A", "B", "C", "D", "E"):
        sheet.column_dimensions[column].width = {"A": 16, "B": 32, "C": 18, "D": 22, "E": 16}[column]
    for row in sheet.iter_rows(min_row=2, max_row=sheet.max_row):
        for cell in row:
            cell.number_format = "@"
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:E{sheet.max_row}"

    guide = workbook.create_sheet("Petunjuk Canva")
    guide.append(["Field Canva", "Kolom Excel"])
    for row in (("no_rm", "No RM"), ("nama", "Nama"), ("nis", "NIS"), ("nik", "NIK"), ("kelas", "Kelas")):
        guide.append(row)
    guide.column_dimensions["A"].width = 24
    guide.column_dimensions["B"].width = 24

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    write_audit_log(db, current_user, "export_patient_card_data", "patient", None, f"total={len(patients)}")
    db.commit()
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="data_kartu_canva_sehati.xlsx"'},
    )


CARD_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "ui" / "assets" / "card-templates"
CARD_FRONT_TEMPLATE = CARD_TEMPLATE_DIR / "kartu-pelajar-depan.png"
CARD_BACK_TEMPLATE = CARD_TEMPLATE_DIR / "kartu-pelajar-belakang.png"
CARD_WIDTH = 85.6 * mm
CARD_HEIGHT = 54 * mm
CARD_TEMPLATE_WIDTH = 1579
CARD_TEMPLATE_HEIGHT = 996
CARD_RENDERER_VERSION = "2026-09-24-photo-frame-v2"
STUDENT_PHOTO_DIR = Path("uploads") / "student_photos"
STUDENT_PHOTO_MAX_BYTES = 3 * 1024 * 1024
STUDENT_PHOTO_MAX_PIXELS = 20_000_000
STUDENT_PHOTO_TYPES = {
    "JPEG": (".jpg", "image/jpeg"),
    "PNG": (".png", "image/png"),
    "WEBP": (".webp", "image/webp"),
}


def _card_x(value: float) -> float:
    return CARD_WIDTH * value / CARD_TEMPLATE_WIDTH


def _card_y_from_top(value: float) -> float:
    return CARD_HEIGHT - (CARD_HEIGHT * value / CARD_TEMPLATE_HEIGHT)


def _card_height(value: float) -> float:
    return CARD_HEIGHT * value / CARD_TEMPLATE_HEIGHT


def _patient_photo_url(patient: PatientORM) -> str | None:
    if not patient.profile_photo_path:
        return None
    return f"/api/patients/{quote(patient.id, safe='')}/photo"


def _decode_student_photo(photo_base64: str) -> tuple[bytes, str, str]:
    try:
        _, encoded = photo_base64.split(",", 1) if "," in photo_base64 else ("", photo_base64)
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="File foto tidak valid") from exc
    if not content or len(content) > STUDENT_PHOTO_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Ukuran foto maksimal 3 MB")
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
        with Image.open(BytesIO(content)) as image:
            if image.width * image.height > STUDENT_PHOTO_MAX_PIXELS:
                raise HTTPException(status_code=400, detail="Resolusi foto terlalu besar")
            image_format = image.format or ""
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise HTTPException(status_code=400, detail="Format foto harus JPG, PNG, atau WebP") from exc
    if image_format not in STUDENT_PHOTO_TYPES:
        raise HTTPException(status_code=400, detail="Format foto harus JPG, PNG, atau WebP")
    extension, media_type = STUDENT_PHOTO_TYPES[image_format]
    return content, extension, media_type


def _draw_student_photo(pdf: canvas.Canvas, patient: PatientORM) -> None:
    if not patient.profile_photo_path:
        return
    photo_path = Path(patient.profile_photo_path)
    if not photo_path.is_file():
        return
    # Cover the full placeholder (x=80..413, y=298..736), including edge pixels.
    frame_x = _card_x(79)
    frame_y = _card_y_from_top(737)
    frame_width = _card_x(335)
    frame_height = _card_height(440)
    try:
        with Image.open(photo_path) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            # Use the physical frame ratio so the printed face is never stretched.
            target_width = 1276
            target_height = round(target_width * frame_height / frame_width)
            fitted = ImageOps.fit(image, (target_width, target_height), method=Image.Resampling.LANCZOS)
            buffer = BytesIO()
            fitted.save(buffer, format="JPEG", quality=90, optimize=True)
        buffer.seek(0)
        clip = pdf.beginPath()
        clip.roundRect(frame_x, frame_y, frame_width, frame_height, _card_x(19))
        pdf.saveState()
        pdf.clipPath(clip, stroke=0, fill=0)
        pdf.drawImage(ImageReader(buffer), frame_x, frame_y, width=frame_width, height=frame_height, mask="auto")
        pdf.restoreState()
    except (OSError, UnidentifiedImageError):
        logger.warning("Student photo could not be rendered for patient %s", patient.id)


def _card_text(value: object | None) -> str:
    text = str(value or "-").strip()
    # The built-in PDF font is limited to WinAnsi; retain readable Indonesian text.
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii") or "-"


def _draw_card_text(
    pdf: canvas.Canvas,
    value: object | None,
    x: float,
    y: float,
    max_width: float,
    font_size: float = 7,
    minimum_font_size: float = 4.6,
    font_name: str = "Helvetica-Bold",
) -> None:
    text = _card_text(value)
    size = font_size
    while size > minimum_font_size and stringWidth(text, font_name, size) > max_width:
        size -= 0.2
    if stringWidth(text, font_name, size) > max_width:
        while text and stringWidth(f"{text}...", font_name, size) > max_width:
            text = text[:-1]
        text = f"{text}..." if text else "-"
    pdf.setFont(font_name, size)
    pdf.setFillColor(colors.HexColor("#08066e"))
    pdf.drawString(x, y, text)


def _medical_card_qr_url(request: Request, db: Session, current_user: UserORM) -> str:
    school = db.get(SchoolORM, current_user.school_id) if current_user.school_id else None
    school_code = school.school_code if school else ""
    base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/") or str(request.base_url).rstrip("/")
    return f"{base_url}/keluhan?{urlencode({'school': school_code})}"


def _draw_medical_card_front(pdf: canvas.Canvas, patient: PatientORM) -> None:
    pdf.drawImage(str(CARD_FRONT_TEMPLATE), 0, 0, width=CARD_WIDTH, height=CARD_HEIGHT, mask="auto")
    _draw_student_photo(pdf, patient)
    value_x = _card_x(690)
    value_width = _card_x(430)
    _draw_card_text(pdf, patient.name, value_x, _card_y_from_top(463), value_width)
    _draw_card_text(pdf, patient.class_name, value_x, _card_y_from_top(518), value_width)
    _draw_card_text(pdf, patient.id, value_x, _card_y_from_top(573), value_width)
    _draw_card_text(pdf, patient.nik, value_x, _card_y_from_top(627), value_width, font_size=6.2)


def _draw_medical_card_back(pdf: canvas.Canvas, patient: PatientORM, qr_url: str) -> None:
    pdf.drawImage(str(CARD_BACK_TEMPLATE), 0, 0, width=CARD_WIDTH, height=CARD_HEIGHT, mask="auto")

    # Replace the sample RM printed in the Canva background with the student's actual RM.
    pdf.setFillColor(colors.HexColor("#f2edff"))
    pdf.roundRect(_card_x(65), _card_y_from_top(500), _card_x(770), _card_x(160), _card_x(20), fill=1, stroke=0)
    pdf.setFillColor(colors.HexColor("#2014a8"))
    pdf.setFont("Helvetica-Bold", 7)
    pdf.drawString(_card_x(145), _card_y_from_top(390), "Nomor Rekam Medis (No. RM)")
    _draw_card_text(pdf, patient.medical_record_number, _card_x(145), _card_y_from_top(470), _card_x(610), font_size=13, minimum_font_size=8)

    generator = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    generator.add_data(qr_url)
    generator.make(fit=True)
    qr_stream = BytesIO()
    generator.make_image(fill_color="black", back_color="white").save(qr_stream, format="PNG")
    qr_stream.seek(0)
    # The white square hides the example QR while retaining its purple frame.
    pdf.setFillColor(colors.white)
    pdf.rect(_card_x(127), _card_y_from_top(764), _card_x(258), _card_x(258), fill=1, stroke=0)
    pdf.drawImage(ImageReader(qr_stream), _card_x(133), _card_y_from_top(758), width=_card_x(246), height=_card_x(246), mask="auto")


@router.post("/patients/{patient_id}/photo")
def upload_patient_photo(
    patient_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_TIM_UKSR)),
) -> dict:
    patient = tenant_get(db, PatientORM, patient_id, current_user)
    if patient is None:
        raise HTTPException(status_code=404, detail="Siswa tidak ditemukan atau tidak dapat diakses")
    photo_base64 = payload.get("photo_base64")
    if not isinstance(photo_base64, str):
        raise HTTPException(status_code=400, detail="Foto wajib dipilih")
    content, extension, _ = _decode_student_photo(photo_base64)
    STUDENT_PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    destination = STUDENT_PHOTO_DIR / f"{patient.school_id or 'default'}_{uuid.uuid4().hex}{extension}"
    destination.write_bytes(content)
    old_photo = Path(patient.profile_photo_path) if patient.profile_photo_path else None
    patient.profile_photo_path = str(destination)
    write_audit_log(db, current_user, "upload_patient_photo", "patient", patient.id, "Uploaded student profile photo")
    db.commit()
    if old_photo and old_photo.is_file() and old_photo != destination:
        old_photo.unlink(missing_ok=True)
    return {"photo_url": _patient_photo_url(patient)}


@router.get("/patients/{patient_id}/photo")
def download_patient_photo(
    patient_id: str,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_TIM_UKSR, ROLE_WALI_ASUH)),
) -> FileResponse:
    patient = ensure_patient_access(db, tenant_get(db, PatientORM, patient_id, current_user), current_user)
    if patient is None or not patient.profile_photo_path:
        raise HTTPException(status_code=404, detail="Foto siswa belum tersedia")
    photo_path = Path(patient.profile_photo_path)
    if not photo_path.is_file():
        raise HTTPException(status_code=404, detail="Foto siswa belum tersedia")
    media_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(photo_path.suffix.lower(), "application/octet-stream")
    return FileResponse(photo_path, media_type=media_type)


@router.get("/patients/{patient_id}/medical-card")
def download_patient_medical_card(
    patient_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_TIM_UKSR)),
) -> StreamingResponse:
    patient = tenant_get(db, PatientORM, patient_id, current_user)
    if patient is None:
        raise HTTPException(status_code=404, detail="Siswa tidak ditemukan atau tidak dapat diakses")
    if not CARD_FRONT_TEMPLATE.exists() or not CARD_BACK_TEMPLATE.exists():
        raise HTTPException(status_code=503, detail="Template kartu belum tersedia")

    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=(CARD_WIDTH, CARD_HEIGHT), pageCompression=1)
    pdf.setTitle(f"Kartu Pelajar {patient.name}")
    _draw_medical_card_front(pdf, patient)
    pdf.showPage()
    _draw_medical_card_back(pdf, patient, _medical_card_qr_url(request, db, current_user))
    pdf.save()
    output.seek(0)

    write_audit_log(db, current_user, "generate_medical_card", "patient", patient.id, "Generated student medical card PDF")
    db.commit()
    filename_id = re.sub(r"[^A-Za-z0-9_-]+", "_", patient.id) or "siswa"
    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="kartu_pelajar_{filename_id}.pdf"',
            "Cache-Control": "no-store",
            "X-Card-Renderer-Version": CARD_RENDERER_VERSION,
        },
    )


@router.get("/patients/{patient_id}", response_model=PatientSummary)
def get_patient_detail(
    patient_id: str,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_TIM_UKSR, ROLE_WALI_ASUH)),
) -> PatientSummary:
    patient = ensure_patient_access(db, tenant_get(db, PatientORM, patient_id, current_user), current_user)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return PatientSummary(
        id=patient.id,
        nik=patient.nik,
        medical_record_number=patient.medical_record_number,
        photo_url=_patient_photo_url(patient),
        name=patient.name,
        age=patient.age,
        gender=patient.gender,
        class_name=patient.class_name,
        birth_date=patient.birth_date,
        parent_name=patient.parent_name,
        parent_phone=patient.parent_phone,
    )
@router.put("/patients/{patient_id}")
def update_patient(
    patient_id: str,
    payload: PatientCreate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(
        require_roles(
            ROLE_ADMIN,
            ROLE_PERAWAT,
            ROLE_KEPALA_UKSR,
            ROLE_TIM_UKSR
        )
    ),
):

    patient = tenant_get(db, PatientORM, patient_id, current_user)

    if patient is None:

        raise HTTPException(
            status_code=404,
            detail="Patient not found"
        )

    patient.name = payload.name
    if "nik" in payload.model_fields_set:
        patient.nik = payload.nik
    if "medical_record_number" in payload.model_fields_set:
        patient.medical_record_number = payload.medical_record_number
    patient.age = payload.age
    patient.gender = payload.gender
    patient.class_name = payload.class_name
    patient.birth_date = payload.birth_date
    patient.parent_name = payload.parent_name
    patient.parent_phone = payload.parent_phone

    write_audit_log(db, current_user, "edit_patient", "patient", patient.id, f"Edited patient {patient.name}")
    db.commit()
    db.refresh(patient)

    return {
        "message":
        "Patient updated"
    }


@router.delete("/patients/{patient_id}")
def delete_patient(
    patient_id: str,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
):
    patient = tenant_get(db, PatientORM, patient_id, current_user)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    patient_name = patient.name
    ckg_students = (
        tenant_query(db.query(CKGStudentORM), CKGStudentORM, current_user)
        .filter(CKGStudentORM.nis == patient_id)
        .all()
    )
    for ckg_student in ckg_students:
        db.delete(ckg_student)

    db.query(RecommendationLetterORM).filter(
        RecommendationLetterORM.student_id == patient_id,
        RecommendationLetterORM.school_id == patient.school_id,
    ).delete(synchronize_session=False)
    db.delete(patient)
    write_audit_log(
        db,
        current_user,
        "delete_patient",
        "patient",
        patient_id,
        f"Deleted patient {patient_name}; CKG records={len(ckg_students)}",
    )
    db.commit()
    return {
        "message": "Data siswa berhasil dihapus",
        "deleted_ckg_records": len(ckg_students),
    }


@router.get("/patients/{patient_id}/bpjs-referrals", response_model=list[BPJSReferralResponse])
def list_patient_bpjs_referrals(
    patient_id: str,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*BPJS_REFERRAL_READ_ROLES)),
) -> list[BPJSReferralResponse]:
    patient = ensure_patient_access(db, tenant_get(db, PatientORM, patient_id, current_user), current_user)
    if patient is None:
        raise HTTPException(status_code=404, detail="Data siswa tidak ditemukan")
    referrals = (
        tenant_query(db.query(BPJSReferralORM), BPJSReferralORM, current_user)
        .filter(BPJSReferralORM.patient_id == patient.id)
        .order_by(BPJSReferralORM.valid_until_date.asc(), BPJSReferralORM.id.desc())
        .all()
    )
    creators = {
        user.id: user
        for user in db.query(UserORM).filter(UserORM.id.in_({item.created_by_user_id for item in referrals})).all()
    } if referrals else {}
    return [_bpjs_referral_response(item, patient, creators.get(item.created_by_user_id)) for item in referrals]


@router.post("/bpjs-referrals", response_model=BPJSReferralResponse, status_code=status.HTTP_201_CREATED)
def create_bpjs_referral(
    payload: BPJSReferralCreate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*BPJS_REFERRAL_ROLES)),
) -> BPJSReferralResponse:
    patient = ensure_patient_access(db, tenant_get(db, PatientORM, payload.patient_id, current_user), current_user)
    if patient is None:
        raise HTTPException(status_code=404, detail="Data siswa tidak ditemukan atau bukan anak asuh Anda")

    content, document_name, content_type = _decode_bpjs_referral_document(payload.document_base64, payload.document_name)
    valid_until = payload.valid_until_date or _add_months(payload.referral_date, 3)
    if valid_until < payload.referral_date:
        raise HTTPException(status_code=400, detail="Tanggal berlaku sampai tidak boleh sebelum tanggal rujukan")
    if payload.control_date and payload.control_date < payload.referral_date:
        raise HTTPException(status_code=400, detail="Jadwal kontrol tidak boleh sebelum tanggal rujukan")

    BPJS_REFERRAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{BPJS_REFERRAL_ALLOWED_TYPES[content_type]}"
    stored_path = BPJS_REFERRAL_UPLOAD_DIR / stored_name
    try:
        stored_path.write_bytes(content)
        referral = BPJSReferralORM(
            school_id=patient.school_id,
            patient_id=patient.id,
            created_by_user_id=current_user.id,
            referral_date=payload.referral_date.isoformat(),
            valid_until_date=valid_until.isoformat(),
            control_date=payload.control_date.isoformat() if payload.control_date else None,
            referring_facility=payload.referring_facility.strip(),
            destination_facility=payload.destination_facility.strip(),
            referral_number=(payload.referral_number or "").strip() or None,
            complaint=(payload.complaint or "").strip() or None,
            notes=(payload.notes or "").strip() or None,
            document_path=str(stored_path),
            document_name=document_name,
            document_content_type=content_type,
            status="aktif",
        )
        db.add(referral)
        db.flush()
        write_audit_log(db, current_user, "create_bpjs_referral", "bpjs_referral", referral.id, f"Rujukan BPJS untuk {patient.id}")
        db.commit()
        db.refresh(referral)
    except Exception:
        if stored_path.exists():
            stored_path.unlink()
        db.rollback()
        raise
    return _bpjs_referral_response(referral, patient, current_user)


@router.get("/bpjs-referrals/{referral_id}/document")
def download_bpjs_referral_document(
    referral_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*BPJS_REFERRAL_READ_ROLES)),
) -> FileResponse:
    referral = tenant_get(db, BPJSReferralORM, referral_id, current_user)
    if referral is None:
        raise HTTPException(status_code=404, detail="Rujukan tidak ditemukan")
    patient = ensure_patient_access(db, tenant_get(db, PatientORM, referral.patient_id, current_user), current_user)
    if patient is None:
        raise HTTPException(status_code=404, detail="Rujukan tidak ditemukan")
    document_path = Path(referral.document_path)
    if not document_path.is_file():
        raise HTTPException(status_code=404, detail="Lampiran rujukan tidak ditemukan")
    return FileResponse(document_path, media_type=referral.document_content_type, filename=referral.document_name)


@router.patch("/bpjs-referrals/{referral_id}/control", response_model=BPJSReferralResponse)
def update_bpjs_referral_control(
    referral_id: int,
    payload: BPJSReferralControlUpdate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*BPJS_REFERRAL_ROLES)),
) -> BPJSReferralResponse:
    referral = tenant_get(db, BPJSReferralORM, referral_id, current_user)
    if referral is None:
        raise HTTPException(status_code=404, detail="Rujukan tidak ditemukan")
    patient = ensure_patient_access(db, tenant_get(db, PatientORM, referral.patient_id, current_user), current_user)
    if patient is None:
        raise HTTPException(status_code=404, detail="Rujukan tidak ditemukan")
    if not referral.control_date:
        raise HTTPException(status_code=400, detail="Rujukan ini belum memiliki jadwal kontrol")

    referral.control_done = payload.control_done
    action = "complete_bpjs_referral_control" if payload.control_done else "reopen_bpjs_referral_control"
    description = f"Kontrol rujukan BPJS {'diselesaikan' if payload.control_done else 'dibuka kembali'} untuk {patient.id}"
    write_audit_log(db, current_user, action, "bpjs_referral", referral.id, description)
    db.commit()
    db.refresh(referral)
    return _bpjs_referral_response(referral, patient, current_user)

@router.post("/uks/visits", response_model=UKSVisitResponse, status_code=status.HTTP_201_CREATED)
def create_uks_visit(
    payload: UKSVisitCreate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_TIM_UKSR)),
) -> UKSVisitResponse:
    patient = tenant_get(db, PatientORM, payload.patient_id, current_user)
    if patient is None:
        raise HTTPException(status_code=404, detail="Siswa tidak ditemukan atau tidak dapat diakses")

    visit = UKSVisitORM(
        school_id=patient.school_id,
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
    db.flush()
    write_audit_log(
        db,
        current_user,
        "create_uks_visit",
        "uks_visit",
        visit.id,
        f"Created UKS visit for patient {visit.patient_id}",
    )

    whatsapp_status = "skipped"
    whatsapp_message = "Nomor wali asuh belum diisi"
    if patient and patient.parent_phone:
        whatsapp_status, whatsapp_message = send_whatsapp_message(
            patient.parent_phone,
            build_uks_visit_whatsapp_message(patient, visit),
        )
    visit.whatsapp_status = whatsapp_status
    visit.whatsapp_message = whatsapp_message
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
        whatsapp_status=whatsapp_status,
        whatsapp_message=whatsapp_message,
    )
    
@router.get("/patients/{patient_id}/visits")
def get_patient_visits(
    patient_id: str,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_TIM_UKSR, ROLE_WALI_ASUH)),
):

    patient = ensure_patient_access(db, tenant_get(db, PatientORM, patient_id, current_user), current_user)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    visits = (
        tenant_query(db.query(UKSVisitORM), UKSVisitORM, current_user)
        .filter(UKSVisitORM.patient_id == patient_id)
        .order_by(UKSVisitORM.visit_date.desc())
        .all()
    )

    return visits

@router.get("/uks/visits")
def get_all_uks_visits(
    month: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_TIM_UKSR, ROLE_WALI_ASUH)),
):
    query = tenant_query(db.query(UKSVisitORM), UKSVisitORM, current_user)
    if is_wali_asuh(current_user):
        query = query.filter(UKSVisitORM.patient_id.in_(guardian_patient_ids(db, current_user)))
    if month:
        month = _validate_month_yyyy_mm(month)
        query = query.filter(UKSVisitORM.visit_date.like(f"{month}%"))

    visits = (
        query
        .order_by(UKSVisitORM.id.desc())
        .all()
    )

    results = []

    for visit in visits:

        patient = ensure_patient_access(db, tenant_get(db, PatientORM, visit.patient_id, current_user), current_user)

        results.append({
            "id": visit.id,
            "patient_id": visit.patient_id,
            "patient_name": patient.name if patient else visit.patient_id,
            "visit_date": visit.visit_date,
            "complaint": visit.complaint,
            "diagnosis": visit.diagnosis,
            "treatment": visit.treatment,
            "referral_place": visit.referral_place,
            "control_date": visit.control_date,
            "control_done": visit.control_done,
        })

    return results
@router.delete("/uks/visits/{visit_id}")
def delete_uks_visit(
    visit_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
):

    visit = tenant_get(db, UKSVisitORM, visit_id, current_user)

    if visit is None:
        raise HTTPException(
            status_code=404,
            detail="Visit not found"
        )

    db.delete(visit)
    write_audit_log(db, current_user, "delete_uks_visit", "uks_visit", visit_id, "Deleted UKS visit")
    db.commit()

    return {"message": "Visit deleted"}

@router.get("/uks/visits/{visit_id}", response_model=UKSVisitResponse)
def get_uks_visit_detail(
    visit_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_TIM_UKSR, ROLE_WALI_ASUH)),
) -> UKSVisitResponse:
    visit = tenant_get(db, UKSVisitORM, visit_id, current_user)
    if visit is None:
        raise HTTPException(status_code=404, detail="UKS visit not found")
    patient = ensure_patient_access(db, tenant_get(db, PatientORM, visit.patient_id, current_user), current_user)
    if patient is None:
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
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_TIM_UKSR, ROLE_WALI_ASUH)),
) -> list[UKSVisitResponse]:
    patient = ensure_patient_access(db, tenant_get(db, PatientORM, patient_id, current_user), current_user)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    visits = (
        tenant_query(db.query(UKSVisitORM), UKSVisitORM, current_user)
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


@router.post(
    "/uks/visits/{visit_id}/medications",
    response_model=UKSMedicationResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_uks_medication(
    visit_id: int,
    payload: UKSMedicationCreate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> UKSMedicationResponse:

    visit = tenant_get(db, UKSVisitORM, visit_id, current_user)
    if visit is None:
        raise HTTPException(status_code=404, detail="UKS visit not found")

    inventory = _find_inventory_by_name(db, payload.medicine_name, current_user)
    if inventory is None:
        raise HTTPException(status_code=404, detail="Medicine not found in inventory")

    if inventory.stock < payload.quantity:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient stock for {inventory.name}. Remaining: {inventory.stock}",
        )

    medication = UKSMedicationORM(
        school_id=visit.school_id,
        visit_id=visit_id,
        medicine_name=inventory.name,
        dosage=payload.dosage,
        quantity=payload.quantity,
        notes=payload.notes,
    )

    inventory.stock -= payload.quantity

    transaction = MedicineTransactionORM(
        school_id=visit.school_id,
        medicine_name=inventory.name,
        transaction_type="OUT",
        quantity=payload.quantity,
        notes=f"Kunjungan UKS #{visit_id}",
    )

    db.add(medication)
    db.add(inventory)
    db.add(transaction)

    db.commit()
    db.refresh(medication)
    db.refresh(inventory)

    return UKSMedicationResponse(
        id=medication.id,
        visit_id=medication.visit_id,
        medicine_name=medication.medicine_name,
        dosage=medication.dosage,
        quantity=medication.quantity,
        notes=medication.notes,
        remaining_stock=inventory.stock,
    )
@router.get("/uks/visits/{visit_id}/medications", response_model=list[UKSMedicationResponse])
def list_uks_medications(
    visit_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> list[UKSMedicationResponse]:
    visit = tenant_get(db, UKSVisitORM, visit_id, current_user)
    if visit is None:
        raise HTTPException(status_code=404, detail="UKS visit not found")

    medications = (
        tenant_query(db.query(UKSMedicationORM), UKSMedicationORM, current_user)
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
            remaining_stock=None,
        )
        for m in medications
    ]


@router.post(
    "/medicines",
    response_model=MedicineInventoryResponse,
    status_code=status.HTTP_201_CREATED
)
def create_medicine_inventory(
    payload: MedicineInventoryCreate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> MedicineInventoryResponse:

    existing = _find_inventory_by_name(
        db,
        payload.name,
        current_user,
    )

    # tambah stok jika obat sudah ada
    if existing is not None:

        existing.stock += payload.stock
        existing.unit = payload.unit.strip()
        existing.minimum_stock = payload.minimum_stock

        transaction = MedicineTransactionORM(
            school_id=existing.school_id,
            medicine_name=existing.name,
            transaction_type="IN",
            quantity=payload.stock,
            notes="Penambahan stok"
        )

        db.add(transaction)

        db.commit()
        db.refresh(existing)

        return MedicineInventoryResponse(
            id=existing.id,
            name=existing.name,
            unit=existing.unit,
            stock=existing.stock,
            minimum_stock=existing.minimum_stock,
            is_low_stock=(
                existing.stock <= existing.minimum_stock
            ),
        )

    # buat obat baru
    med = MedicineInventoryORM(
        school_id=current_user.school_id,
        name=payload.name.strip(),
        unit=payload.unit.strip(),
        stock=payload.stock,
        minimum_stock=payload.minimum_stock,
    )

    db.add(med)

    transaction = MedicineTransactionORM(
        school_id=current_user.school_id,
        medicine_name=payload.name.strip(),
        transaction_type="IN",
        quantity=payload.stock,
        notes="Stok awal"
    )

    db.add(transaction)

    db.commit()
    db.refresh(med)

    return MedicineInventoryResponse(
        id=med.id,
        name=med.name,
        unit=med.unit,
        stock=med.stock,
        minimum_stock=med.minimum_stock,
        is_low_stock=(
            med.stock <= med.minimum_stock
        ),
    )

@router.get("/medicines", response_model=list[MedicineInventoryResponse])
def list_medicines_inventory(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> list[MedicineInventoryResponse]:
    meds = tenant_query(db.query(MedicineInventoryORM), MedicineInventoryORM, current_user).order_by(MedicineInventoryORM.name.asc()).all()
    return [
        MedicineInventoryResponse(
            id=m.id,
            name=m.name,
            unit=m.unit,
            stock=m.stock,
            minimum_stock=m.minimum_stock,
            is_low_stock=m.stock <= m.minimum_stock,
        )
        for m in meds
    ]


@router.get("/medicines/import-template")
def download_medicines_import_template(
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> StreamingResponse:
    workbook = _build_medicine_import_template_workbook()
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="template_import_obat_uks.xlsx"'},
    )


@router.post("/medicines/import-excel")
def import_medicines_excel(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
):
    content = payload.get("content_base64")
    if not content:
        raise HTTPException(status_code=400, detail="content_base64 wajib diisi")

    try:
        raw = base64.b64decode(content.split(",", 1)[-1])
        workbook = load_workbook(BytesIO(raw), data_only=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="File Excel tidak valid") from exc

    sheet = workbook.active
    headers = [str(cell.value or "").strip().lower() for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
    aliases = {
        "name": ["nama obat", "obat", "name", "medicine", "medicine name"],
        "unit": ["satuan", "unit"],
        "stock": ["stok awal", "stok", "stock", "jumlah"],
        "minimum_stock": ["stok minimum", "minimum", "minimum stock", "min stock"],
        "notes": ["catatan", "notes", "keterangan"],
    }

    def idx(key: str) -> int | None:
        for alias in aliases[key]:
            if alias in headers:
                return headers.index(alias)
        return None

    def parse_int(value, default: int) -> int:
        if value is None or str(value).strip() == "":
            return default
        try:
            parsed = int(float(str(value).strip()))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Nilai stok tidak valid: {value}") from exc
        if parsed < 0:
            raise HTTPException(status_code=400, detail="Stok tidak boleh kurang dari 0")
        return parsed

    name_idx = idx("name")
    if name_idx is None:
        raise HTTPException(status_code=400, detail="Kolom Nama Obat wajib ada")

    unit_idx = idx("unit")
    stock_idx = idx("stock")
    minimum_idx = idx("minimum_stock")
    notes_idx = idx("notes")
    rows = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if not row or not row[name_idx]:
            continue
        name = str(row[name_idx]).strip()
        if not name:
            continue
        rows.append(
            {
                "name": name,
                "unit": str(row[unit_idx] or "tablet").strip() if unit_idx is not None else "tablet",
                "stock": parse_int(row[stock_idx], 0) if stock_idx is not None else 0,
                "minimum_stock": parse_int(row[minimum_idx], 10) if minimum_idx is not None else 10,
                "notes": str(row[notes_idx] or "").strip() if notes_idx is not None else "",
            }
        )

    if payload.get("preview", False):
        return {"preview": rows[:20], "total": len(rows)}

    created = 0
    updated = 0
    for item in rows:
        medicine = _find_inventory_by_name(db, item["name"], current_user)
        note_suffix = f" - {item['notes']}" if item["notes"] else ""
        if medicine is None:
            medicine = MedicineInventoryORM(
                school_id=current_user.school_id,
                name=item["name"],
                unit=item["unit"] or "tablet",
                stock=item["stock"],
                minimum_stock=item["minimum_stock"],
            )
            db.add(medicine)
            db.add(
                MedicineTransactionORM(
                    school_id=current_user.school_id,
                    medicine_name=item["name"],
                    transaction_type="IN",
                    quantity=item["stock"],
                    notes=f"Import Excel obat: stok awal {item['stock']}{note_suffix}",
                )
            )
            created += 1
            continue

        before_stock = medicine.stock
        medicine.unit = item["unit"] or medicine.unit
        medicine.minimum_stock = item["minimum_stock"]
        medicine.stock = item["stock"]
        db.add(medicine)
        if item["stock"] >= before_stock:
            transaction_type = "IN"
            quantity = item["stock"] - before_stock
        else:
            transaction_type = "OUT"
            quantity = before_stock - item["stock"]
        db.add(
            MedicineTransactionORM(
                school_id=medicine.school_id,
                medicine_name=medicine.name,
                transaction_type=transaction_type,
                quantity=quantity,
                notes=f"Import Excel obat: koreksi stok {before_stock} -> {item['stock']}{note_suffix}",
            )
        )
        updated += 1

    write_audit_log(
        db,
        current_user,
        "import_medicines_excel",
        "medicine",
        None,
        f"created={created}; updated={updated}",
    )
    db.commit()
    return {"message": "Import obat selesai", "created": created, "updated": updated, "total": len(rows)}


@router.patch("/medicines/{medicine_id}", response_model=MedicineInventoryResponse)
def update_medicine_inventory(
    medicine_id: int,
    payload: MedicineInventoryUpdate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> MedicineInventoryResponse:
    med = tenant_get(db, MedicineInventoryORM, medicine_id, current_user)
    if med is None:
        raise HTTPException(status_code=404, detail="Medicine not found")

    if payload.unit is not None:
        med.unit = payload.unit.strip()
    if payload.stock is not None:
        med.stock = payload.stock
    if payload.minimum_stock is not None:
        med.minimum_stock = payload.minimum_stock

    db.add(med)
    db.commit()
    db.refresh(med)
    return MedicineInventoryResponse(
        id=med.id,
        name=med.name,
        unit=med.unit,
        stock=med.stock,
        minimum_stock=med.minimum_stock,
        is_low_stock=med.stock <= med.minimum_stock,
    )


@router.post("/medicines/{medicine_id}/adjust", response_model=MedicineInventoryResponse)
def adjust_medicine_stock(
    medicine_id: int,
    payload: MedicineStockAdjustment,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> MedicineInventoryResponse:
    med = tenant_get(db, MedicineInventoryORM, medicine_id, current_user)
    if med is None:
        raise HTTPException(status_code=404, detail="Medicine not found")

    before_stock = med.stock
    transaction_type = payload.adjustment_type
    transaction_quantity = payload.quantity

    if payload.adjustment_type == "IN":
        if payload.quantity < 1:
            raise HTTPException(status_code=400, detail="Quantity must be greater than 0")
        med.stock += payload.quantity
    elif payload.adjustment_type == "OUT":
        if payload.quantity < 1:
            raise HTTPException(status_code=400, detail="Quantity must be greater than 0")
        if med.stock < payload.quantity:
            raise HTTPException(status_code=400, detail=f"Insufficient stock for {med.name}. Remaining: {med.stock}")
        med.stock -= payload.quantity
    else:
        if payload.quantity == before_stock:
            transaction_type = "IN"
            transaction_quantity = 0
        elif payload.quantity > before_stock:
            transaction_type = "IN"
            transaction_quantity = payload.quantity - before_stock
        else:
            transaction_type = "OUT"
            transaction_quantity = before_stock - payload.quantity
        med.stock = payload.quantity

    transaction = MedicineTransactionORM(
        school_id=med.school_id,
        medicine_name=med.name,
        transaction_type=transaction_type,
        quantity=transaction_quantity,
        notes=payload.notes or f"Koreksi stok dari {before_stock} ke {med.stock}",
    )
    db.add(med)
    db.add(transaction)
    write_audit_log(
        db,
        current_user,
        "adjust_medicine_stock",
        "medicine",
        med.id,
        f"{med.name}: {before_stock} -> {med.stock}",
    )
    db.commit()
    db.refresh(med)

    return MedicineInventoryResponse(
        id=med.id,
        name=med.name,
        unit=med.unit,
        stock=med.stock,
        minimum_stock=med.minimum_stock,
        is_low_stock=med.stock <= med.minimum_stock,
    )


@router.get("/reports/medicine-mutation")
def get_medicine_mutation_report(
    month: int,
    year: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR)),
) -> list[dict]:
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Month must be 1-12")
    start_dt = datetime(year, month, 1)
    end_dt = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)

    transactions = (
        tenant_query(db.query(MedicineTransactionORM), MedicineTransactionORM, current_user)
        .filter(MedicineTransactionORM.transaction_date >= start_dt)
        .filter(MedicineTransactionORM.transaction_date < end_dt)
        .order_by(MedicineTransactionORM.medicine_name.asc())
        .all()
    )
    summary: dict[str, dict] = {}
    for trx in transactions:
        item = summary.setdefault(
            trx.medicine_name,
            {"medicine_name": trx.medicine_name, "in_qty": 0, "out_qty": 0, "current_stock": 0},
        )
        if trx.transaction_type == "IN":
            item["in_qty"] += trx.quantity
        else:
            item["out_qty"] += trx.quantity

    stocks = {
        med.name: med.stock
        for med in tenant_query(db.query(MedicineInventoryORM), MedicineInventoryORM, current_user).order_by(MedicineInventoryORM.name.asc()).all()
    }
    for name, stock in stocks.items():
        item = summary.setdefault(
            name,
            {"medicine_name": name, "in_qty": 0, "out_qty": 0, "current_stock": stock},
        )
        item["current_stock"] = stock

    return list(summary.values())


@router.get("/reports/medicines/pdf")
def get_medicines_report_pdf(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR)),
) -> StreamingResponse:
    medicines = tenant_query(db.query(MedicineInventoryORM), MedicineInventoryORM, current_user).order_by(MedicineInventoryORM.name.asc()).all()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=24,
        rightMargin=24,
        topMargin=24,
        bottomMargin=24,
    )

    styles = getSampleStyleSheet()

    elements = []
    _append_pdf_letterhead(
        elements,
        doc,
        "LAPORAN STOK OBAT UKS",
        f"Total item: {len(medicines)}",
        styles,
        pdf_school_for_user(db, current_user),
    )

    data = [["No", "Nama Obat", "Stok", "Satuan", "Stok Minimum", "Status"]]
    for idx, med in enumerate(medicines, start=1):
        status_text = "Perlu Restok" if med.stock <= med.minimum_stock else "Aman"
        data.append(
            [
                str(idx),
                med.name,
                str(med.stock),
                med.unit,
                str(med.minimum_stock),
                status_text,
            ]
        )

    table = Table(data, repeatRows=1, colWidths=[28, 220, 50, 70, 80, 90])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("ALIGN", (1, 1), (1, -1), "LEFT"),
                ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#94a3b8")),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    elements.append(table)
    _append_pdf_signature(elements, doc, current_user, styles, school=pdf_school_for_user(db, current_user))
    doc.build(elements)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="laporan_stok_obat_uks.pdf"'},
    )
@router.get("/reports/medicine-mutation/pdf")
def get_medicine_mutation_pdf(
    month: int,
    year: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR)),
) -> StreamingResponse:


    start_dt = datetime(year, month, 1)

    end_dt = (
        datetime(year + 1, 1, 1)
        if month == 12
        else datetime(year, month + 1, 1)
)

    transactions = (
        tenant_query(db.query(MedicineTransactionORM), MedicineTransactionORM, current_user)
        .filter(MedicineTransactionORM.transaction_date >= start_dt)
        .filter(MedicineTransactionORM.transaction_date < end_dt)
        .order_by(MedicineTransactionORM.transaction_date.asc())
        .all()
)

    mutation_rows = []

    for trx in transactions:

        stock_item = (
            db.query(MedicineInventoryORM)
            .filter(
                MedicineInventoryORM.name == trx.medicine_name,
                MedicineInventoryORM.school_id == trx.school_id,
            )
            .first()
        )

        mutation_rows.append(
            {
                "date": trx.transaction_date.strftime("%d-%m-%Y"),
                "medicine": trx.medicine_name,
                "type": "Masuk" if trx.transaction_type == "IN" else "Keluar",
                "qty": trx.quantity,
                "stock": stock_item.stock if stock_item else 0,
            }
        )

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=24,
        rightMargin=24,
        topMargin=24,
        bottomMargin=24,
    )

    styles = getSampleStyleSheet()

    elements = []
    _append_pdf_letterhead(
        elements,
        doc,
        "LAPORAN MUTASI OBAT UKS",
        f"Periode: {month:02d}/{year}",
        styles,
        pdf_school_for_user(db, current_user),
    )

    data = [
        [
            "No",
            "Tanggal",
            "Nama Obat",
            "Jenis",
            "Jumlah",
            "Stok Saat Ini",
        ]
    ]

    for idx, row in enumerate(mutation_rows, start=1):
        data.append(
            [
                str(idx),
                row["date"],
                row["medicine"],
                row["type"],
                str(row["qty"]),
                str(row["stock"]),
            ]
        )

    table = Table(
        data,
        repeatRows=1,
        colWidths=[30, 70, 210, 70, 60, 80]
    )

    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
            ]
        )
    )

    elements.append(table)
    _append_pdf_signature(elements, doc, current_user, styles, school=pdf_school_for_user(db, current_user))

    doc.build(elements)

    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition":
            f'attachment; filename="laporan_mutasi_obat_{year}_{month:02d}.pdf"'
        },
    )
@router.patch("/uks/visits/{visit_id}/referral", response_model=UKSVisitResponse)
def update_uks_referral(
    visit_id: int,
    payload: UKSReferralUpdate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR)),
) -> UKSVisitResponse:
    visit = tenant_get(db, UKSVisitORM, visit_id, current_user)
    if visit is None:
        raise HTTPException(status_code=404, detail="UKS visit not found")

    visit.referral_to = payload.referral_to
    visit.referral_status = payload.referral_status
    db.add(visit)
    db.commit()
    db.refresh(visit)
    patient = tenant_get(db, PatientORM, visit.patient_id, current_user)

    if patient and patient.parent_phone:
        send_whatsapp_message(
            patient.parent_phone,
            build_referral_whatsapp_message(patient, visit),
        )

    return UKSVisitResponse(
        id=visit.id,
        patient_id=visit.patient_id,
        visit_date=str(visit.visit_date),
        complaint=visit.complaint,
        examination=visit.examination,
        treatment=visit.treatment,
        diagnosis=visit.diagnosis,
        notes=visit.notes,
        referral_to=visit.referral_to,
        referral_status=visit.referral_status,
    )

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
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR)),
) -> UKSDailyReportResponse:
    date = _validate_date_yyyy_mm_dd(date)
    visits = tenant_query(db.query(UKSVisitORM), UKSVisitORM, current_user).filter(UKSVisitORM.visit_date == date).all()
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
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR)),
) -> StreamingResponse:
    date = _validate_date_yyyy_mm_dd(date)
    visits = (
        tenant_query(db.query(UKSVisitORM), UKSVisitORM, current_user)
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
        patient = tenant_get(db, PatientORM, visit.patient_id, current_user)
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
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR)),
) -> UKSMonthlyReportResponse:
    month = _validate_month_yyyy_mm(month)
    month_prefix = f"{month}%"
    visits = tenant_query(db.query(UKSVisitORM), UKSVisitORM, current_user).filter(UKSVisitORM.visit_date.like(month_prefix)).all()
    total_referrals = sum(1 for visit in visits if visit.referral_status == "dirujuk")
    return UKSMonthlyReportResponse(
        month=month,
        total_visits=len(visits),
        total_referrals=total_referrals,
        top_complaints=_build_top_complaints(visits),
    )


def _visit_report_bounds(
    period: str,
    report_date: str | None,
    start_date: str | None,
    end_date: str | None,
    month: str | None,
) -> tuple[str, str, str]:
    if period == "daily":
        if not report_date:
            raise HTTPException(status_code=400, detail="date is required for daily report")
        safe_date = _validate_date_yyyy_mm_dd(report_date)
        return safe_date, safe_date, f"Harian {safe_date}"
    if period == "weekly":
        if not start_date or not end_date:
            raise HTTPException(status_code=400, detail="start_date and end_date are required for weekly report")
        safe_start = _validate_date_yyyy_mm_dd(start_date)
        safe_end = _validate_date_yyyy_mm_dd(end_date)
        if safe_start > safe_end:
            raise HTTPException(status_code=400, detail="start_date cannot be after end_date")
        return safe_start, safe_end, f"Mingguan {safe_start} s/d {safe_end}"
    if period == "monthly":
        if not month:
            raise HTTPException(status_code=400, detail="month is required for monthly report")
        safe_month = _validate_month_yyyy_mm(month)
        start_dt = datetime.strptime(f"{safe_month}-01", "%Y-%m-%d")
        if start_dt.month == 12:
            end_dt = datetime(start_dt.year + 1, 1, 1) - timedelta(days=1)
        else:
            end_dt = datetime(start_dt.year, start_dt.month + 1, 1) - timedelta(days=1)
        return start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"), f"Bulanan {safe_month}"
    raise HTTPException(status_code=400, detail="period must be daily, weekly, or monthly")


def _visit_report_rows(db: Session, start: str, end: str, current_user: UserORM) -> list[dict]:
    visits = (
        tenant_query(db.query(UKSVisitORM), UKSVisitORM, current_user)
        .filter(UKSVisitORM.visit_date >= start)
        .filter(UKSVisitORM.visit_date <= end)
        .order_by(UKSVisitORM.visit_date.asc(), UKSVisitORM.id.asc())
        .all()
    )
    patient_ids = [visit.patient_id for visit in visits if visit.patient_id]
    patients = {
        patient.id: patient
        for patient in tenant_query(db.query(PatientORM), PatientORM, current_user).filter(PatientORM.id.in_(patient_ids)).all()
    } if patient_ids else {}
    rows = []
    for visit in visits:
        patient = patients.get(visit.patient_id)
        rows.append(
            {
                "tanggal": visit.visit_date,
                "nama_siswa": patient.name if patient else visit.patient_id,
                "kelas": patient.class_name if patient and patient.class_name else "-",
                "keluhan": visit.complaint or "-",
                "diagnosa": visit.diagnosis or "-",
                "tindakan": visit.treatment or "-",
                "petugas": "-",
            }
        )
    return rows


def _visit_report_payload(
    db: Session,
    current_user: UserORM,
    period: str,
    report_date: str | None,
    start_date: str | None,
    end_date: str | None,
    month: str | None,
) -> dict:
    start, end, label = _visit_report_bounds(period, report_date, start_date, end_date, month)
    rows = _visit_report_rows(db, start, end, current_user)
    return {
        "period": period,
        "label": label,
        "start_date": start,
        "end_date": end,
        "total": len(rows),
        "rows": rows,
    }


@router.get("/reports/uks/visits")
def get_uks_visit_report(
    period: str = Query(..., pattern="^(daily|weekly|monthly)$"),
    date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    month: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR)),
) -> dict:
    return _visit_report_payload(db, current_user, period, date, start_date, end_date, month)


@router.get("/reports/uks/visits/pdf")
def get_uks_visit_report_pdf(
    period: str = Query(..., pattern="^(daily|weekly|monthly)$"),
    date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    month: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR)),
) -> StreamingResponse:
    payload = _visit_report_payload(db, current_user, period, date, start_date, end_date, month)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=28, rightMargin=28, topMargin=24, bottomMargin=24)
    styles = getSampleStyleSheet()
    body = styles["BodyText"]
    body.fontSize = 7
    body.leading = 8.5
    title = styles["Title"]
    title.fontSize = 14
    elements = []
    _append_pdf_letterhead(
        elements,
        doc,
        "LAPORAN KUNJUNGAN UKS",
        escape(payload["label"]),
        styles,
        pdf_school_for_user(db, current_user),
    )
    headers = ["Tanggal", "Nama Siswa", "Kelas", "Keluhan", "Diagnosa", "Tindakan", "Petugas"]
    table_rows = [[Paragraph(escape(header), body) for header in headers]]
    for row in payload["rows"]:
        table_rows.append([Paragraph(escape(str(row[key])), body) for key in ["tanggal", "nama_siswa", "kelas", "keluhan", "diagnosa", "tindakan", "petugas"]])
    if len(table_rows) == 1:
        table_rows.append([Paragraph("Tidak ada data", body), "", "", "", "", "", ""])
    table = Table(table_rows, repeatRows=1, colWidths=[58, 130, 45, 115, 130, 235, 60])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#9ca3af")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    elements.append(table)
    _append_pdf_signature(elements, doc, current_user, styles, school=pdf_school_for_user(db, current_user))
    doc.build(elements)
    buffer.seek(0)
    filename = f"laporan_kunjungan_uks_{period}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/uks/visits/excel")
def get_uks_visit_report_excel(
    period: str = Query(..., pattern="^(daily|weekly|monthly)$"),
    date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    month: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR)),
) -> StreamingResponse:
    payload = _visit_report_payload(db, current_user, period, date, start_date, end_date, month)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Laporan Kunjungan"
    headers = ["Tanggal", "Nama Siswa", "Kelas", "Keluhan", "Diagnosa", "Tindakan", "Petugas"]
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

    for row in payload["rows"]:
        sheet.append([row[key] for key in ["tanggal", "nama_siswa", "kelas", "keluhan", "diagnosa", "tindakan", "petugas"]])

    widths = {"A": 14, "B": 28, "C": 12, "D": 28, "E": 30, "F": 48, "G": 20}
    for col, width in widths.items():
        sheet.column_dimensions[col].width = width
    for row in sheet.iter_rows(min_row=2, max_row=sheet.max_row, min_col=1, max_col=7):
        for cell in row:
            cell.border = border
            cell.alignment = center if cell.column in (1, 3, 7) else wrap

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    filename = f"laporan_kunjungan_uks_{period}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/patients/{patient_id}/assessments", response_model=PatientAssessmentsResponse)
def get_patient_assessments(
    patient_id: str,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_TIM_UKSR)),
) -> PatientAssessmentsResponse:
    patient = tenant_get(db, PatientORM, patient_id, current_user)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    assessments = (
        tenant_query(db.query(AssessmentORM), AssessmentORM, current_user)
        .filter(AssessmentORM.patient_id == patient_id)
        .order_by(AssessmentORM.id.desc())
        .all()
    )

    payload = []
    for a in assessments:
        recs = (
            tenant_query(db.query(RecommendationORM), RecommendationORM, current_user)
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
            nik=patient.nik,
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
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_TIM_UKSR)),
) -> AssessmentSummary:
    assessment = tenant_get(db, AssessmentORM, assessment_id, current_user)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")

    recs = (
        tenant_query(db.query(RecommendationORM), RecommendationORM, current_user)
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
@router.put("/uks/visits/{visit_id}")
def update_uks_visit(
    visit_id: int,
    payload: UKSVisitCreate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_TIM_UKSR)),
):

    visit = tenant_get(db, UKSVisitORM, visit_id, current_user)

    if visit is None:
        raise HTTPException(
            status_code=404,
            detail="Visit not found"
        )

    if payload.patient_id is not None:
        patient = tenant_get(db, PatientORM, payload.patient_id, current_user)
        if patient is None:
            raise HTTPException(status_code=404, detail="Patient not found")
        visit.patient_id = payload.patient_id

    if payload.visit_date is not None:
        visit.visit_date = payload.visit_date

    if payload.complaint is not None:
        visit.complaint = payload.complaint

    if payload.examination is not None:
        visit.examination = payload.examination

    if payload.treatment is not None:
        visit.treatment = payload.treatment

    if payload.diagnosis is not None:
        visit.diagnosis = payload.diagnosis

    if payload.notes is not None:
        visit.notes = payload.notes

    if payload.referral_place is not None:
        visit.referral_place = payload.referral_place

    if payload.control_date is not None:
        visit.control_date = payload.control_date

    if payload.control_done is not None:
        visit.control_done = payload.control_done

    write_audit_log(db, current_user, "edit_uks_visit", "uks_visit", visit.id, f"Edited UKS visit for patient {visit.patient_id}")
    db.commit()
    db.refresh(visit)
    if payload.control_date is not None or payload.referral_place is not None:
        patient = tenant_get(db, PatientORM, visit.patient_id, current_user)
        if patient and patient.parent_phone:
            send_whatsapp_message(patient.parent_phone, build_control_whatsapp_message(patient, visit))

    return {
        "message": "Visit updated"
    }
from sqlalchemy import func
from datetime import date


@router.get("/dashboard/stats")
def dashboard_stats(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_TIM_UKSR, ROLE_WALI_ASUH)),
):

    total_students = guardian_patient_query(
        tenant_query(db.query(PatientORM), PatientORM, current_user), current_user, db
    ).count()

    visit_query = tenant_query(db.query(UKSVisitORM), UKSVisitORM, current_user)
    if is_wali_asuh(current_user):
        visit_query = visit_query.filter(UKSVisitORM.patient_id.in_(guardian_patient_ids(db, current_user)))
    today_visits = visit_query.filter(
        UKSVisitORM.visit_date == date.today().isoformat()
    ).count()

    top_case_query = tenant_query(
        db.query(UKSVisitORM.diagnosis, func.count(UKSVisitORM.diagnosis).label("total")),
        UKSVisitORM,
        current_user,
    )
    if is_wali_asuh(current_user):
        top_case_query = top_case_query.filter(
            UKSVisitORM.patient_id.in_(guardian_patient_ids(db, current_user))
        )
    top_case = (
        top_case_query
        .group_by(UKSVisitORM.diagnosis)
        .order_by(func.count(UKSVisitORM.diagnosis).desc())
        .first()
    )

    return {
        "total_students": total_students,
        "today_visits": today_visits,
        "top_case": top_case[0] if top_case else "-",
        "active_reports": today_visits
    }


@router.get("/dashboard/bpjs-referrals")
def dashboard_bpjs_referrals(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(*BPJS_REFERRAL_READ_ROLES)),
) -> dict:
    today = date.today()
    query = tenant_query(db.query(BPJSReferralORM), BPJSReferralORM, current_user)
    if is_wali_asuh(current_user):
        query = query.filter(BPJSReferralORM.patient_id.in_(guardian_patient_ids(db, current_user)))
    referrals = query.order_by(BPJSReferralORM.valid_until_date.asc()).all()
    patients = {
        patient.id: patient
        for patient in tenant_query(db.query(PatientORM), PatientORM, current_user)
        .filter(PatientORM.id.in_({item.patient_id for item in referrals}))
        .all()
    } if referrals else {}

    active = 0
    expiring = 0
    expired = 0
    priority = []
    control_due = 0
    control_overdue = 0
    control_priority = []
    for referral in referrals:
        try:
            expiry = date.fromisoformat(str(referral.valid_until_date))
        except ValueError:
            continue
        days_remaining = (expiry - today).days
        if days_remaining < 0:
            expired += 1
            label = "Kedaluwarsa"
        else:
            active += 1
            if days_remaining <= 30:
                expiring += 1
                label = f"H-{days_remaining}" if days_remaining else "Habis hari ini"
            else:
                label = f"{days_remaining} hari"
        if days_remaining <= 30:
            patient = patients.get(referral.patient_id)
            priority.append({
                "id": referral.id,
                "patient_id": referral.patient_id,
                "patient_name": patient.name if patient else referral.patient_id,
                "class_name": patient.class_name if patient else None,
                "destination_facility": referral.destination_facility,
                "valid_until_date": referral.valid_until_date,
                "days_remaining": days_remaining,
                "label": label,
            })
        if referral.control_date and not referral.control_done:
            try:
                control_day = date.fromisoformat(str(referral.control_date))
            except ValueError:
                continue
            control_remaining = (control_day - today).days
            patient = patients.get(referral.patient_id)
            if control_remaining < 0:
                control_overdue += 1
                control_label = "Terlambat kontrol"
            elif control_remaining <= 7:
                control_due += 1
                control_label = "Kontrol hari ini" if control_remaining == 0 else f"Kontrol H-{control_remaining}"
            else:
                continue
            control_priority.append({
                "id": referral.id,
                "patient_id": referral.patient_id,
                "patient_name": patient.name if patient else referral.patient_id,
                "class_name": patient.class_name if patient else None,
                "destination_facility": referral.destination_facility,
                "control_date": referral.control_date,
                "days_remaining": control_remaining,
                "label": control_label,
            })
    return {
        "active": active,
        "expiring": expiring,
        "expired": expired,
        "priority": sorted(priority, key=lambda item: item["days_remaining"])[:10],
        "control_due": control_due,
        "control_overdue": control_overdue,
        "control_priority": sorted(control_priority, key=lambda item: item["days_remaining"])[:10],
    }
@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT))
):

    users = (
        tenant_query(db.query(UserORM), UserORM, current_user)
        .order_by(UserORM.full_name.asc())
        .all()
    )

    return [
        {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role,
            "school_id": user.school_id,
            "is_active": user.is_active,
            "nip": getattr(user, "nip", None),
            "jabatan": getattr(user, "jabatan", None),
            "created_at": user.created_at,
            "updated_at": user.updated_at,
        }
        for user in users
    ]


def _temporary_password(length: int = 12) -> str:
    """Create a readable password containing all required character groups."""
    alphabet = string.ascii_letters + string.digits
    characters = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
    ]
    characters.extend(secrets.choice(alphabet) for _ in range(length - len(characters)))
    secrets.SystemRandom().shuffle(characters)
    return "".join(characters)


def _excel_text(value: object) -> str:
    text = str(value or "")
    return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text


@router.post("/users/export-temporary-credentials")
def export_temporary_user_credentials(
    payload: UserCredentialExportRequest,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_SUPER_ADMIN)),
) -> StreamingResponse:
    school = db.get(SchoolORM, payload.school_id)
    if school is None or not school.is_active:
        raise HTTPException(status_code=404, detail="Sekolah aktif tidak ditemukan")

    allowed_roles = {ROLE_ADMIN, ROLE_PERAWAT, ROLE_KEPALA_UKSR, ROLE_WALI_ASUH, ROLE_TIM_UKSR}
    selected_roles = set(payload.roles) if payload.roles else allowed_roles
    if not selected_roles or not selected_roles.issubset(allowed_roles):
        raise HTTPException(status_code=400, detail="Role yang dipilih tidak valid")

    users = (
        db.query(UserORM)
        .filter(
            UserORM.school_id == school.id,
            UserORM.role.in_(selected_roles),
            UserORM.is_active.is_(True),
        )
        .order_by(UserORM.role.asc(), UserORM.full_name.asc())
        .all()
    )
    if not users:
        raise HTTPException(status_code=404, detail="Tidak ada pengguna aktif untuk pilihan tersebut")

    credentials: list[tuple[UserORM, str]] = []
    for user in users:
        temporary_password = _temporary_password()
        user.password_hash = hash_password(temporary_password)
        db.add(user)
        credentials.append((user, temporary_password))

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Kredensial Sementara"
    headers = ["Nama Lengkap", "Username", "Password Sementara", "Role", "Status", "Sekolah"]
    sheet.append(headers)
    for user, temporary_password in credentials:
        sheet.append([
            _excel_text(user.full_name),
            _excel_text(user.username),
            temporary_password,
            user.role,
            "Aktif",
            _excel_text(school.school_name),
        ])

    header_fill = PatternFill("solid", fgColor="4F46E5")
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column, width in {"A": 30, "B": 24, "C": 24, "D": 20, "E": 12, "F": 34}.items():
        sheet.column_dimensions[column].width = width

    info = workbook.create_sheet("Petunjuk")
    info.append(["PENTING"])
    info.append(["Password dalam file ini adalah password sementara yang baru dibuat."])
    info.append(["Bagikan setiap baris hanya kepada pemilik akun yang bersangkutan."])
    info.append(["Simpan file di tempat aman dan hapus setelah kredensial dibagikan."])
    info.column_dimensions["A"].width = 78
    info["A1"].font = Font(color="B91C1C", bold=True, size=14)

    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    write_audit_log(
        db,
        current_user,
        "export_temporary_credentials",
        "school",
        school.id,
        f"Reset and exported temporary credentials for {len(users)} active user(s); roles: {', '.join(sorted(selected_roles))}",
    )
    db.commit()

    safe_code = re.sub(r"[^A-Za-z0-9_-]+", "_", school.school_code).strip("_") or str(school.id)
    filename = f"kredensial_sehati_{safe_code}_{date.today().isoformat()}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )


@router.get("/guardian-assignments")
def list_guardian_assignments(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN)),
) -> list[dict]:
    guardians = (
        tenant_query(db.query(UserORM), UserORM, current_user)
        .filter(UserORM.role == ROLE_WALI_ASUH)
        .order_by(UserORM.full_name.asc())
        .all()
    )
    return [
        {
            "id": guardian.id,
            "username": guardian.username,
            "full_name": guardian.full_name,
            "is_active": guardian.is_active,
            "assigned_count": db.query(GuardianStudentAssignmentORM)
            .filter(
                GuardianStudentAssignmentORM.guardian_id == guardian.id,
                GuardianStudentAssignmentORM.school_id == guardian.school_id,
            )
            .count(),
        }
        for guardian in guardians
    ]


def _guardian_for_assignment_or_404(db: Session, guardian_id: int, current_user: UserORM) -> UserORM:
    guardian = tenant_get(db, UserORM, guardian_id, current_user)
    if guardian is None or guardian.role != ROLE_WALI_ASUH:
        raise HTTPException(status_code=404, detail="Akun wali asuh tidak ditemukan")
    if not is_super_admin(current_user) and guardian.school_id != current_user.school_id:
        raise HTTPException(status_code=404, detail="Akun wali asuh tidak ditemukan")
    return guardian


@router.get("/guardian-assignments/{guardian_id}")
def get_guardian_assignments(
    guardian_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN)),
) -> dict:
    guardian = _guardian_for_assignment_or_404(db, guardian_id, current_user)
    students = (
        tenant_query(db.query(PatientORM), PatientORM, current_user)
        .filter(PatientORM.school_id == guardian.school_id)
        .order_by(PatientORM.name.asc())
        .all()
    )
    assigned_ids = {
        assignment.patient_id
        for assignment in db.query(GuardianStudentAssignmentORM)
        .filter(
            GuardianStudentAssignmentORM.guardian_id == guardian.id,
            GuardianStudentAssignmentORM.school_id == guardian.school_id,
        )
        .all()
    }
    return {
        "guardian": {"id": guardian.id, "full_name": guardian.full_name, "username": guardian.username},
        "students": [
            {
                "id": student.id,
                "name": student.name,
                "class_name": student.class_name,
                "assigned": student.id in assigned_ids,
            }
            for student in students
        ],
    }


@router.put("/guardian-assignments/{guardian_id}")
def replace_guardian_assignments(
    guardian_id: int,
    payload: GuardianAssignmentUpdate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN)),
) -> dict:
    guardian = _guardian_for_assignment_or_404(db, guardian_id, current_user)
    patient_ids = sorted({patient_id.strip() for patient_id in payload.patient_ids if patient_id.strip()})
    if len(patient_ids) > 500:
        raise HTTPException(status_code=400, detail="Terlalu banyak siswa dalam satu penugasan")

    valid_ids = {
        patient_id
        for (patient_id,) in db.query(PatientORM.id)
        .filter(PatientORM.school_id == guardian.school_id, PatientORM.id.in_(patient_ids))
        .all()
    }
    missing_ids = sorted(set(patient_ids) - valid_ids)
    if missing_ids:
        raise HTTPException(status_code=400, detail="Ada siswa yang tidak ditemukan pada sekolah wali asuh")

    db.query(GuardianStudentAssignmentORM).filter(
        GuardianStudentAssignmentORM.guardian_id == guardian.id,
        GuardianStudentAssignmentORM.school_id == guardian.school_id,
    ).delete(synchronize_session=False)
    db.add_all(
        [
            GuardianStudentAssignmentORM(
                school_id=guardian.school_id,
                guardian_id=guardian.id,
                patient_id=patient_id,
            )
            for patient_id in patient_ids
        ]
    )
    write_audit_log(
        db,
        current_user,
        "assign_guardian_students",
        "guardian_assignment",
        guardian.id,
        f"Assigned {len(patient_ids)} student(s) to wali asuh {guardian.username}",
    )
    db.commit()
    return {"message": "Penugasan anak asuh berhasil disimpan", "assigned_count": len(patient_ids)}


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user_from_admin(
    payload: UserCreate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> UserResponse:
    existing = db.query(UserORM).filter(UserORM.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    if is_super_admin(current_user):
        if payload.role != ROLE_SUPER_ADMIN and payload.school_id is None:
            raise HTTPException(status_code=400, detail="school_id is required for school users")
        school_id = payload.school_id
    else:
        if payload.role == ROLE_SUPER_ADMIN:
            raise HTTPException(status_code=403, detail="Only super_admin can create super_admin users")
        school_id = current_user.school_id

    user = UserORM(
        school_id=school_id,
        username=payload.username,
        full_name=payload.full_name,
        role=payload.role,
        nip=payload.nip,
        jabatan=payload.jabatan,
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    db.flush()
    write_audit_log(db, current_user, "create_user", "user", user.id, f"Created user {user.username}")
    db.commit()
    db.refresh(user)

    return _user_response(user)


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user_from_admin(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> UserResponse:
    user = tenant_get(db, UserORM, user_id, current_user)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.username is not None and payload.username != user.username:
        existing = db.query(UserORM).filter(UserORM.username == payload.username).first()
        if existing is not None:
            raise HTTPException(status_code=400, detail="Username already exists")
        user.username = payload.username

    if payload.full_name is not None:
        user.full_name = payload.full_name

    if payload.nip is not None:
        user.nip = payload.nip.strip() or None

    if payload.jabatan is not None:
        user.jabatan = payload.jabatan.strip() or None

    if payload.role is not None:
        if user.role == ROLE_ADMIN and payload.role != ROLE_ADMIN and user.is_active and _active_admin_count(db, user.school_id) <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the last active admin")
        user.role = payload.role

    if payload.is_active is not None:
        if user.id == current_user.id and payload.is_active is False:
            raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
        if user.role == ROLE_ADMIN and user.is_active and payload.is_active is False and _active_admin_count(db, user.school_id) <= 1:
            raise HTTPException(status_code=400, detail="Cannot deactivate the last active admin")
        user.is_active = payload.is_active

    write_audit_log(db, current_user, "edit_user", "user", user.id, f"Edited user {user.username}")
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_response(user)


@router.post("/users/{user_id}/reset-password")
def reset_user_password(
    user_id: int,
    payload: PasswordResetRequest,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> dict:
    user = tenant_get(db, UserORM, user_id, current_user)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = hash_password(payload.new_password)
    write_audit_log(db, current_user, "reset_password", "user", user.id, f"Reset password for {user.username}")
    db.add(user)
    db.commit()
    return {"message": "Password reset successfully"}


@router.post("/users/{user_id}/activate", response_model=UserResponse)
def activate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> UserResponse:
    user = tenant_get(db, UserORM, user_id, current_user)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = True
    write_audit_log(db, current_user, "activate_user", "user", user.id, f"Activated user {user.username}")
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_response(user)


@router.post("/users/{user_id}/deactivate", response_model=UserResponse)
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> UserResponse:
    user = tenant_get(db, UserORM, user_id, current_user)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
    if user.role == ROLE_ADMIN and user.is_active and _active_admin_count(db, user.school_id) <= 1:
        raise HTTPException(status_code=400, detail="Cannot deactivate the last active admin")
    user.is_active = False
    write_audit_log(db, current_user, "deactivate_user", "user", user.id, f"Deactivated user {user.username}")
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_response(user)


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> dict:
    user = tenant_get(db, UserORM, user_id, current_user)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    if user.role == ROLE_ADMIN and user.is_active and _active_admin_count(db, user.school_id) <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the last active admin")
    username = user.username
    db.delete(user)
    write_audit_log(db, current_user, "delete_user", "user", user_id, f"Deleted user {username}")
    db.commit()
    return {"message": "User deleted"}


@router.get("/audit-logs", response_model=AuditLogListResponse)
def list_audit_logs(
    user: str | None = None,
    action: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN)),
) -> AuditLogListResponse:
    query = tenant_query(db.query(AuditLogORM), AuditLogORM, current_user)

    if user:
        like_user = f"%{user.strip()}%"
        query = query.filter(AuditLogORM.username.ilike(like_user))
    if action:
        query = query.filter(AuditLogORM.action == action.strip())
    if date_from:
        query = query.filter(AuditLogORM.timestamp >= datetime.strptime(date_from, "%Y-%m-%d"))
    if date_to:
        query = query.filter(AuditLogORM.timestamp < datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59))
    if search:
        like_search = f"%{search.strip()}%"
        query = query.filter(
            (AuditLogORM.username.ilike(like_search))
            | (AuditLogORM.action.ilike(like_search))
            | (AuditLogORM.entity_type.ilike(like_search))
            | (AuditLogORM.entity_id.ilike(like_search))
            | (AuditLogORM.details.ilike(like_search))
        )

    total = query.count()
    logs = (
        query.order_by(AuditLogORM.timestamp.desc(), AuditLogORM.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return AuditLogListResponse(
        items=[
            AuditLogResponse(
                id=log.id,
                user_id=log.user_id,
                username=log.username,
                action=log.action,
                entity_type=log.entity_type,
                entity_id=log.entity_id,
                details=log.details,
                timestamp=log.timestamp,
            )
            for log in logs
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/dashboard/advanced-stats")
def dashboard_advanced_stats(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
):
    today = date.today().isoformat()
    month_prefix = today[:7]

    visits = tenant_query(db.query(UKSVisitORM), UKSVisitORM, current_user).all()
    monthly_visits = [v for v in visits if str(v.visit_date).startswith(month_prefix)]
    today_visits = [v for v in visits if str(v.visit_date) == today]
    low_stock = (
        tenant_query(db.query(MedicineInventoryORM), MedicineInventoryORM, current_user)
        .filter(MedicineInventoryORM.stock <= MedicineInventoryORM.minimum_stock)
        .order_by(MedicineInventoryORM.name.asc())
        .limit(10)
        .all()
    )
    pending_controls = [
        v for v in visits
        if getattr(v, "control_date", None) and not getattr(v, "control_done", False)
    ]
    student_counter: dict[str, dict] = {}
    for visit in monthly_visits:
        patient = tenant_get(db, PatientORM, visit.patient_id, current_user)
        key = visit.patient_id
        if key not in student_counter:
            student_counter[key] = {
                "student_id": key,
                "name": patient.name if patient else key,
                "class_name": patient.class_name if patient else "-",
                "total": 0,
            }
        student_counter[key]["total"] += 1

    return {
        "today_visits": len(today_visits),
        "monthly_visits": len(monthly_visits),
        "top_monthly_students": sorted(student_counter.values(), key=lambda x: x["total"], reverse=True)[:10],
        "low_stock": [
            {
                "id": med.id,
                "name": med.name,
                "stock": med.stock,
                "unit": med.unit,
                "minimum_stock": med.minimum_stock,
            }
            for med in low_stock
        ],
        "pending_controls": [
            {
                "visit_id": visit.id,
                "patient_id": visit.patient_id,
                "patient_name": (tenant_get(db, PatientORM, visit.patient_id, current_user).name if tenant_get(db, PatientORM, visit.patient_id, current_user) else visit.patient_id),
                "control_date": visit.control_date,
                "referral_place": visit.referral_place or visit.referral_to,
            }
            for visit in sorted(pending_controls, key=lambda v: str(v.control_date))[:10]
        ],
        "whatsapp": {
            "configured": bool(os.getenv("FONNTE_TOKEN")),
            "visits_with_parent_phone": sum(1 for v in today_visits if (tenant_get(db, PatientORM, v.patient_id, current_user) and tenant_get(db, PatientORM, v.patient_id, current_user).parent_phone)),
            "visits_without_parent_phone": sum(1 for v in today_visits if not (tenant_get(db, PatientORM, v.patient_id, current_user) and tenant_get(db, PatientORM, v.patient_id, current_user).parent_phone)),
        },
    }


@router.get("/whatsapp/logs")
def list_whatsapp_logs(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> list[dict]:
    query = tenant_query(db.query(UKSVisitORM), UKSVisitORM, current_user).order_by(UKSVisitORM.id.desc())
    if status_filter:
        query = query.filter(UKSVisitORM.whatsapp_status == status_filter)
    visits = query.limit(limit).all()
    rows = []
    for visit in visits:
        patient = tenant_get(db, PatientORM, visit.patient_id, current_user)
        rows.append(
            {
                "visit_id": visit.id,
                "visit_date": visit.visit_date,
                "patient_id": visit.patient_id,
                "patient_name": patient.name if patient else visit.patient_id,
                "parent_phone": patient.parent_phone if patient else None,
                "status": visit.whatsapp_status or "skipped",
                "message": friendly_whatsapp_message(visit.whatsapp_status, visit.whatsapp_message),
            }
        )
    return rows


@router.post("/whatsapp/visits/{visit_id}/resend")
def resend_visit_whatsapp(
    visit_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> dict:
    visit = tenant_get(db, UKSVisitORM, visit_id, current_user)
    if visit is None:
        raise HTTPException(status_code=404, detail="UKS visit not found")
    patient = tenant_get(db, PatientORM, visit.patient_id, current_user)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    status_text, detail = send_whatsapp_message(
        patient.parent_phone,
        build_uks_visit_whatsapp_message(patient, visit),
    )
    visit.whatsapp_status = status_text
    visit.whatsapp_message = detail
    db.add(visit)
    write_audit_log(db, current_user, "resend_whatsapp_visit", "uks_visit", visit.id, f"{status_text}: {detail}")
    db.commit()
    return {"whatsapp_status": status_text, "whatsapp_message": friendly_whatsapp_message(status_text, detail)}


@router.get("/system/health-check")
def system_health_check(
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
):
    checks = []
    try:
        db.query(UserORM).count()
        checks.append({"name": "Database", "status": "ok", "detail": "Koneksi database aktif"})
    except Exception as exc:
        checks.append({"name": "Database", "status": "error", "detail": str(exc)})

    checks.append({
        "name": "WhatsApp",
        "status": "ok" if os.getenv("FONNTE_TOKEN") else "warning",
        "detail": "FONNTE_TOKEN terisi" if os.getenv("FONNTE_TOKEN") else "FONNTE_TOKEN belum diisi",
    })
    kemensos_logo = Path("app/ui/assets/logo-kemensoss.png")
    sr_logo = Path("app/ui/assets/logo-sekolah-rakyat.png")
    checks.append({
        "name": "Logo Kop Surat PDF",
        "status": "ok" if kemensos_logo.exists() and sr_logo.exists() else "warning",
        "detail": f"{kemensos_logo}; {sr_logo}",
    })
    static_dir = Path("static")
    checks.append({
        "name": "Static Folder",
        "status": "ok" if static_dir.exists() else "error",
        "detail": str(static_dir.resolve()) if static_dir.exists() else "Folder static tidak ditemukan",
    })
    return {"status": "ok" if all(c["status"] != "error" for c in checks) else "error", "checks": checks}


@router.get("/admin/backup")
def download_backup(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
):
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "patients": [
            {
                "id": p.id,
                "nik": p.nik,
                "medical_record_number": p.medical_record_number,
                "name": p.name,
                "age": p.age,
                "gender": p.gender,
                "class_name": p.class_name,
                "birth_date": p.birth_date,
                "parent_name": p.parent_name,
                "parent_phone": p.parent_phone,
            }
            for p in tenant_query(db.query(PatientORM), PatientORM, current_user).all()
        ],
        "visits": [
            {
                "id": v.id,
                "patient_id": v.patient_id,
                "visit_date": v.visit_date,
                "complaint": v.complaint,
                "examination": v.examination,
                "treatment": v.treatment,
                "diagnosis": v.diagnosis,
                "notes": v.notes,
                "referral_to": v.referral_to,
                "referral_status": v.referral_status,
                "referral_place": v.referral_place,
                "control_date": v.control_date,
                "control_done": v.control_done,
            }
            for v in tenant_query(db.query(UKSVisitORM), UKSVisitORM, current_user).all()
        ],
        "medicines": [
            {"name": m.name, "unit": m.unit, "stock": m.stock, "minimum_stock": m.minimum_stock}
            for m in tenant_query(db.query(MedicineInventoryORM), MedicineInventoryORM, current_user).all()
        ],
    }
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return StreamingResponse(
        BytesIO(data),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="backup_emr_uks_{date.today().isoformat()}.json"'},
    )


@router.post("/admin/restore")
def restore_backup(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
):
    restored = {"patients": 0, "visits": 0, "medicines": 0}
    for item in payload.get("patients", []):
        patient = tenant_get(db, PatientORM, str(item.get("id")), current_user)
        if patient is None:
            patient = PatientORM(school_id=current_user.school_id, id=str(item.get("id")), name=item.get("name") or "-", age=int(item.get("age") or 0), gender=item.get("gender") or "-")
            db.add(patient)
        patient.name = item.get("name") or patient.name
        patient.age = int(item.get("age") or patient.age or 0)
        patient.gender = item.get("gender") or patient.gender
        patient.class_name = item.get("class_name")
        patient.birth_date = item.get("birth_date")
        if "nik" in item:
            patient.nik = item.get("nik")
        if "medical_record_number" in item:
            patient.medical_record_number = item.get("medical_record_number")
        patient.parent_name = item.get("parent_name")
        patient.parent_phone = item.get("parent_phone")
        restored["patients"] += 1

    for item in payload.get("medicines", []):
        med = tenant_query(db.query(MedicineInventoryORM), MedicineInventoryORM, current_user).filter(MedicineInventoryORM.name == item.get("name")).first()
        if med is None:
            med = MedicineInventoryORM(school_id=current_user.school_id, name=item.get("name") or "-", unit=item.get("unit") or "tablet", stock=0, minimum_stock=10)
            db.add(med)
        med.unit = item.get("unit") or med.unit
        med.stock = int(item.get("stock") or 0)
        med.minimum_stock = int(item.get("minimum_stock") or 0)
        restored["medicines"] += 1

    for item in payload.get("visits", []):
        patient_id = str(item.get("patient_id") or "")
        if not patient_id or tenant_get(db, PatientORM, patient_id, current_user) is None:
            continue
        visit = None
        if item.get("id") is not None:
            visit = tenant_get(db, UKSVisitORM, int(item.get("id")), current_user)
        if visit is None:
            visit = UKSVisitORM(
                school_id=current_user.school_id,
                patient_id=patient_id,
                visit_date=item.get("visit_date") or date.today().isoformat(),
                complaint=item.get("complaint") or "-",
                examination=item.get("examination") or "-",
                treatment=item.get("treatment") or "-",
            )
            db.add(visit)
        visit.patient_id = patient_id
        visit.visit_date = item.get("visit_date") or visit.visit_date
        visit.complaint = item.get("complaint") or visit.complaint
        visit.examination = item.get("examination") or visit.examination
        visit.treatment = item.get("treatment") or visit.treatment
        visit.diagnosis = item.get("diagnosis")
        visit.notes = item.get("notes")
        visit.referral_to = item.get("referral_to")
        visit.referral_status = item.get("referral_status")
        visit.referral_place = item.get("referral_place")
        visit.control_date = item.get("control_date")
        visit.control_done = bool(item.get("control_done"))
        restored["visits"] += 1
    write_audit_log(db, current_user, "restore_backup", "system", None, json.dumps(restored))
    db.commit()
    return {"message": "Restore selesai", "restored": restored}


@router.post("/patients/import-excel")
def import_patients_excel(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
):
    content = payload.get("content_base64")
    if not content:
        raise HTTPException(status_code=400, detail="content_base64 wajib diisi")
    raw = base64.b64decode(content.split(",", 1)[-1])
    workbook = load_workbook(BytesIO(raw), data_only=True)
    sheet = workbook.active
    headers = [str(cell.value or "").strip().lower() for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
    aliases = {
        "id": ["id", "nis", "id / nis"],
        "nik": ["nik"],
        "medical_record_number": ["no", "no rm", "nomor rm", "no. rm", "medical_record_number"],
        "name": ["nama", "nama lengkap", "name", "full name"],
        "gender": ["gender", "jenis kelamin", "jk"],
        "birth_date": ["tanggal lahir", "birth date", "birth_date"],
        "class_name": ["kelas", "class", "class_name"],
        "parent_name": ["wali asuh", "nama wali asuh", "orang tua", "parent name"],
        "parent_phone": ["nomor hp wali asuh", "no hp", "hp wali", "parent phone"],
    }

    def idx(key: str) -> int | None:
        for alias in aliases[key]:
            if alias in headers:
                return headers.index(alias)
        return None

    id_idx = idx("id")
    name_idx = idx("name")
    if id_idx is None or name_idx is None:
        raise HTTPException(status_code=400, detail="Kolom NIS/ID dan Nama wajib ada")

    rows = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if not row or not row[id_idx] or not row[name_idx]:
            continue
        item = {
            "id": str(row[id_idx]).strip(),
            "name": str(row[name_idx]).strip(),
            "gender": str(row[idx("gender")] or "-").strip() if idx("gender") is not None else "-",
            "birth_date": str(row[idx("birth_date")] or "").strip() if idx("birth_date") is not None else None,
            "class_name": str(row[idx("class_name")] or "").strip() if idx("class_name") is not None else None,
            "parent_name": str(row[idx("parent_name")] or "").strip() if idx("parent_name") is not None else None,
            "parent_phone": str(row[idx("parent_phone")] or "").strip() if idx("parent_phone") is not None else None,
        }
        nik_idx = idx("nik")
        if nik_idx is not None and row[nik_idx] not in (None, ""):
            value = row[nik_idx]
            if not isinstance(value, str) or len(value.strip()) != 16 or not all(c in "0123456789" for c in value.strip()):
                raise HTTPException(status_code=400, detail=f"NIK untuk NIS {item['id']} harus berupa teks 16 digit. Atur format kolom Excel menjadi Text.")
            item["nik"] = value.strip()
        medical_record_number_idx = idx("medical_record_number")
        if medical_record_number_idx is not None and row[medical_record_number_idx] not in (None, ""):
            item["medical_record_number"] = str(row[medical_record_number_idx]).strip()
        rows.append(item)

    if payload.get("preview", False):
        return {"preview": rows[:20], "total": len(rows)}

    created = 0
    updated = 0
    for item in rows:
        patient = tenant_get(db, PatientORM, item["id"], current_user)
        if patient is None:
            patient = PatientORM(
                school_id=current_user.school_id,
                id=item["id"],
                name=item["name"],
                age=0,
                gender=item["gender"],
            )
            db.add(patient)
            created += 1
        else:
            updated += 1
        patient.name = item["name"]
        if "nik" in item:
            patient.nik = item["nik"]
        if "medical_record_number" in item:
            patient.medical_record_number = item["medical_record_number"]
        patient.gender = item["gender"]
        patient.class_name = item["class_name"]
        patient.birth_date = item["birth_date"]
        patient.parent_name = item["parent_name"]
        patient.parent_phone = item["parent_phone"]
    write_audit_log(db, current_user, "import_patients_excel", "patient", None, f"created={created}; updated={updated}")
    db.commit()
    return {"message": "Import siswa selesai", "created": created, "updated": updated, "total": len(rows)}


@router.post("/uks/visits/{visit_id}/notify-rest-letter")
def notify_rest_letter(
    visit_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
):
    visit = tenant_get(db, UKSVisitORM, visit_id, current_user)
    if visit is None:
        raise HTTPException(status_code=404, detail="UKS visit not found")
    patient = tenant_get(db, PatientORM, visit.patient_id, current_user)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    status_text, message = send_whatsapp_message(patient.parent_phone, build_rest_letter_whatsapp_message(patient, visit))
    write_audit_log(db, current_user, "notify_rest_letter", "uks_visit", visit.id, f"{status_text}: {message}")
    db.commit()
    return {"whatsapp_status": status_text, "whatsapp_message": message}


def _visit_or_404(db: Session, visit_id: int, current_user: UserORM) -> tuple[UKSVisitORM, PatientORM]:
    visit = tenant_get(db, UKSVisitORM, visit_id, current_user)
    if visit is None:
        raise HTTPException(status_code=404, detail="UKS visit not found")
    patient = tenant_get(db, PatientORM, visit.patient_id, current_user)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return visit, patient


@router.get("/uks/visits/{visit_id}/referral-letter")
def uks_referral_letter_pdf(
    visit_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
):
    visit, patient = _visit_or_404(db, visit_id, current_user)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=24, bottomMargin=28, leftMargin=42, rightMargin=42)
    styles = getSampleStyleSheet()
    elements = []
    _append_pdf_letterhead(elements, doc, "SURAT RUJUKAN UKS", f"Tanggal: {visit.visit_date}", styles, pdf_school_for_user(db, current_user))
    rows = [
        ["Nama", patient.name],
        ["NIS", patient.id],
        ["Kelas", patient.class_name or "-"],
        ["Keluhan", visit.complaint],
        ["Diagnosa", visit.diagnosis or "-"],
        ["Tindakan", visit.treatment],
        ["Tujuan Rujukan", visit.referral_to or visit.referral_place or "Fasilitas kesehatan terdekat"],
    ]
    elements.append(Table(rows, colWidths=[130, doc.width - 130], style=TableStyle([
        ("GRID", (0, 0), (-1, -1), .4, colors.lightgrey),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 7),
    ])))
    _append_pdf_signature(elements, doc, current_user, styles, "Petugas UKS", pdf_school_for_user(db, current_user))
    doc.build(elements)
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="surat_rujukan_{visit_id}.pdf"'})


@router.get("/uks/visits/{visit_id}/rest-letter")
def uks_rest_letter_pdf(
    visit_id: int,
    reason: str = Query(default="Istirahat", min_length=2, max_length=300),
    days: int = Query(default=1, ge=1, le=30),
    start_date: date | None = None,
    notes: str | None = Query(default=None, max_length=1000),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
):
    visit, patient = _visit_or_404(db, visit_id, current_user)
    if start_date is None:
        try:
            start_date = date.fromisoformat(str(visit.visit_date)[:10])
        except ValueError:
            start_date = date.today()
    end_date = start_date + timedelta(days=days - 1)
    reason_text = " ".join(reason.split())
    notes_text = " ".join(notes.split()) if notes else ""
    if len(reason_text) > 180:
        reason_text = f"{reason_text[:177].rsplit(' ', 1)[0]}..."
    if len(notes_text) > 240:
        notes_text = f"{notes_text[:237].rsplit(' ', 1)[0]}..."
    school = pdf_school_for_user(db, current_user)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A5), topMargin=14, bottomMargin=14, leftMargin=24, rightMargin=24)
    styles = getSampleStyleSheet()
    title_style = styles["Title"].clone("RestLetterTitle")
    title_style.textColor = colors.HexColor("#1e3a8a")
    title_style.fontSize = 13
    title_style.leading = 15
    title_style.alignment = 1
    label_style = styles["Normal"].clone("RestLetterLabel")
    label_style.textColor = colors.HexColor("#475569")
    label_style.fontSize = 8
    body_style = styles["Normal"].clone("RestLetterBody")
    body_style.fontSize = 9
    body_style.leading = 11
    elements = []
    letterhead = letterhead_flowable(doc.width, school)
    if letterhead:
        elements.extend([letterhead, Spacer(1, 4)])
    elements.append(Paragraph("SURAT IZIN ISTIRAHAT", title_style))
    elements.append(Paragraph("UNIT KESEHATAN SEKOLAH", title_style))
    elements.append(Spacer(1, 3))
    elements.append(Paragraph("Berdasarkan pemeriksaan kesehatan di Unit Kesehatan Sekolah, siswa berikut disarankan untuk beristirahat.", body_style))
    elements.append(Spacer(1, 6))
    rows = [
        [Paragraph("<b>Nama Siswa</b>", label_style), Paragraph(escape(patient.name), body_style)],
        [Paragraph("<b>NIS</b>", label_style), Paragraph(escape(patient.id), body_style)],
        [Paragraph("<b>Kelas</b>", label_style), Paragraph(escape(patient.class_name or "-"), body_style)],
        [Paragraph("<b>Keluhan / Alasan</b>", label_style), Paragraph(escape(reason_text), body_style)],
        [Paragraph("<b>Tanggal Izin</b>", label_style), Paragraph(f"{start_date.strftime('%d-%m-%Y')} s.d. {end_date.strftime('%d-%m-%Y')}", body_style)],
    ]
    elements.append(Table(rows, colWidths=[125, doc.width - 125], style=TableStyle([
        ("GRID", (0, 0), (-1, -1), .45, colors.HexColor("#bfdbfe")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eff6ff")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 5),
    ])))
    elements.append(Spacer(1, 7))
    rest_text = f"<b>Rekomendasi UKS</b><br/>Siswa disarankan beristirahat selama <b>{days} hari</b> dan dapat kembali mengikuti kegiatan setelah kondisi membaik."
    if notes_text:
        rest_text += f"<br/><b>Catatan:</b> {escape(notes_text)}"
    elements.append(Table([[Paragraph(rest_text, body_style)]], colWidths=[doc.width], style=TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef2ff")),
        ("BOX", (0, 0), (-1, -1), .7, colors.HexColor("#818cf8")),
        ("LINEBEFORE", (0, 0), (0, -1), 4, colors.HexColor("#4f46e5")),
        ("PADDING", (0, 0), (-1, -1), 7),
    ])))
    elements.append(Spacer(1, 7))
    elements.append(Paragraph("Demikian surat izin ini dibuat untuk dipergunakan sebagaimana mestinya. Terima kasih atas perhatian dan kerja samanya.", body_style))
    signature_style = styles["Normal"].clone("RestLetterSignature")
    signature_style.fontSize = 8.5
    signature_style.leading = 10
    signature_city = school.city if school and school.city else "-"
    signer_name = current_user.full_name or "-"
    signer_nip = getattr(current_user, "nip", None) or "-"
    signer_title = getattr(current_user, "jabatan", None) or "Petugas UKS"
    elements.append(Spacer(1, 7))
    elements.append(Table([["", [
        Paragraph(f"{signature_city}, {datetime.now().strftime('%d/%m/%Y')}", signature_style),
        Paragraph(signer_title, signature_style),
        Spacer(1, 24),
        Paragraph(f"<b>{escape(signer_name)}</b>", signature_style),
        Paragraph(f"NIP. {escape(str(signer_nip))}", signature_style),
    ]]], colWidths=[doc.width - 170, 170], style=TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ])))
    doc.build(elements)
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="surat_izin_{visit_id}.pdf"'})


@router.post("/ckg/students/{student_id}/notify-completed")
def notify_ckg_completed(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
):
    student = tenant_get(db, CKGStudentORM, student_id, current_user)
    if student is None:
        raise HTTPException(status_code=404, detail="CKG student not found")
    patient = (
        tenant_query(db.query(PatientORM), PatientORM, current_user)
        .filter(PatientORM.id == student.nis)
        .first()
    )
    phone = student.parent_phone or (patient.parent_phone if patient else None)
    parent_name = student.parent_name or (patient.parent_name if patient else None) or "Wali Asuh / Orang Tua"
    message = f"""[EMR UKS Sekolah Rakyat]

Yth. {parent_name},

Hasil CKG siswa {student.full_name} telah selesai diproses.

Status: {student.status}
Silakan hubungi petugas UKS bila diperlukan tindak lanjut."""
    status_text, detail = send_whatsapp_message(phone, message)
    write_audit_log(db, current_user, "notify_ckg_completed", "ckg_student", student.id, f"{status_text}: {detail}")
    db.commit()
    return {"whatsapp_status": status_text, "whatsapp_message": detail}


@router.get("/audit-logs/export/excel")
def export_audit_logs_excel(
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN)),
):
    logs = tenant_query(db.query(AuditLogORM), AuditLogORM, current_user).order_by(AuditLogORM.timestamp.desc()).limit(5000).all()
    wb = Workbook()
    ws = wb.active
    ws.title = "Audit Log"
    ws.append(["Timestamp", "User", "Action", "Entity", "Entity ID", "Details"])
    for log in logs:
        ws.append([str(log.timestamp), log.username, log.action, log.entity_type, log.entity_id, log.details])
    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="audit_log.xlsx"'},
    )
    PasswordResetRequest,
