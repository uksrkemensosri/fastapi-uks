"""Printable collaboration reports. Input rows are explicitly projected per audience."""
from io import BytesIO
from datetime import datetime
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

STATUS = {'BELUM_DIJADWALKAN':'Belum dijadwalkan', 'TERJADWAL':'Terjadwal',
          'MENUNGGU_HASIL':'Menunggu hasil', 'TINDAK_LANJUT':'Dalam tindak lanjut',
          'SELESAI':'Selesai', 'DIBATALKAN':'Dibatalkan'}


def display_date(value):
    if not value:
        return 'Belum ditentukan'
    try:
        return datetime.fromisoformat(str(value)).strftime('%d-%m-%Y')
    except ValueError:
        return str(value)


def build_report(*, school_name, school_address, author, rows, start=None, end=None,
                 patient=None, undated=0):
    clinical = patient is not None
    stream = BytesIO()
    title = 'RIWAYAT INDIVIDUAL FASYANKES' if clinical else 'REKAP KOLABORASI FASYANKES'
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='ReportTitle', fontName='Helvetica-Bold', fontSize=16, leading=20, textColor=colors.HexColor('#443378'), spaceAfter=8))
    styles.add(ParagraphStyle(name='Cell', fontName='Helvetica', fontSize=8, leading=11, spaceAfter=2, splitLongWords=True))
    styles.add(ParagraphStyle(name='SmallNote', fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor('#526078'), spaceAfter=6))
    styles['BodyText'].fontSize=10;styles['BodyText'].leading=14
    styles['Heading4'].spaceBefore=7;styles['Heading4'].spaceAfter=3
    def p(text, style='BodyText'):
        return Paragraph(escape(str(text or '-')).replace('\n','<br/>'), styles[style])
    doc = SimpleDocTemplate(stream, pagesize=A4 if clinical else landscape(A4),
                            rightMargin=14*mm, leftMargin=14*mm, topMargin=15*mm, bottomMargin=17*mm,
                            title=title, author=author)
    now = datetime.now(ZoneInfo('Asia/Jakarta')).strftime('%d-%m-%Y %H:%M WIB')
    story=[p('SEHATI | '+school_name,'Heading2'),p(school_address,'SmallNote'),p(title,'ReportTitle')]
    period='Seluruh riwayat siswa' if clinical else f'Periode kunjungan: {display_date(start)} s.d. {display_date(end)}'
    story += [p(period),p(f'Dicetak: {now} | Penyusun: {author}','SmallNote')]
    if clinical:
        story += [p('TERBATAS - Untuk petugas berwenang. Memuat informasi kesehatan individual.','SmallNote'),
                  p(f"Siswa: {patient['name']} | ID: {patient['id']} | Kelas: {patient.get('class_name') or '-'}"),Spacer(1,12)]
        for index,row in enumerate(rows,1):
            v=row['visit']
            story += [p(f"{index}. {v['facility']} - {STATUS[v['status']]}",'Heading2'),
                      p(f"Kasus #{row['case_id']} | Versi {row['version']} | Rujukan BPJS: {row.get('referral_number') or '-'}",'SmallNote')]
            for label,key in [('Jenis fasyankes','facility_type'),('Poli / layanan','clinic'),('Tanggal rencana','planned_date'),
                              ('Jam rencana','planned_time'),('Tanggal aktual','actual_date'),('Dokter / pemeriksa','doctor'),
                              ('Pendamping','companion'),('Alasan kunjungan','reason'),('Diagnosis menurut dokter','diagnosis'),
                              ('Hasil konsultasi','result'),('Obat / terapi','therapy'),('Tindak lanjut UKS','follow_up'),
                              ('Arahan wali asuh','guardian_instruction'),('Penanggung jawab','responsible'),('Tenggat','due_date'),
                              ('Hambatan','obstacle'),('Alasan pembatalan','cancel_reason')]:
                value=v.get(key)
                if not value:continue
                if key.endswith('_date'):value=display_date(value)
                if key in ('facility_type','clinic','planned_date','planned_time','actual_date','doctor','companion','responsible','due_date'):
                    story.append(p(f'{label}: {value}'))
                else:
                    story += [p(label,'Heading4'),p(value)]
            if v.get('needs_control'):
                story += [p('Kontrol berikutnya','Heading4'),p(f"{display_date(v.get('next_date'))} - {v.get('next_facility') or v['facility']}")]
            story.append(Spacer(1,14))
    else:
        done=sum(bool(r['actual_date']) and r['status']!='DIBATALKAN' for r in rows)
        cancelled=sum(r['status']=='DIBATALKAN' for r in rows)
        story += [p(f'{len(rows)} catatan kunjungan | {len({r["patient_id"] for r in rows})} siswa | {done} terlaksana | {cancelled} dibatalkan'),
                  p('Filter memakai tanggal aktual; jika belum terlaksana, memakai tanggal rencana. Status adalah kondisi terbaru saat dicetak, bukan snapshot historis. Diagnosis, hasil konsultasi, dan obat tidak disertakan.','SmallNote')]
        if undated:story.append(p(f'{undated} catatan tanpa tanggal rencana/aktual tidak masuk rekap periode. Lengkapi jadwal melalui SEHATI.','SmallNote'))
        if rows:
            cells=[[p(x,'Cell') for x in ['No.','Siswa / kelas','Fasyankes','Rencana / aktual','Status','Pendamping / penanggung jawab','Tindak lanjut / koordinasi']]]
            long_notes=[]
            for i,r in enumerate(rows,1):
                follow=f"Tenggat: {display_date(r['due_date'])}"
                if r['needs_control']:
                    follow+=f"\nKontrol: {display_date(r['next_date'])}\nTujuan: {r['next_facility'] or r['facility']}"
                for label,value in [('Hambatan',r['obstacle']),('Pembatalan',r['cancel_reason'] if r['status']=='DIBATALKAN' else '')]:
                    if not value:continue
                    if len(value)>160:
                        follow+=f'\n{label}: {value[:160]}... (lihat rincian #{i})'
                        long_notes.append((i,r['patient_name'],label,value))
                    else:follow+=f'\n{label}: {value}'
                cells.append([p(x,'Cell') for x in [i,f"{r['patient_name']}\n{r['class_name'] or '-'}",r['facility'],
                    f"Rencana: {display_date(r['planned_date'])}\nAktual: {display_date(r['actual_date'])}",STATUS[r['status']],
                    f"Pendamping: {r['companion'] or '-'}\nPJ: {r['responsible'] or '-'}",follow]])
            widths=[8,39,39,34,32,52,65]
            table=Table(cells,colWidths=[w*mm for w in widths],repeatRows=1,splitByRow=1,hAlign='LEFT')
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#ede9f7')),
                ('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,0),.6,colors.HexColor('#b5a6ce')),
                ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f8f9fc')]),
                ('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),
                ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
            story += [Spacer(1,8),table]
            for i,name,label,value in long_notes:
                story += [p(f'Rincian #{i} - {name}: {label}','Heading3'),p(value)]
    if not rows:
        story += [Spacer(1,12),p('Tidak ada catatan kunjungan yang sesuai dengan pilihan laporan.')]
    story.append(Spacer(1,18))
    signature=Table([[p('Disusun oleh'),p('Mengetahui')],[Spacer(1,18*mm),Spacer(1,18*mm)],
                     [p(author),p('............................................')],[p('Petugas / penyusun laporan','SmallNote'),p('Kepala sekolah / pejabat berwenang','SmallNote')]],colWidths=[doc.width/2]*2)
    story.append(KeepTogether([signature]))
    def footer(canvas,document):
        canvas.saveState();canvas.setFont('Helvetica',8);canvas.setFillColor(colors.HexColor('#68748a'))
        canvas.drawString(14*mm,9*mm,'SEHATI - Kolaborasi Fasyankes | '+('Terbatas' if clinical else 'Rekap penanganan'))
        canvas.drawRightString(document.pagesize[0]-14*mm,9*mm,f'Halaman {document.page}');canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return stream.getvalue()
