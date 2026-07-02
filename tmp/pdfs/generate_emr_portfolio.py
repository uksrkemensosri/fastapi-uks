from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "output" / "pdf"
TMP_DIR = ROOT / "tmp" / "pdfs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PDF_PATH = OUT_DIR / "Nur_Indah_EMR_SEHATI_Portfolio.pdf"
SCREENSHOT = TMP_DIR / "emr_login.png"

PAGE_W, PAGE_H = A4
MARGIN = 17 * mm
DEEP = colors.HexColor("#12323A")
TEAL = colors.HexColor("#168276")
MINT = colors.HexColor("#EAF6F3")
INK = colors.HexColor("#24313A")
MUTED = colors.HexColor("#6B7780")
LINE = colors.HexColor("#D8E7E4")
WHITE = colors.white


styles = {
    "kicker": ParagraphStyle("kicker", fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=TEAL),
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=24, leading=28, textColor=DEEP),
    "subtitle": ParagraphStyle("subtitle", fontName="Helvetica", fontSize=10.5, leading=14, textColor=MUTED),
    "section": ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=DEEP, spaceBefore=9, spaceAfter=5),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9, leading=12.5, textColor=INK),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8.2, leading=11.2, textColor=INK),
    "muted": ParagraphStyle("muted", fontName="Helvetica", fontSize=8, leading=10.5, textColor=MUTED),
    "pill": ParagraphStyle("pill", fontName="Helvetica-Bold", fontSize=8.2, leading=10, textColor=TEAL, alignment=TA_CENTER),
    "metric": ParagraphStyle("metric", fontName="Helvetica-Bold", fontSize=16, leading=18, textColor=DEEP, alignment=TA_CENTER),
    "metric_label": ParagraphStyle("metric_label", fontName="Helvetica", fontSize=7.5, leading=9, textColor=MUTED, alignment=TA_CENTER),
}


def p(text, style="body"):
    return Paragraph(text, styles[style])


def bullet(text):
    return Paragraph(f"- {text}", ParagraphStyle("bullet", parent=styles["body"], leftIndent=8, firstLineIndent=-5, spaceAfter=2))


def chip(text):
    table = Table([[p(text, "pill")]], colWidths=[36 * mm], rowHeights=[8 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), MINT),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def card(title, lines):
    content = [p(title, "section")]
    for line in lines:
        content.append(bullet(line))
    table = Table([[content]], colWidths=[(PAGE_W - 2 * MARGIN - 8 * mm) / 2])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FBFDFC")),
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def metric(value, label):
    t = Table([[p(value, "metric")], [p(label, "metric_label")]], colWidths=[36 * mm], rowHeights=[13 * mm, 10 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), WHITE),
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return t


