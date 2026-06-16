from collections import Counter, defaultdict
from datetime import datetime
from html import escape
from io import BytesIO
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.db.dependencies import get_db
from app.db.models import (
    PatientORM,
    RecommendationLetterORM,
    UKSMedicationORM,
    UKSVisitORM,
    UserORM,
    MedicineInventoryORM,
    MedicineTransactionORM,
)
from app.api.recommendations import letterhead_flowable, qr_code_flowable, signature_image_flowable

router = APIRouter(prefix="/reports", tags=["Monthly UKS Report"])

ROLE_ADMIN = "admin"
ROLE_PERAWAT = "perawat"

MONTH_NAMES = {
    1: "Januari",
    2: "Februari",
    3: "Maret",
    4: "April",
    5: "Mei",
    6: "Juni",
    7: "Juli",
    8: "Agustus",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Desember",
}


def validate_period(month: int, year: int) -> tuple[str, str, str]:
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Month must be 1-12")
    if year < 2000 or year > 2100:
        raise HTTPException(status_code=400, detail="Year is invalid")
    prefix = f"{year}-{month:02d}"
    return prefix, MONTH_NAMES[month], f"{MONTH_NAMES[month]} {year}"


def top_items(counter: Counter, limit: int = 10) -> list[dict]:
    return [
        {"name": name or "-", "total": total}
        for name, total in counter.most_common(limit)
    ]


def normalize_stat_text(value: str | None) -> str:
    text = re.sub(r"\s+", " ", (value or "-").strip().lower())
    if not text or text == "-":
        return "-"
    return text[:1].upper() + text[1:]


def dominant_diagnoses(counter: Counter, limit: int = 5) -> list[dict]:
    if not counter:
        return []
    if all(total == 1 for total in counter.values()):
        return [{"name": "Belum terdapat diagnosa dominan pada periode ini.", "total": ""}]
    return top_items(counter, limit)


def compact_text(value: str | None, limit: int = 72) -> str:
    text = (value or "-").strip() or "-"
    return text if len(text) <= limit else f"{text[:limit - 1].rstrip()}..."


def pdf_paragraph(value: str | int | None, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(value if value is not None else "-")), style)


