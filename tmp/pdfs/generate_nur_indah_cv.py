from pathlib import Path

from PIL import Image as PILImage, ImageOps
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
ASSET_DIR = ROOT / "tmp" / "pdfs" / "cv_assets"
OUT_DIR = ROOT / "output" / "pdf"
RENDER_DIR = ROOT / "tmp" / "pdfs" / "rendered_cv"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RENDER_DIR.mkdir(parents=True, exist_ok=True)

PHOTO_SRC = ASSET_DIR / "page1_image1.png"
PHOTO_CARD = ASSET_DIR / "photo_card.png"
PDF_PATH = OUT_DIR / "Nur_Indah_Fitriana_Dewi_CV.pdf"

PAGE_W, PAGE_H = A4
MARGIN = 14 * mm
SIDEBAR_W = 58 * mm
GAP = 9 * mm

DEEP = colors.HexColor("#12323A")
TEAL = colors.HexColor("#168276")
SOFT = colors.HexColor("#EAF6F3")
INK = colors.HexColor("#24313A")
MUTED = colors.HexColor("#66727D")
LINE = colors.HexColor("#CFE2DE")
PALE_LINE = colors.HexColor("#E8EFED")
WHITE = colors.white


def prepare_photo():
    img = PILImage.open(PHOTO_SRC).convert("RGBA")
    bbox = img.getbbox()
    img = img.crop(bbox)

    canvas_w, canvas_h = 620, 760
    bg = PILImage.new("RGBA", (canvas_w, canvas_h), (234, 246, 243, 255))
    # Keep the full-body photo but make it feel intentional inside a soft card.
    target_h = 700
    scale = target_h / img.height
    resized = img.resize((int(img.width * scale), target_h), PILImage.LANCZOS)
    x = (canvas_w - resized.width) // 2
    y = canvas_h - resized.height + 22
    bg.alpha_composite(resized, (x, y))
    bg = ImageOps.expand(bg, border=0)
    bg.convert("RGB").save(PHOTO_CARD, quality=95)


styles = {
    "name": ParagraphStyle(
        "name",
        fontName="Helvetica-Bold",
        fontSize=23,
        leading=26,
        textColor=DEEP,
        spaceAfter=3,
    ),
    "role": ParagraphStyle(
        "role",
        fontName="Helvetica",
        fontSize=10.5,
        leading=14,
        textColor=TEAL,
        spaceAfter=9,
    ),
    "summary": ParagraphStyle(
        "summary",
        fontName="Helvetica",
        fontSize=8.7,
        leading=12.2,
        textColor=INK,
    ),
    "section": ParagraphStyle(
        "section",
        fontName="Helvetica-Bold",
        fontSize=10.2,
        leading=13,
        textColor=DEEP,
        spaceBefore=9,
        spaceAfter=5,
    ),
    "job": ParagraphStyle(
        "job",
        fontName="Helvetica-Bold",
        fontSize=9.7,
        leading=12,
        textColor=DEEP,
        spaceBefore=2,
        spaceAfter=1,
    ),
    "place": ParagraphStyle(
        "place",
        fontName="Helvetica",
        fontSize=8.1,
        leading=10.5,
        textColor=MUTED,
        spaceAfter=3,
    ),
    "body": ParagraphStyle(
        "body",
        fontName="Helvetica",
        fontSize=8.35,
        leading=11.2,
        textColor=INK,
        alignment=TA_LEFT,
    ),
    "bullet": ParagraphStyle(
        "bullet",
        fontName="Helvetica",
        fontSize=8.2,
        leading=10.8,
        textColor=INK,
        leftIndent=8,
        firstLineIndent=-5,
        spaceAfter=1.7,
    ),
    "side_head": ParagraphStyle(
        "side_head",
        fontName="Helvetica-Bold",
        fontSize=8.8,
        leading=11,
        textColor=WHITE,
        spaceBefore=8,
        spaceAfter=4,
    ),
    "side": ParagraphStyle(
        "side",
        fontName="Helvetica",
        fontSize=7.75,
        leading=10.4,
        textColor=colors.HexColor("#EEF8F5"),
    ),
    "side_bold": ParagraphStyle(
        "side_bold",
        fontName="Helvetica-Bold",
        fontSize=7.8,
        leading=10.4,
        textColor=WHITE,
        spaceAfter=1,
    ),
    "tiny": ParagraphStyle(
        "tiny",
        fontName="Helvetica",
        fontSize=7.3,
        leading=9.4,
        textColor=MUTED,
        alignment=TA_CENTER,
    ),
}


