"""School-scoped collaboration with explicit Fonnte notification delivery."""
import os
import hashlib
import hmac
import json
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlencode
from html import escape
from copy import deepcopy
from datetime import date, datetime, UTC
from typing import Literal
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, HTMLResponse, FileResponse
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
    lab_result: str = Field(default='', max_length=5000)
    imaging_result: str = Field(default='', max_length=5000)
    other_result: str = Field(default='', max_length=5000)
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


RESULT_DIR = Path('uploads') / 'fasyankes_results'
RESULT_FIELDS = [('lab_result','Laboratorium'),('imaging_result','Radiologi / rontgen'),('other_result','Pemeriksaan lain')]

class ResultUpload(BaseModel):
    name: str = Field(min_length=1,max_length=255)
    data: str = Field(min_length=1,max_length=11200000)


def store_result(upload):
    from app.api.routes import _decode_bpjs_referral_document
    content,name,mime=_decode_bpjs_referral_document(upload.data,upload.name)
    RESULT_DIR.mkdir(parents=True,exist_ok=True)
    key=uuid4().hex
    (RESULT_DIR/key).write_bytes(content)
    return {'key':key,'name':name,'mime':mime}


def has_result(v):
    return bool(v and (any(v.get(k) for k,_ in RESULT_FIELDS) or v.get('result_file')))


