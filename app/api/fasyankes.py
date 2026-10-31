"""School-scoped collaboration. Notifications are in-app only; no messaging provider."""
from copy import deepcopy
from datetime import date, datetime, UTC
from typing import Literal
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, ConfigDict, model_validator
from sqlalchemy import update
from sqlalchemy.orm import Session
from app.auth.dependencies import require_roles
from app.auth.tenant import tenant_query, tenant_get, guardian_patient_ids
from app.db.dependencies import get_db
from app.db.models import PatientORM, BPJSReferralORM, UKSVisitORM, UserORM, SchoolORM, GuardianStudentAssignmentORM, AuditLogORM
from app.db.fasyankes import FasyankesCaseORM as Case, FasyankesRevisionORM as Revision, FasyankesNotificationORM as Notice

router = APIRouter(prefix='/api/fasyankes', tags=['Kolaborasi Fasyankes'])
READ = ('admin', 'perawat', 'kepala_sekolah', 'wali_asuh', 'tim_uksr')
WRITE = ('admin', 'perawat')


def today():
    return datetime.now(ZoneInfo('Asia/Jakarta')).date()


class Visit(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=60)
    facility: str = Field(min_length=2, max_length=255)
    facility_type: Literal['Puskesmas', 'Klinik', 'Rumah Sakit', 'Lainnya'] = 'Puskesmas'
    planned_date: date | None = None
    planned_time: str = Field(default='', pattern=r'^([01]\d|2[0-3]):[0-5]\d$|^$')
    actual_date: date | None = None
    status: Literal['BELUM_DIJADWALKAN', 'TERJADWAL', 'MENUNGGU_HASIL', 'TINDAK_LANJUT', 'SELESAI', 'DIBATALKAN'] = 'BELUM_DIJADWALKAN'
    clinic: str = Field(default='', max_length=150)
    doctor: str = Field(default='', max_length=150)
    companion: str = Field(default='', max_length=150)
    reason: str = Field(default='', max_length=2000)
    diagnosis: str = Field(default='', max_length=2000)
    result: str = Field(default='', max_length=5000)
    therapy: str = Field(default='', max_length=3000)
    follow_up: str = Field(default='', max_length=3000)
    guardian_instruction: str = Field(default='', max_length=1500)
    responsible: str = Field(default='', max_length=150)
    due_date: date | None = None
    needs_control: bool = False
    next_date: date | None = None
    next_facility: str = Field(default='', max_length=255)
    parent_visit_id: str | None = Field(default=None, max_length=60)
    obstacle: str = Field(default='', max_length=1000)
    cancel_reason: str = Field(default='', max_length=1000)

    @model_validator(mode='after')
    def validate_state(self):
        if self.status == 'TERJADWAL' and not self.planned_date:
            raise ValueError('Isi tanggal rencana kunjungan')
        if self.status in ('MENUNGGU_HASIL', 'TINDAK_LANJUT', 'SELESAI') and not self.actual_date:
            raise ValueError('Isi tanggal kunjungan aktual sebelum menyatakan sudah berkunjung')
        if self.actual_date and self.actual_date > today():
            raise ValueError('Kunjungan aktual tidak boleh di masa depan')
        if self.status == 'DIBATALKAN' and not self.cancel_reason:
            raise ValueError('Alasan pembatalan wajib diisi')
        if self.status in ('TINDAK_LANJUT', 'SELESAI') and not self.result:
            raise ValueError('Isi hasil konsultasi')
        if self.next_date and not self.needs_control:
            raise ValueError('Aktifkan perlu kontrol untuk mengisi tanggal kontrol')
        if self.next_date and self.actual_date and self.next_date < self.actual_date:
            raise ValueError('Kontrol tidak boleh sebelum kunjungan aktual')
        return self


class Create(BaseModel):
    model_config = ConfigDict(extra='forbid')
    patient_id: str
    referral_id: int | None = None
    uks_visit_id: int | None = None
    visit: Visit


