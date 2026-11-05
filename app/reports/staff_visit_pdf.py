"""Patient-facing projection and rendering of one UKS staff visit."""
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate


def staff_report_data(staff, visit):
    record = visit.record
    return {
        'name': staff.name, 'date': visit.visit_date,
        **{k: record.get(k) or '' for k in ('complaint','examination','diagnosis','treatment','advice')},
        'medications': [(m['medicine_name'], m['dosage'], m['quantity']) for m in record.get('medications', [])],
    }


def build_staff_report(data):
    stream = BytesIO()
    doc = SimpleDocTemplate(stream, pagesize=A4, title='Hasil kunjungan UKS', author='SEHATI')
    styles = getSampleStyleSheet()
    def paragraph(value, style='BodyText'):
        return Paragraph(escape(str(value)).replace('\n','<br/>'),styles[style])
    story = [paragraph('SEHATI | UKS Sekolah Rakyat','Heading3'), paragraph('Hasil kunjungan UKS','Title'),
             paragraph(data['name'],'Heading2'), paragraph('Tanggal kunjungan: '+'-'.join(reversed(data['date'].split('-'))))]
    meds = '\n'.join(f'{name} — {dose} (jumlah: {qty})' for name,dose,qty in data['medications'])
    for label,value in [('Keluhan',data['complaint']),('Hasil pemeriksaan',data['examination']),
                        ('Diagnosis',data['diagnosis']),('Tindakan',data['treatment']),('Obat',meds),('Anjuran',data['advice'])]:
        if value:
            story.extend([paragraph(label,'Heading3'),paragraph(value)])
    doc.build(story)
    return stream.getvalue()