def monthly_report_data(db: Session, month: int, year: int) -> dict:
    prefix, month_name, period_label = validate_period(month, year)
    start_dt = datetime(year, month, 1)
    end_dt = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    visits = (
        db.query(UKSVisitORM)
        .filter(UKSVisitORM.visit_date.like(f"{prefix}%"))
        .order_by(UKSVisitORM.visit_date.asc(), UKSVisitORM.id.asc())
        .all()
    )
    patient_ids = [visit.patient_id for visit in visits if visit.patient_id]
    patients = {
        patient.id: patient
        for patient in db.query(PatientORM).filter(PatientORM.id.in_(patient_ids)).all()
    } if patient_ids else {}
    visit_ids = [visit.id for visit in visits]
    medications = (
        db.query(UKSMedicationORM)
        .filter(UKSMedicationORM.visit_id.in_(visit_ids))
        .all()
        if visit_ids else []
    )
    meds_by_visit: dict[int, list[UKSMedicationORM]] = defaultdict(list)
    for med in medications:
        meds_by_visit[med.visit_id].append(med)

    diagnosis_counter = Counter(normalize_stat_text(visit.diagnosis) for visit in visits)
    complaint_counter = Counter(normalize_stat_text(visit.complaint) for visit in visits)
    medicine_counter = Counter()
    for med in medications:
        medicine_counter[med.medicine_name] += med.quantity
    class_counter = Counter((patients.get(visit.patient_id).class_name if patients.get(visit.patient_id) else "-") or "-" for visit in visits)
    student_counter = Counter(visit.patient_id for visit in visits)
    referral_count = sum(1 for visit in visits if visit.referral_status == "dirujuk" or visit.referral_to or visit.referral_place)
    recommendation_count = (
        db.query(RecommendationLetterORM)
        .filter(RecommendationLetterORM.created_at >= start_dt)
        .filter(RecommendationLetterORM.created_at < end_dt)
        .count()
    )

    top_students = []
    for patient_id, total in student_counter.most_common(10):
        patient = patients.get(patient_id)
        top_students.append(
            {
                "nis": patient_id,
                "name": patient.name if patient else patient_id,
                "class_name": patient.class_name if patient else "-",
                "total": total,
            }
        )

    top_student_detail = None
    if top_students:
        top_id = top_students[0]["nis"]
        top_visits = [visit for visit in visits if visit.patient_id == top_id]
        top_student_detail = {
            **top_students[0],
            "visits": [
                {
                    "tanggal": visit.visit_date,
                    "keluhan": normalize_stat_text(visit.complaint),
                    "diagnosa": normalize_stat_text(visit.diagnosis),
                    "tindakan": visit.treatment,
                }
                for visit in top_visits
            ],
            "dominant_complaints": top_items(Counter(normalize_stat_text(visit.complaint) for visit in top_visits), 5),
            "dominant_diagnoses": top_items(Counter(normalize_stat_text(visit.diagnosis) for visit in top_visits), 5),
        }

    top_complaint = complaint_counter.most_common(1)[0] if complaint_counter else ("-", 0)
    top_diagnosis = diagnosis_counter.most_common(1)[0] if diagnosis_counter else ("-", 0)
    top_student = top_students[0] if top_students else {"name": "-", "total": 0}
    conclusion = (
        f"Pada bulan {period_label} tercatat {len(visits)} kunjungan UKS yang melibatkan "
        f"{len(set(patient_ids))} siswa unik. Keluhan terbanyak adalah {top_complaint[0]} sebanyak "
        f"{top_complaint[1]} kasus. Diagnosa yang paling sering muncul adalah {top_diagnosis[0]} "
        f"sebanyak {top_diagnosis[1]} kasus. Siswa dengan frekuensi kunjungan tertinggi adalah "
        f"{top_student['name']} sebanyak {top_student['total']} kali. Disarankan dilakukan pemantauan "
        f"terhadap siswa dengan kunjungan berulang dan peningkatan edukasi kesehatan sesuai keluhan yang dominan."
    )

    return {
        "period": period_label,
        "month": month,
        "year": year,
        "summary": {
            "total_visits": len(visits),
            "total_student_visits": len(patient_ids),
            "unique_students": len(set(patient_ids)),
            "referrals": referral_count,
            "recommendations": recommendation_count,
        },
        "top_diagnoses": dominant_diagnoses(diagnosis_counter, 5),
        "top_complaints": top_items(complaint_counter, 10),
        "top_medicines": top_items(medicine_counter, 10),
        "top_classes": top_items(class_counter, 10),
        "top_students": top_students,
        "conclusion": conclusion,
        "top_student_detail": top_student_detail,
    }


@router.get("/monthly")
def get_monthly_report(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> dict:
    return monthly_report_data(db, month, year)


def table_style(font_size: float = 6.6) -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#9ca3af")),
            ("FONTSIZE", (0, 0), (-1, -1), font_size),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
    )


def small_table(title: str, rows: list[dict], cell: ParagraphStyle, header: ParagraphStyle, width: float):
    data = [[pdf_paragraph(title, header), pdf_paragraph("Jumlah", header)]]
    data += [
        [pdf_paragraph(compact_text(item["name"], 60), cell), pdf_paragraph(item["total"], cell)]
        for item in rows[:5]
    ]
    table = Table(data, colWidths=[width - 48, 48])
    table.setStyle(table_style())
    return table