class Change(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(ge=1)
    visit: Visit


class Undo(BaseModel):
    version: int = Field(ge=2)


def case_query(db, user):
    q = tenant_query(db.query(Case), Case, user)
    if user.role == 'wali_asuh':
        q = q.filter(Case.patient_id.in_(guardian_patient_ids(db, user)))
    return q


def owned(db, user, cid):
    c = case_query(db, user).filter(Case.id == cid).first()
    if not c:
        raise HTTPException(404, 'Kolaborasi tidak ditemukan')
    return c


def record(db, c, user, action):
    db.add(Revision(case_id=c.id, version=c.version, actor_id=user.id, action=action, snapshot=deepcopy(c.data)))
    db.add(AuditLogORM(school_id=c.school_id, user_id=user.id, username=user.username, action='fasyankes_'+action, entity_type='fasyankes_case', entity_id=str(c.id), details=f'Versi {c.version}'))
    guardians = db.query(UserORM).join(GuardianStudentAssignmentORM, GuardianStudentAssignmentORM.guardian_id == UserORM.id).filter(
        GuardianStudentAssignmentORM.patient_id == c.patient_id, GuardianStudentAssignmentORM.school_id == c.school_id,
        UserORM.school_id == c.school_id, UserORM.role == 'wali_asuh', UserORM.is_active.is_(True)).all()
    for guardian in guardians:
        db.add(Notice(case_id=c.id, version=c.version, recipient_id=guardian.id))


def create_from_referral(db, referral, user):
    existing = db.query(Case).filter(Case.referral_id == referral.id).first()
    if existing:
        return existing
    v = Visit(id='rujukan-'+str(referral.id), facility=referral.destination_facility, facility_type='Rumah Sakit',
              planned_date=referral.control_date, status='TERJADWAL' if referral.control_date else 'BELUM_DIJADWALKAN', reason=referral.complaint or '')
    c = Case(school_id=referral.school_id, patient_id=referral.patient_id, referral_id=referral.id, version=1, data={'visits':[v.model_dump(mode='json')]})
    db.add(c); db.flush(); record(db, c, user, 'dibuat_dari_rujukan')
    return c


def serialize(db, c, user):
    p = db.get(PatientORM, c.patient_id)
    data = deepcopy(c.data)
    clinical = user.role in ('admin', 'perawat', 'super_admin')
    for v in data['visits']:
        if not clinical:
            for field in ('reason', 'diagnosis', 'result', 'therapy', 'follow_up'):
                v.pop(field, None)
            if user.role != 'wali_asuh':
                v.pop('guardian_instruction', None)
    ref = db.get(BPJSReferralORM, c.referral_id) if c.referral_id else None
    return dict(id=c.id, patient_id=c.patient_id, patient_name=p.name, class_name=p.class_name,
                referral_id=c.referral_id, referral_number=ref.referral_number if ref else None,
                valid_until=ref.valid_until_date if ref else None, uks_visit_id=c.uks_visit_id, version=c.version, **data)


def schedule_items(db, user):
    items=[]
    for c in case_query(db, user).all():
        p=db.get(PatientORM,c.patient_id)
        visits=c.data['visits']
        for v in visits:
            if v['status']=='DIBATALKAN':continue
            base=dict(case_id=c.id, visit_id=v['id'], patient_name=p.name, patient_id=p.id, facility=v['facility'])
            if not v['actual_date'] and v['planned_date']:
                items.append(dict(base, date=v['planned_date'], kind='Kunjungan', overdue=v['planned_date']<today().isoformat()))
            children=[x for x in visits if x.get('parent_visit_id')==v['id'] and x['status']!='DIBATALKAN']
            if v['needs_control'] and not children:
                items.append(dict(base, date=v['next_date'], facility=v['next_facility'] or v['facility'], kind='Kontrol', overdue=bool(v['next_date'] and v['next_date']<today().isoformat())))
    return sorted(items,key=lambda x:x['date'] or '9999')


@router.get('')
def listing(db: Session=Depends(get_db), user: UserORM=Depends(require_roles(*READ))):
    return [serialize(db,c,user) for c in case_query(db,user).order_by(Case.id.desc()).all()]


@router.get('/schedule')
def schedule(db: Session=Depends(get_db), user: UserORM=Depends(require_roles(*READ))):
    return schedule_items(db,user)


@router.get('/referrals')
def referrals(db: Session=Depends(get_db), user: UserORM=Depends(require_roles(*READ))):
    q=tenant_query(db.query(BPJSReferralORM),BPJSReferralORM,user).filter(~BPJSReferralORM.id.in_(db.query(Case.referral_id).filter(Case.referral_id.isnot(None))))
    if user.role=='wali_asuh':q=q.filter(BPJSReferralORM.patient_id.in_(guardian_patient_ids(db,user)))
    return [dict(id=r.id,patient_id=r.patient_id,patient_name=db.get(PatientORM,r.patient_id).name,facility=r.destination_facility,control_date=r.control_date,valid_until=r.valid_until_date) for r in q.all()]


@router.post('/from-referral/{rid}')
def from_referral(rid:int, db: Session=Depends(get_db),user:UserORM=Depends(require_roles(*WRITE))):
    # Lock the source row to serialize concurrent imports on PostgreSQL.
    r=tenant_query(db.query(BPJSReferralORM),BPJSReferralORM,user).filter(BPJSReferralORM.id==rid).with_for_update().first()
    if not r:raise HTTPException(404,'Rujukan tidak ditemukan')
    c=create_from_referral(db,r,user);db.commit()
    return serialize(db,c,user)


@router.post('',status_code=201)
def create(payload:Create,db:Session=Depends(get_db),user:UserORM=Depends(require_roles(*WRITE))):
    p=tenant_get(db,PatientORM,payload.patient_id,user)
    if not p or not p.school_id:raise HTTPException(404,'Siswa tidak ditemukan')
    if payload.referral_id:raise HTTPException(422,'Gunakan integrasi rujukan BPJS')
    if payload.uks_visit_id:
        v=tenant_get(db,UKSVisitORM,payload.uks_visit_id,user)
        if not v or v.patient_id!=p.id:raise HTTPException(404,'Kunjungan UKS tidak sesuai siswa')
    if payload.visit.parent_visit_id:raise HTTPException(422,'Kontrol harus ditambahkan pada kasus asal')
    c=Case(school_id=p.school_id,patient_id=p.id,uks_visit_id=payload.uks_visit_id,version=1,data={'visits':[payload.visit.model_dump(mode='json')]})
    db.add(c);db.flush();record(db,c,user,'dibuat');db.commit()
    return serialize(db,c,user)


def save_version(db,c,user,new_data,expected,action):
    changed=db.execute(update(Case).where(Case.id==c.id,Case.version==expected).values(data=new_data,version=expected+1).execution_options(synchronize_session=False))
    if changed.rowcount!=1:
        db.rollback();raise HTTPException(409,'Catatan telah berubah. Muat ulang sebelum menyimpan.')
    db.refresh(c)
    if c.referral_id:
        referral=db.get(BPJSReferralORM,c.referral_id)
        visits=c.data['visits']
        active=[v for v in visits if v['status']!='DIBATALKAN']
        pending=[v for v in active if v['needs_control'] and not any(x.get('parent_visit_id')==v['id'] for x in active)]
        if pending:
            referral.control_date=pending[-1]['next_date']
            referral.control_done=False
        elif active:
            last=active[-1]
            referral.control_date=last['actual_date'] or last['planned_date']
            referral.control_done=bool(last['actual_date'])
        else:
            referral.control_done=False
    record(db,c,user,action);db.commit()


@router.put('/{cid}/visit')
def save_visit(cid:int,payload:Change,db:Session=Depends(get_db),user:UserORM=Depends(require_roles(*WRITE))):
    c=owned(db,user,cid);data=deepcopy(c.data);v=payload.visit.model_dump(mode='json')
    old=next((x for x in data['visits'] if x['id']==v['id']),None)
    if old and old.get('parent_visit_id')!=v.get('parent_visit_id'):raise HTTPException(422,'Hubungan kontrol tidak dapat diubah')
    if not v['needs_control'] and any(x.get('parent_visit_id')==v['id'] and x['status']!='DIBATALKAN' for x in data['visits']):
        raise HTTPException(409,'Kunjungan sudah mempunyai kontrol lanjutan; pertahankan hubungan kontrol')
    if v.get('parent_visit_id'):
        parent=next((x for x in data['visits'] if x['id']==v['parent_visit_id']),None)
        if not parent or parent['id']==v['id'] or not parent['needs_control'] or parent['status']=='DIBATALKAN':raise HTTPException(422,'Kunjungan asal kontrol tidak valid')
        if any(x['id']!=v['id'] and x.get('parent_visit_id')==parent['id'] and x['status']!='DIBATALKAN' for x in data['visits']):raise HTTPException(409,'Kontrol ini sudah memiliki kunjungan lanjutan')
    if v['status']=='DIBATALKAN' and any(x.get('parent_visit_id')==v['id'] and x['status']!='DIBATALKAN' for x in data['visits']):raise HTTPException(409,'Batalkan kunjungan kontrol turunannya terlebih dahulu')
    data['visits']=[v if x['id']==v['id'] else x for x in data['visits']] if old else [*data['visits'],v]
    save_version(db,c,user,data,payload.version,'kunjungan_diperbarui' if old else 'kunjungan_ditambah')
    return serialize(db,c,user)


@router.post('/{cid}/undo')
def undo(cid:int,payload:Undo,db:Session=Depends(get_db),user:UserORM=Depends(require_roles(*WRITE))):
    c=owned(db,user,cid)
    previous=db.query(Revision).filter(Revision.case_id==cid,Revision.version==payload.version-1).first()
    if not previous:raise HTTPException(409,'Tidak ada versi sebelumnya')
    save_version(db,c,user,deepcopy(previous.snapshot),payload.version,'undo')
    return serialize(db,c,user)


@router.get('/{cid}/history')
def history(cid:int,db:Session=Depends(get_db),user:UserORM=Depends(require_roles(*READ))):
    owned(db,user,cid)
    return [dict(version=r.version,action=r.action,actor=db.get(UserORM,r.actor_id).full_name,recorded_at=r.created_at) for r in db.query(Revision).filter(Revision.case_id==cid).order_by(Revision.version.desc()).all()]


@router.get('/notices/inbox')
def inbox(db:Session=Depends(get_db),user:UserORM=Depends(require_roles(*READ))):
    cs={c.id:c for c in case_query(db,user).all()}
    return [dict(id=n.id,case_id=n.case_id,version=n.version,read_at=n.read_at,created_at=n.created_at,patient_name=db.get(PatientORM,cs[n.case_id].patient_id).name,message='Catatan fasyankes diperbarui. Buka untuk melihat status terbaru dan arahan pendampingan.') for n in db.query(Notice).filter(Notice.recipient_id==user.id,Notice.case_id.in_(cs)).order_by(Notice.id.desc()).limit(100).all()]


@router.post('/notices/{nid}/read')
def read_notice(nid:int,db:Session=Depends(get_db),user:UserORM=Depends(require_roles(*READ))):
    n=db.query(Notice).filter(Notice.id==nid,Notice.recipient_id==user.id).first()
    if not n:raise HTTPException(404,'Notifikasi tidak ditemukan')
    owned(db,user,n.case_id);n.read_at=datetime.now(UTC);db.commit();return {'ok':True}


@router.get('/{cid}/notification-preview')
def preview(cid:int,db:Session=Depends(get_db),user:UserORM=Depends(require_roles(*WRITE))):
    c=owned(db,user,cid);p=db.get(PatientORM,c.patient_id);v=c.data['visits'][-1]
    status=v['status'].replace('_',' ').lower()
    group=f"SEHATI: status penanganan 1 siswa: {status}. " + ('Kunjungan fasyankes telah terlaksana. ' if v['actual_date'] and v['status']!='DIBATALKAN' else '') + 'Riwayat tindakan tersedia di SEHATI.'
    notices=db.query(Notice).filter(Notice.case_id==cid,Notice.version==c.version).all()
    return {'whatsapp_enabled':False,'group':group,'guardian':f"{p.name}: {status}. Tujuan: {v['facility']}. {v['guardian_instruction']}",'recipients':[{'name':db.get(UserORM,n.recipient_id).full_name,'read_at':n.read_at} for n in notices]}


def pdf_response(content,filename):
    return Response(content,media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="{filename}"','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})


