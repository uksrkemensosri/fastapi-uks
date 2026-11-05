from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, update
from sqlalchemy.orm import Session
from app.auth.dependencies import require_roles
from app.auth.tenant import tenant_get, tenant_query, require_user_school
from app.db.dependencies import get_db
from app.db.staff import StaffORM, StaffVisitORM
from app.db.models import MedicineInventoryORM, MedicineTransactionORM, SchoolORM
from app.models.schemas import UKSMedicationCreate
from app.api.routes import send_whatsapp_message, write_audit_log

router = APIRouter(prefix='/api/staff', tags=['Tendik'])
clinical = Depends(require_roles('admin','perawat'))


class StaffInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1,max_length=200)
    position: str = Field(min_length=1,max_length=120)
    phone: str = Field(default='',pattern=r'^$|^\+?[0-9]{10,15}$')
    school_id: int | None = None


class VisitInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    visit_date: date
    complaint: str = Field(min_length=1,max_length=3000)
    examination: str = Field(default='',max_length=5000)
    diagnosis: str = Field(default='',max_length=2000)
    treatment: str = Field(default='',max_length=3000)
    advice: str = Field(default='',max_length=3000)
    notes: str = Field(default='',max_length=3000)
    medications: list[UKSMedicationCreate] = Field(default_factory=list,max_length=50)


def staff_visit_message(name: str, visit: VisitInput) -> str:
    months = 'Januari Februari Maret April Mei Juni Juli Agustus September Oktober November Desember'.split()
    day = visit.visit_date
    sections = [
        '🏥 *EMR UKS – Sekolah Rakyat*',
        f'Hai {name}, terima kasih sudah berkunjung ke UKS. Berikut ringkasan pemeriksaanmu.',
        f'📅 *Tanggal kunjungan*\n{day.day} {months[day.month-1]} {day.year}',
    ]
    meds = '\n'.join(f'• {m.medicine_name} — {m.dosage}' for m in visit.medications)
    for label, value in [('💬 Keluhan', visit.complaint), ('🩺 Hasil pemeriksaan', visit.examination),
                         ('🩹 Tindakan', visit.treatment), ('💊 Obat', meds), ('📌 Anjuran', visit.advice)]:
        if value:
            icon, title = label.split(' ', 1)
            sections.append(f'{icon} *{title}*\n{value}')
    sections.extend(['Semoga lekas membaik, ' + name + '.', '━━━━━━━━━━━━━━━━━━\n*Tim UKS Sekolah Rakyat*\nKementerian Sosial RI'])
    return '\n\n'.join(sections)


def identity(s):
    return dict(id=s.id,name=s.name,position=s.position,school_id=s.school_id,phone=s.phone)


@router.get('')
def directory(db:Session=Depends(get_db),user=clinical):
    return [identity(s) for s in tenant_query(db.query(StaffORM),StaffORM,user).order_by(StaffORM.name,StaffORM.id).all()]


@router.post('',status_code=201)
def register(payload:StaffInput,db:Session=Depends(get_db),user=clinical):
    sid=payload.school_id if user.role=='super_admin' and payload.school_id else require_user_school(user)
    if not db.get(SchoolORM,sid):raise HTTPException(404,'Sekolah tidak ditemukan')
    if payload.school_id and payload.school_id!=sid:raise HTTPException(403,'Sekolah tidak sesuai akses')
    s=StaffORM(school_id=sid,name=payload.name,position=payload.position,phone=payload.phone)
    db.add(s);db.flush();write_audit_log(db,user,'create_staff','staff',s.id,'Registrasi tendik');db.commit()
    return identity(s)


def get_staff(db,user,staff_id):
    s=tenant_get(db,StaffORM,staff_id,user)
    if not s:raise HTTPException(404,'Tendik tidak ditemukan')
    return s


@router.get('/visits')
def visit_list(month:str|None=Query(default=None,pattern=r'^\d{4}-(0[1-9]|1[0-2])$'),db:Session=Depends(get_db),user=clinical):
    q=tenant_query(db.query(StaffVisitORM,StaffORM).join(StaffORM,StaffORM.id==StaffVisitORM.staff_id),StaffVisitORM,user)
    if month:q=q.filter(StaffVisitORM.visit_date.startswith(month+'-'))
    return [dict(kind='staff',id=v.id,staff_id=s.id,patient_name=s.name,visit_date=v.visit_date,
                 complaint=v.record['complaint'],diagnosis=v.record['diagnosis'],treatment=v.record['treatment'])
            for v,s in q.order_by(StaffVisitORM.visit_date.desc(),StaffVisitORM.id.desc())]


@router.get('/{staff_id}/visits')
def history(staff_id:int,db:Session=Depends(get_db),user=clinical):
    s=get_staff(db,user,staff_id)
    rows=db.query(StaffVisitORM).filter_by(staff_id=s.id,school_id=s.school_id).order_by(StaffVisitORM.visit_date.desc(),StaffVisitORM.id.desc())
    return [dict(id=v.id,visit_date=v.visit_date,**v.record,whatsapp_status=v.whatsapp_status) for v in rows]


@router.post('/{staff_id}/visits',status_code=201)
def visit(staff_id:int,payload:VisitInput,db:Session=Depends(get_db),user=clinical):
    s=get_staff(db,user,staff_id)
    record=payload.model_dump(mode='json',exclude={'visit_date'})
    v=StaffVisitORM(school_id=s.school_id,staff_id=s.id,actor_id=user.id,visit_date=payload.visit_date.isoformat(),record=record,whatsapp_status='skipped')
    db.add(v);db.flush()
    for m in sorted(payload.medications,key=lambda m:m.medicine_name.lower()):
        inventory=db.query(MedicineInventoryORM).filter(MedicineInventoryORM.school_id==s.school_id,func.lower(MedicineInventoryORM.name)==m.medicine_name.strip().lower()).first()
        if not inventory:raise HTTPException(422,'Obat tidak ditemukan di sekolah ini')
        result=db.execute(update(MedicineInventoryORM).where(MedicineInventoryORM.id==inventory.id,MedicineInventoryORM.stock>=m.quantity).values(stock=MedicineInventoryORM.stock-m.quantity))
        if result.rowcount!=1:raise HTTPException(409,'Stok obat tidak cukup: '+inventory.name)
        db.add(MedicineTransactionORM(school_id=s.school_id,medicine_name=inventory.name,transaction_type='OUT',quantity=m.quantity,notes=f'Kunjungan tendik #{v.id}'))
    write_audit_log(db,user,'create_staff_visit','staff_visit',v.id,'Kunjungan UKS tendik')
    db.commit()
    status='skipped'
    if s.phone:
        status,_=send_whatsapp_message(s.phone,staff_visit_message(s.name,payload))
        v.whatsapp_status=status;db.commit()
    return {'id':v.id,'whatsapp_status':status}