@router.get("/monthly/pdf")
def get_monthly_report_pdf(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
    current_user: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
) -> StreamingResponse:
    data = monthly_report_data(db, month, year)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=28, rightMargin=28, topMargin=14, bottomMargin=20)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("MonthlyTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=13, leading=15, alignment=TA_CENTER)
    h = ParagraphStyle("MonthlyHeading", parent=styles["Heading3"], fontName="Helvetica-Bold", fontSize=8.5, leading=10, spaceBefore=4, spaceAfter=2)
    body = ParagraphStyle("MonthlyBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=7.6, leading=9.2, wordWrap="CJK")
    right = ParagraphStyle("MonthlyRight", parent=body, alignment=TA_RIGHT)
    cell = ParagraphStyle("MonthlyCell", parent=body, fontSize=6.4, leading=7.5, wordWrap="CJK")
    header = ParagraphStyle("MonthlyHeaderCell", parent=cell, fontName="Helvetica-Bold")
    elements = []

    letterhead = letterhead_flowable(doc.width)
    if letterhead:
        elements.append(letterhead)
        elements.append(Spacer(1, 3))
    elements.append(Paragraph("LAPORAN BULANAN UKS", title))
    elements.append(Paragraph(f"Periode: {data['period']}", ParagraphStyle("Period", parent=body, alignment=TA_CENTER)))
    elements.append(Spacer(1, 4))

    summary = data["summary"]
    summary_table = Table(
        [
            [pdf_paragraph("Ringkasan Statistik", header), pdf_paragraph("Jumlah", header)],
            [pdf_paragraph("Total kunjungan UKS", cell), pdf_paragraph(summary["total_visits"], cell)],
            [pdf_paragraph("Total siswa yang berkunjung", cell), pdf_paragraph(summary["total_student_visits"], cell)],
            [pdf_paragraph("Total siswa unik", cell), pdf_paragraph(summary["unique_students"], cell)],
            [pdf_paragraph("Jumlah rujukan", cell), pdf_paragraph(summary["referrals"], cell)],
            [pdf_paragraph("Jumlah surat rekomendasi", cell), pdf_paragraph(summary["recommendations"], cell)],
        ],
        colWidths=[doc.width - 70, 70],
    )
    summary_table.setStyle(table_style())
    elements.append(summary_table)
    elements.append(Spacer(1, 4))

    grid_rows = [
        [small_table("Top Diagnosa", data["top_diagnoses"], cell, header, doc.width / 2 - 6), small_table("Top Keluhan", data["top_complaints"], cell, header, doc.width / 2 - 6)],
        [small_table("Top Obat", data["top_medicines"], cell, header, doc.width / 2 - 6), small_table("Top Kelas", data["top_classes"], cell, header, doc.width / 2 - 6)],
    ]
    grid = Table(grid_rows, colWidths=[doc.width / 2, doc.width / 2])
    grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    elements.append(grid)
    elements.append(Spacer(1, 4))

    top_student_rows = [
        [pdf_paragraph("Nama", header), pdf_paragraph("NIS", header), pdf_paragraph("Kelas", header), pdf_paragraph("Kunjungan", header)]
    ] + [
        [pdf_paragraph(item["name"], cell), pdf_paragraph(item["nis"], cell), pdf_paragraph(item["class_name"] or "-", cell), pdf_paragraph(item["total"], cell)]
        for item in data["top_students"][:10]
    ]
    top_student_table = Table(top_student_rows, colWidths=[190, 105, 75, 70])
    top_student_table.setStyle(table_style())
    elements.append(Paragraph("Top Siswa", h))
    elements.append(top_student_table)
    elements.append(Spacer(1, 4))
    elements.append(Paragraph("KESIMPULAN", h))
    elements.append(Paragraph(data["conclusion"], body))
    elements.append(Spacer(1, 5))

    generated_at = datetime.now()
    signature = signature_image_flowable(current_user)
    qr_text = "\n".join(
        [
            f"Nama: {current_user.full_name or '-'}",
            f"NIP: {current_user.nip or '-'}",
            f"Jabatan: {current_user.jabatan or 'Petugas UKS'}",
            f"Tanggal cetak: {generated_at.strftime('%d/%m/%Y')}",
        ]
    )
    signature_qr = qr_code_flowable(qr_text, size=48)
    signature_cells = [
        "",
        [
            Paragraph(f"Bekasi, {generated_at.strftime('%d/%m/%Y')}", right),
            Paragraph(current_user.jabatan or "Petugas UKS", right),
        ],
    ]
    if signature_qr:
        signature_qr.hAlign = "RIGHT"
        signature_cells[1].append(signature_qr)
    elif signature:
        signature.hAlign = "RIGHT"
        signature_cells[1].append(signature)
    else:
        signature_cells[1].append(Spacer(1, 24))
    signature_cells[1].append(Paragraph(current_user.full_name, right))
    signature_cells[1].append(Paragraph(f"NIP. {current_user.nip or '-'}", right))
    signature_table = Table([signature_cells], colWidths=[doc.width - 190, 190])
    signature_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT")]))
    elements.append(signature_table)

    elements.append(PageBreak())
    elements.append(Paragraph(f"Lampiran Laporan Bulanan UKS Periode {data['period']}",ParagraphStyle("LampiranSub",parent=body,alignment=TA_CENTER)))
    elements.append(Spacer(1, 10))
    detail = data["top_student_detail"]
    elements.append(Paragraph("RIWAYAT SISWA PALING SERING BERKUNJUNG", title))
    if detail:
        elements.append(Paragraph(f"{detail['name']} | NIS {detail['nis']} | Kelas {detail['class_name']} | {detail['total']} kunjungan", body))
        elements.append(Spacer(1, 4))
        history_rows = [
            [pdf_paragraph("Tanggal", header), pdf_paragraph("Keluhan", header), pdf_paragraph("Diagnosa", header), pdf_paragraph("Tindakan", header)]
        ] + [
            [
                pdf_paragraph(visit["tanggal"], cell),
                pdf_paragraph(visit["keluhan"], cell),
                pdf_paragraph(visit["diagnosa"], cell),
                pdf_paragraph(visit["tindakan"], cell),
            ]
            for visit in detail["visits"][:10]
        ]
        history_table = Table(history_rows, repeatRows=1, colWidths=[62, 105, 142, doc.width - 309])
        history_table.setStyle(table_style())
        elements.append(history_table)
        elements.append(Spacer(1, 6))
        elements.append(Paragraph("POLA KESEHATAN SISWA", h))
        complaint_text = ", ".join(f"{item['name']} ({item['total']}x)" for item in detail["dominant_complaints"]) or "-"
        diagnosis_text = ", ".join(f"{item['name']} ({item['total']}x)" for item in detail["dominant_diagnoses"]) or "-"
        elements.append(Paragraph(f"Keluhan Dominan: {complaint_text}", body))
        elements.append(Paragraph(f"Diagnosa Dominan: {diagnosis_text}", body))
    else:
        elements.append(Paragraph("Tidak ada data kunjungan pada periode ini.", body))

    doc.build(elements)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename=\"laporan_bulanan_uks_{year}_{month:02d}.pdf\"'},
    )
@router.get("/medicine-mutation")
def medicine_mutation_report(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2000, le=2100),
    db: Session = Depends(get_db),
    _: UserORM = Depends(require_roles(ROLE_ADMIN, ROLE_PERAWAT)),
):
    start_dt = datetime(year, month, 1)
    end_dt = (
        datetime(year + 1, 1, 1)
        if month == 12
        else datetime(year, month + 1, 1)
    )

    transactions = (
        db.query(MedicineTransactionORM)
        .filter(MedicineTransactionORM.transaction_date >= start_dt)
        .filter(MedicineTransactionORM.transaction_date < end_dt)
        .all()
    )

    result = {}

    for trx in transactions:

        if trx.medicine_name not in result:

            stock_item = (
                db.query(MedicineInventoryORM)
                .filter(
                    MedicineInventoryORM.name
                    == trx.medicine_name
                )
                .first()
            )

            result[trx.medicine_name] = {
                "medicine_name": trx.medicine_name,
                "in_qty": 0,
                "out_qty": 0,
                "current_stock":
                    stock_item.stock
                    if stock_item
                    else 0,
            }

        if trx.transaction_type == "IN":
            result[trx.medicine_name]["in_qty"] += trx.quantity

        elif trx.transaction_type == "OUT":
            result[trx.medicine_name]["out_qty"] += trx.quantity

    return list(result.values())