def background(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(MINT)
    canvas.rect(0, PAGE_H - 50 * mm, PAGE_W, 50 * mm, fill=1, stroke=0)
    canvas.setFillColor(TEAL)
    canvas.rect(0, PAGE_H - 50 * mm, PAGE_W, 3 * mm, fill=1, stroke=0)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(PAGE_W - MARGIN, 9 * mm, f"Nur Indah Fitriana Dewi | Portfolio | Page {doc.page}")
    canvas.restoreState()


def build_story():
    story = [
        Spacer(1, 8 * mm),
        p("HEALTHCARE DIGITALIZATION PROJECT", "kicker"),
        p("SEHATI - EMR UKS Sekolah Rakyat", "title"),
        p("An integrated digital healthcare system for school clinic documentation, student health records, medication inventory, reporting, and nursing decision support.", "subtitle"),
        Spacer(1, 14),
        Table(
            [[chip("EMR UKS"), chip("FastAPI"), chip("SQLite/PostgreSQL"), chip("Role-Based Access")]],
            colWidths=[39 * mm, 39 * mm, 39 * mm, 39 * mm],
            style=TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]),
        ),
        Spacer(1, 10),
        p("Project Overview", "section"),
        p(
            "SEHATI is an Electronic Medical Record (EMR) application designed for school health unit services. "
            "It helps healthcare staff document student visits, manage patient records, record medication use, "
            "generate reports, and maintain a more organized and traceable clinical administration workflow."
        ),
        Spacer(1, 10),
        Table(
            [[metric("50+", "API endpoints"), metric("2", "User roles"), metric("PDF/XLSX", "Report outputs"), metric("NANDA", "Care support")]],
            colWidths=[39 * mm, 39 * mm, 39 * mm, 39 * mm],
            style=TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]),
        ),
        Spacer(1, 10),
        Table(
            [
                [
                    card(
                        "Clinical & Operational Features",
                        [
                            "Student/patient identity records and school clinic visit history.",
                            "Documentation of complaints, examination, diagnosis, treatment, notes, referral, and follow-up.",
                            "Medication administration records per visit and minimum stock monitoring.",
                            "Daily and monthly visit reports, PDF/Excel export, and medication mutation reports.",
                        ],
                    ),
                    card(
                        "Governance & Safety",
                        [
                            "Login with JWT authentication and signed session cookies.",
                            "Admin and nurse roles to restrict page and endpoint access.",
                            "Audit logs for key actions such as login, data edits, and user management.",
                            "Local database backup and migration support to PostgreSQL on Railway.",
                        ],
                    ),
                ]
            ],
            colWidths=[(PAGE_W - 2 * MARGIN - 8 * mm) / 2, (PAGE_W - 2 * MARGIN - 8 * mm) / 2],
            style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 8)]),
        ),
        Spacer(1, 8),
        p("Role Contribution", "section"),
        bullet("Translated school clinic service needs into a digital workflow covering student registration, visits, treatment, medication, referrals, and reports."),
        bullet("Provided a nursing and healthcare administration perspective so terminology, forms, and report outputs match real clinical workflows."),
        bullet("Promoted structured, searchable, and accountable documentation for school healthcare service activities."),
        PageBreak(),
        Spacer(1, 8 * mm),
        p("Product Snapshot", "kicker"),
        p("SEHATI Application Preview", "title"),
        p("A visual preview of the EMR application interface used as supporting project evidence.", "subtitle"),
        Spacer(1, 12),
    ]

    if SCREENSHOT.exists():
        story.append(Image(str(SCREENSHOT), width=162 * mm, height=91 * mm))
        story.append(Spacer(1, 6))
        story.append(p("SEHATI login page - an integrated digital healthcare service system for Sekolah Rakyat.", "muted"))

    story.extend(
        [
            Spacer(1, 12),
            p("Technical Scope", "section"),
            bullet("Backend API built with FastAPI, using local SQLite storage and PostgreSQL support for deployment."),
            bullet("Data model includes users, audit logs, patients, assessments, recommendations, school clinic visits, medication records, inventory, CKG events, screening stations, referrals, and recommendation letters."),
            bullet("Deployment prepared with Dockerfile, Procfile, railway.json, Railway documentation, and environment variable configuration."),
            bullet("Additional integrations include AI care recommendations, WhatsApp notifications via Fonnte, and PDF/Excel report exports."),
            Spacer(1, 10),
            p("Portfolio Narrative", "section"),
            p(
                "This project demonstrates the ability to combine nursing experience, healthcare administration, and digital workflow understanding. "
                "Its core value is improving school clinic documentation, reporting, and service traceability while preserving healthcare professionals' clinical judgment."
            ),
        ]
    )
    return story


def main():
    doc = BaseDocTemplate(
        str(PDF_PATH),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=10 * mm,
        bottomMargin=14 * mm,
        title="Nur Indah - EMR SEHATI Portfolio",
        author="Nur Indah Fitriana Dewi",
    )
    frame = Frame(MARGIN, 14 * mm, PAGE_W - 2 * MARGIN, PAGE_H - 24 * mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="portfolio", frames=[frame], onPage=background)])
    doc.build(build_story())
    print(PDF_PATH)


if __name__ == "__main__":
    main()