@router.get('/reports/summary.pdf')
def summary_pdf(start:date,end:date,school_id:int|None=None,db:Session=Depends(get_db),user:UserORM=Depends(require_roles('admin','perawat','kepala_sekolah','tim_uksr'))):
    from app.reports.fasyankes_pdf import build_report
    if start>end:raise HTTPException(422,'Tanggal awal harus sebelum atau sama dengan tanggal akhir')
    if (end-start).days>366:raise HTTPException(422,'Pilih rentang maksimal 366 hari')
    if user.role=='super_admin':
        if school_id is None:raise HTTPException(422,'Pilih school_id untuk laporan satu sekolah')
        sid=school_id
    else:
        if school_id is not None and school_id!=user.school_id:raise HTTPException(403,'Sekolah tidak sesuai akses')
        sid=user.school_id
    school=db.get(SchoolORM,sid) if sid else None
    if not school:raise HTTPException(404,'Sekolah tidak ditemukan')
    rows=[];undated=0
    for c in case_query(db,user).filter(Case.school_id==sid).all():
        patient=db.get(PatientORM,c.patient_id)
        for v in c.data['visits']:
            when=v['actual_date'] or v['planned_date']
            if not when:undated+=1;continue
            if not start.isoformat()<=when<=end.isoformat():continue
            # Whitelist only coordination fields. Never pass clinical values to summary renderer.
            row={key:v.get(key) for key in ('facility','status','planned_date','actual_date','companion','responsible','due_date','needs_control','next_date','next_facility','obstacle','cancel_reason')}
            row.update(patient_id=patient.id,patient_name=patient.name,class_name=patient.class_name)
            rows.append(row)
    rows.sort(key=lambda r:(r['actual_date'] or r['planned_date'],r['patient_name']))
    content=build_report(school_name=school.school_name,school_address=school.address or '',author=user.full_name,rows=rows,start=start,end=end,undated=undated)
    return pdf_response(content,f'rekap-fasyankes-{start}-{end}.pdf')


@router.get('/reports/student/{patient_id}.pdf')
def student_pdf(patient_id:str,db:Session=Depends(get_db),user:UserORM=Depends(require_roles(*WRITE))):
    from app.reports.fasyankes_pdf import build_report
    patient=tenant_get(db,PatientORM,patient_id,user)
    if not patient:raise HTTPException(404,'Siswa tidak ditemukan')
    school=db.get(SchoolORM,patient.school_id)
    rows=[]
    for c in case_query(db,user).filter(Case.patient_id==patient.id).order_by(Case.id).all():
        ref=db.get(BPJSReferralORM,c.referral_id) if c.referral_id else None
        rows.extend(dict(case_id=c.id,version=c.version,referral_number=ref.referral_number if ref else None,visit=deepcopy(v)) for v in c.data['visits'])
    rows.sort(key=lambda r:(r['visit']['actual_date'] or r['visit']['planned_date'] or '9999',r['case_id']))
    content=build_report(school_name=school.school_name if school else 'Sekolah',school_address=school.address if school else '',author=user.full_name,rows=rows,patient={'id':patient.id,'name':patient.name,'class_name':patient.class_name})
    return pdf_response(content,'riwayat-individual-fasyankes.pdf')