def p(text, style="body"):
    return Paragraph(text, styles[style])


def rule(width=1, color=LINE):
    return Table(
        [[""]],
        colWidths=[width],
        rowHeights=[1],
        style=TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.6, color)]),
    )


def bullet_list(items):
    return [p(f"- {item}", "bullet") for item in items]


def experience(title, company, dates, items):
    left = Table(
        [[""]],
        colWidths=[4],
        rowHeights=[None],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SOFT),
                ("LINEBEFORE", (0, 0), (-1, -1), 1, TEAL),
            ]
        ),
    )
    content = [p(title, "job"), p(f"{company} | {dates}", "place"), *bullet_list(items)]
    t = Table([[left, content]], colWidths=[5 * mm, PAGE_W - 2 * MARGIN - SIDEBAR_W - GAP - 5 * mm])
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 3),
                ("LEFTPADDING", (1, 0), (1, 0), 2),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return t


def skill(title, text):
    return [p(title, "side_bold"), p(text, "side"), Spacer(1, 3)]


def sidebar(items, include_photo=False):
    flows = []
    if include_photo:
        flows.append(Image(str(PHOTO_CARD), width=42 * mm, height=51.5 * mm))
        flows.append(Spacer(1, 8))
    flows.extend(items)
    return flows


def background(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(DEEP)
    canvas.rect(0, 0, SIDEBAR_W + MARGIN, PAGE_H, fill=1, stroke=0)
    canvas.setFillColor(TEAL)
    canvas.rect(SIDEBAR_W + MARGIN - 3, 0, 3, PAGE_H, fill=1, stroke=0)
    canvas.setFillColor(SOFT)
    canvas.rect(SIDEBAR_W + MARGIN, PAGE_H - 34 * mm, PAGE_W - SIDEBAR_W - MARGIN, 34 * mm, fill=1, stroke=0)
    canvas.setStrokeColor(PALE_LINE)
    canvas.setLineWidth(0.5)
    canvas.line(SIDEBAR_W + MARGIN + GAP, PAGE_H - 34 * mm, PAGE_W - MARGIN, PAGE_H - 34 * mm)
    canvas.setFont("Helvetica", 7.2)
    canvas.setFillColor(colors.HexColor("#7D8B94"))
    canvas.drawRightString(PAGE_W - MARGIN, 8 * mm, f"Nur Indah Fitriana Dewi | Page {doc.page}")
    canvas.restoreState()


def page_layout(left_flows, right_flows, top_gap=8 * mm):
    left_col = sidebar(left_flows)
    table = Table([[left_col, right_flows]], colWidths=[SIDEBAR_W, PAGE_W - 2 * MARGIN - SIDEBAR_W - GAP])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 4),
                ("RIGHTPADDING", (0, 0), (0, 0), 8),
                ("LEFTPADDING", (1, 0), (1, 0), GAP),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), top_gap),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def build_story():
    story = []

    left1 = sidebar(
        [
            p("CONTACT", "side_head"),
            p("Perumahan Tridaya Indah 3<br/>Jl. Palm Raja 4 No. 19<br/>Tambun", "side"),
            Spacer(1, 4),
            p("+62 822-9579-8154", "side"),
            p("nurindah.fitrianadewi@gmail.com", "side"),
            Spacer(1, 8),
            p("CORE SKILLS", "side_head"),
            *skill("Clinical", "Nursing care, triage, Basic Life Support (BLS), health education, wound care."),
            *skill("Administration", "Medical records, shift management, document archiving, payroll data processing."),
            *skill("Technical", "Microsoft Office, BPJS Edabu System."),
            *skill("Languages", "Indonesian (Native), English (Passive)."),
        ],
        include_photo=True,
    )

    right1 = [
        Spacer(1, 6 * mm),
        p("NUR INDAH FITRIANA DEWI", "name"),
        p("Professional Nurse | Healthcare Administrator", "role"),
        rule(width=92 * mm, color=TEAL),
        Spacer(1, 5),
        p("PROFESSIONAL SUMMARY", "section"),
        p(
            "Dedicated and adaptable Registered Nurse with a D3 degree from Poltekkes Kemenkes Jakarta III (2020). "
            "Experienced in clinical nursing, public health, and healthcare administration. Currently serving as a Nurse "
            "at Klinik Pratama Kementerian Sosial, with strengths in comprehensive nursing care, clinical administrative "
            "workflows, patient education, and collaborative medical service delivery.",
            "summary",
        ),
        p("PROFESSIONAL EXPERIENCE", "section"),
        experience(
            "Nurse",
            "Klinik Pratama Kementerian Sosial",
            "June 1, 2025 - Present",
            [
                "Provide comprehensive nursing care and primary medical services to patients within the clinical setting.",
                "Collaborate with the medical team to execute preventive, curative, and rehabilitative procedures.",
                "Manage clinical administration, maintain accurate medical records, and monitor medical supply inventory.",
                "Educate patients and families on health promotion and Clean and Healthy Living Behavior (PHBS).",
            ],
        ),
        experience(
            "Nurse",
            "Klinik 24 Jam Dharma Bhakti Medical Center, Tambun",
            "May 2024 - May 2025",
            [
                "Managed patient care flow, from initial registration to medication dispensing.",
                "Performed patient anamnesis and vital signs monitoring.",
                "Assisted physicians with IV therapy, injections, wound care, and other medical procedures.",
                "Provided health counseling and recovery instructions to patients.",
                "Handled clinical administrative reporting and systematic medical record archiving.",
            ],
        ),
    ]

    story.append(page_layout(left1, right1, top_gap=9 * mm))
    story.append(PageBreak())

    left2 = [
        p("EDUCATION", "side_head"),
        p("Diploma in Nursing<br/>(D3 Keperawatan)", "side_bold"),
        p("Poltekkes Kemenkes Jakarta 3<br/>2017 - 2020<br/>GPA: 3.59", "side"),
        Spacer(1, 8),
        p("CERTIFICATIONS", "side_head"),
        p("Basic Trauma Cardiac Life<br/>Support (BTCLS)<br/>Poltekkes Kemenkes Jakarta 3,<br/>2019", "side"),
        Spacer(1, 5),
        p("Volunteer Contact Tracer<br/>Puskesmas Kecamatan<br/>Duren Sawit, 2020", "side"),
        Spacer(1, 8),
        p("ORGANIZATION", "side_head"),
        p("Head of Information and<br/>Communication", "side_bold"),
        p("Ikatan Alumni Poltekkes<br/>Kemenkes Jakarta 3<br/>2023 - Present", "side"),
    ]

    right2 = [
        Spacer(1, 8 * mm),
        p("PROFESSIONAL EXPERIENCE", "section"),
        experience(
            "HRGA Staff",
            "PT. Bina San Prima, Karawang",
            "May 2021 - April 2024",
            [
                "Managed personnel administration, PKWT registration with Disnaker, and mandatory company reporting to Kemenaker.",
                "Handled employee attendance, shift management, and payroll processing data.",
                "Registered and managed employee BPJS Kesehatan benefits using the Edabu system.",
                "Executed end-to-end recruitment and resignation procedures.",
                "Maintained updated employee databases and organized HRGA documentation.",
            ],
        ),
        experience(
            "Contact Tracer (Covid-19)",
            "Puskesmas Kecamatan Duren Sawit",
            "November 2020 - March 2021",
            [
                "Conducted contact tracing, testing, and treatment monitoring for Covid-19 patients.",
                "Coordinated follow-up communication and documented case progress to support public health response.",
            ],
        ),
        p("PROFILE STRENGTHS", "section"),
        *bullet_list(
            [
                "Balanced clinical, administrative, and public health experience across healthcare and corporate settings.",
                "Able to manage patient-facing care while maintaining accurate documentation and operational discipline.",
                "Quick learner with strong communication, teamwork, problem solving, and loyalty to the organization.",
            ]
        ),
    ]

    story.append(page_layout(left2, right2, top_gap=10 * mm))
    return story


def main():
    prepare_photo()
    doc = BaseDocTemplate(
        str(PDF_PATH),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=8 * mm,
        bottomMargin=12 * mm,
        title="Nur Indah Fitriana Dewi - CV",
        author="Nur Indah Fitriana Dewi",
    )
    frame = Frame(
        MARGIN,
        12 * mm,
        PAGE_W - 2 * MARGIN,
        PAGE_H - 20 * mm,
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
        id="normal",
    )
    doc.addPageTemplates([PageTemplate(id="cv", frames=[frame], onPage=background)])
    doc.build(build_story())
    print(PDF_PATH)


if __name__ == "__main__":
    main()