def result_signature(c,v):
    secret=os.environ.get('SECRET_KEY','')
    if len(secret)<32 or secret=='dev-secret-key-change-me':
        raise HTTPException(503,'Konfigurasi tautan hasil belum tersedia')
    payload=['sehati:shared-result:v1',c.school_id,c.patient_id,c.id,v['id'],
             v.get('facility'),v.get('actual_date'),v.get('planned_date'),
             [v.get(k) for k,_ in RESULT_FIELDS],v.get('result_file')]
    return hmac.new(secret.encode(),json.dumps(payload,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()


def result_link(c,v):
    if not has_result(v):return None
    base=(os.getenv('PUBLIC_BASE_URL') or 'https://emruks.my.id').rstrip('/')
    return f'{base}/api/fasyankes/{c.id}/shared-result?'+urlencode({'visit_id':v['id'],'key':result_signature(c,v)})


def guardian_pdf_data(c,v,p):
    return dict(student=p.name, facility=v['facility'], status=v['status'],
                planned=v.get('planned_date'), time=v.get('planned_time'), actual=v.get('actual_date'),
                controls=v.get('needs_control'), next_date=v.get('next_date'), next_facility=v.get('next_facility'),
                instruction=v.get('guardian_instruction'), result_url=result_link(c,v))


def guardian_pdf_key(c,v,data):
    secret=os.getenv('SECRET_KEY','')
    if len(secret)<32:raise HTTPException(503,'Konfigurasi tautan PDF belum tersedia')
    payload=['sehati:guardian-pdf:v1',c.school_id,c.patient_id,c.id,v['id'],data]
    return hmac.new(secret.encode(),json.dumps(payload,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()


def guardian_pdf_link(c,v,p):
    base=(os.getenv('PUBLIC_BASE_URL') or 'https://emruks.my.id').rstrip('/')
    return f'{base}/api/fasyankes/{c.id}/wali-asuh.pdf?'+urlencode({'visit_id':v['id'],'key':guardian_pdf_key(c,v,guardian_pdf_data(c,v,p))})


@router.get('/{cid}/wali-asuh.pdf')
def guardian_pdf(cid:int,visit_id:str,key:str='',db:Session=Depends(get_db)):
    from app.reports.fasyankes_pdf import guardian_report
    missing=HTTPException(404,'Tautan PDF tidak berlaku')
    if len(key)!=64 or any(ch not in '0123456789abcdef' for ch in key):raise missing
    c=db.get(Case,cid)
    v=next((x for x in c.data['visits'] if x['id']==visit_id),None) if c else None
    if not v:raise missing
    data=guardian_pdf_data(c,v,db.get(PatientORM,c.patient_id))
    if not hmac.compare_digest(key,guardian_pdf_key(c,v,data)):raise missing
    response=pdf_response(guardian_report(data),'ringkasan-kunjungan-fasyankes.pdf')
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Robots-Tag']='noindex, nofollow, noarchive'
    return response


class Create(BaseModel):
    model_config = ConfigDict(extra='forbid')
    patient_id: str
    referral_id: int | None = None
    uks_visit_id: int | None = None
    visit: Visit
    result_upload: ResultUpload | None = None


class Change(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: int = Field(ge=1)
    visit: Visit
    result_upload: ResultUpload | None = None


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
        file=v.pop('result_file',None)
        if clinical and file:v['result_file_name']=file['name']
        if not clinical:
            for key,_ in RESULT_FIELDS:v.pop(key,None)
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
    if payload.result_upload:c.data['visits'][0]['result_file']=store_result(payload.result_upload)
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
    if c.version!=payload.version:raise HTTPException(409,'Catatan sudah berubah')
    if payload.result_upload:v['result_file']=store_result(payload.result_upload)
    elif old and old.get('result_file'):v['result_file']=old['result_file']
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
    deliveries=db.query(AuditLogORM).filter(AuditLogORM.school_id==c.school_id,AuditLogORM.entity_id==str(cid),AuditLogORM.action.in_(['fasyankes_wa_guardian','fasyankes_wa_group'])).order_by(AuditLogORM.id.desc()).limit(10).all()
    return {'deliveries':[{'target':x.action.removeprefix('fasyankes_wa_'),'status':x.details} for x in deliveries], 'whatsapp_enabled':bool(os.getenv('FONNTE_TOKEN')), 'version':c.version, 'guardian_phone_available':bool(p.parent_phone), 'group_available':bool(os.getenv('FONNTE_GROUP_ID')), 'group':group,'guardian':f"{p.name}: {status}. Tujuan: {v['facility']}. Rencana: {v['planned_date'] or 'Belum ditentukan'}. Aktual: {v['actual_date'] or 'Belum tercatat'}. Kontrol: {v['next_date'] or 'Belum dijadwalkan' if v['needs_control'] else 'Tidak dijadwalkan'}. {v['guardian_instruction']}\n\nUnduh PDF kunjungan (tanpa login):\n{guardian_pdf_link(c,v,p)}",'recipients':[{'name':db.get(UserORM,n.recipient_id).full_name,'read_at':n.read_at} for n in notices]}


class SendNotification(BaseModel):
    version: int = Field(ge=1)
    target: Literal['guardian', 'group']


@router.post('/{cid}/whatsapp')
def send_notification(cid:int, payload:SendNotification, db:Session=Depends(get_db), user:UserORM=Depends(require_roles(*WRITE))):
    from app.api.routes import send_whatsapp_message, normalize_whatsapp_number
    c=case_query(db,user).filter(Case.id==cid).with_for_update().first()
    if not c:raise HTTPException(404,'Kolaborasi tidak ditemukan')
    if c.version!=payload.version:raise HTTPException(409,'Catatan berubah. Buka ulang preview sebelum mengirim.')
    p=db.get(PatientORM,c.patient_id)
    if not os.getenv('FONNTE_TOKEN'):raise HTTPException(422,'Integrasi Fonnte belum dikonfigurasi')
    if payload.target=='group' and not os.getenv('FONNTE_GROUP_ID'):raise HTTPException(422,'Grup WhatsApp belum dikonfigurasi')
    if payload.target=='guardian' and not normalize_whatsapp_number(p.parent_phone):raise HTTPException(422,'Nomor WhatsApp wali asuh pada data siswa belum valid')
    action='fasyankes_wa_'+payload.target
    prefix=f'{c.version}:'
    logs=db.query(AuditLogORM).filter(AuditLogORM.school_id==c.school_id,AuditLogORM.action==action,AuditLogORM.entity_id==str(cid)).all()
    if any((log.details or '').startswith(prefix) for log in logs):
        raise HTTPException(409,'Versi ini sudah diajukan ke WhatsApp. Periksa status pengiriman sebelum mengirim lagi.')
    contents=preview(cid,db,user)
    log=AuditLogORM(school_id=c.school_id,user_id=user.id,username=user.username,action=action,entity_type='fasyankes_case',entity_id=str(cid),details=prefix+'requested')
    db.add(log);db.commit()  # Reserve before network I/O; uncertain deliveries must not be duplicated.
    try:
        status,_=send_whatsapp_message(p.parent_phone,contents[payload.target],group=payload.target=='group')
    except Exception:
        status='unknown'
    # Provider/network failures can have an uncertain outcome: require checking provider before retry.
    log.details=prefix+status;db.commit()
    labels={'sent':'Pesan diterima layanan WhatsApp; belum berarti sudah dibaca.', 'queued':'Pesan masuk antrean WhatsApp.', 'failed':'Pengiriman gagal. Periksa log Fonnte sebelum mencoba lagi.', 'skipped':'Pesan belum dikirim. Periksa konfigurasi dan nomor tujuan.', 'unknown':'Status belum dapat dipastikan. Periksa Fonnte sebelum mengirim lagi.'}
    return {'status':status,'message':labels.get(status,labels['unknown'])}


@router.get('/{cid}/supporting-result')
def supporting_result(cid:int,visit_id:str,attachment:bool=False,db:Session=Depends(get_db),user:UserORM=Depends(require_roles(*WRITE))):
    c=owned(db,user,cid)
    v=next((x for x in c.data['visits'] if x['id']==visit_id),None)
    if not has_result(v):raise HTTPException(404,'Hasil pemeriksaan belum tersedia')
    return render_supporting_result(db,c,v,attachment)


@router.get('/{cid}/shared-result')
def shared_result(cid:int,visit_id:str,key:str='',attachment:bool=False,db:Session=Depends(get_db)):
    missing=HTTPException(404,'Tautan hasil tidak berlaku')
    if len(key)!=64 or any(ch not in '0123456789abcdef' for ch in key):raise missing
    c=db.get(Case,cid)
    v=next((x for x in c.data['visits'] if x['id']==visit_id),None) if c else None
    if not has_result(v) or not hmac.compare_digest(key,result_signature(c,v)):raise missing
    return render_supporting_result(db,c,v,attachment,key)


def render_supporting_result(db,c,v,attachment,key=None):
    headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex, nofollow, noarchive'}
    file=v.get('result_file')
    if attachment:
        if not file or not (RESULT_DIR/file['key']).is_file():raise HTTPException(404,'Lampiran tidak ditemukan')
        return FileResponse(RESULT_DIR/file['key'],filename=file['name'],media_type=file['mime'],headers=headers)
    sections=''.join('<h2>'+label+'</h2><p>'+escape(v[key])+'</p>' for key,label in RESULT_FIELDS if v.get(key))
    if file:
        query=escape(urlencode({'visit_id':v['id'],'attachment':'true',**({'key':key} if key else {})}))
        sections+=f'<h2>Lampiran</h2><a href="?{query}">Unduh {escape(file["name"])}</a>'
    title='Hasil pemeriksaan penunjang'
    patient=db.get(PatientORM,c.patient_id)
    return HTMLResponse(f'<!doctype html><html lang="id"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{title} · SEHATI</title><style>body{{max-width:48rem;margin:auto;padding:2rem;font:1rem/1.6 system-ui;color:#312e59}}h2{{font-size:1.1rem}}p{{white-space:pre-wrap;overflow-wrap:anywhere}}</style><main><small>SEHATI · Kolaborasi Fasyankes</small><h1>{title}</h1><p>{escape(patient.name)} · {escape(v["facility"])} · {escape(v.get("actual_date") or v.get("planned_date") or "Tanggal belum diisi")}</p>{sections}</main></html>',headers=headers)


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
            row.update(result_url=result_link(c,v),patient_id=patient.id,patient_name=patient.name,class_name=patient.class_name)
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
        rows.extend(dict(result_url=result_link(c,v),case_id=c.id,version=c.version,referral_number=ref.referral_number if ref else None,visit=deepcopy(v)) for v in c.data['visits'])
    rows.sort(key=lambda r:(r['visit']['actual_date'] or r['visit']['planned_date'] or '9999',r['case_id']))
    content=build_report(school_name=school.school_name if school else 'Sekolah',school_address=school.address if school else '',author=user.full_name,rows=rows,patient={'id':patient.id,'name':patient.name,'class_name':patient.class_name})
    return pdf_response(content,'riwayat-individual-fasyankes.pdf')
