"""Local review server with synthetic data only. Never loads production database."""
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.chdir(ROOT)
database=ROOT/'tmp'/'fasyankes-preview.db'
database.parent.mkdir(exist_ok=True)
os.environ.update(DATABASE_URL='sqlite:///'+database.as_posix(), SECRET_KEY='preview-local-only-sehati-fasyankes-2026',
                  ENVIRONMENT='development',SESSION_COOKIE_SECURE='false',FONNTE_TOKEN='',FONNTE_GROUP_ID='',
                  ADMIN_USERNAME='demo.admin',ADMIN_PASSWORD='DemoSehati2026!',DISABLE_DEFAULT_ADMIN='false')
from app.main import app
from app.db.database import SessionLocal
from app.db.models import PatientORM,UserORM,GuardianStudentAssignmentORM
from app.auth.security import hash_password
from app.api.fasyankes import create, Create, Visit
from app.db.fasyankes import FasyankesCaseORM

with SessionLocal() as db:
    admin=db.query(UserORM).filter_by(username='demo.admin').one()
    for username,role,name in [('demo.perawat','perawat','Perawat Demo'),('demo.walsuh','wali_asuh','Wali Asuh Demo'),('demo.kepala','kepala_sekolah','Kepala Sekolah Demo')]:
        if not db.query(UserORM).filter_by(username=username).first():
            db.add(UserORM(username=username,role=role,full_name=name,school_id=admin.school_id,password_hash=hash_password('DemoSehati2026!'),is_active=True))
    if not db.get(PatientORM,'DEMO-FASY-01'):
        db.add(PatientORM(id='DEMO-FASY-01',name='Siswa Contoh (Data Fiktif)',age=15,gender='P',class_name='X A',school_id=admin.school_id))
    db.commit()
    wali=db.query(UserORM).filter_by(username='demo.walsuh').one()
    if not db.query(GuardianStudentAssignmentORM).filter_by(guardian_id=wali.id,patient_id='DEMO-FASY-01').first():
        db.add(GuardianStudentAssignmentORM(guardian_id=wali.id,patient_id='DEMO-FASY-01',school_id=admin.school_id));db.commit()
    if not db.query(FasyankesCaseORM).first():
        create(Create(patient_id='DEMO-FASY-01',visit=Visit(id='demo-first',facility='Puskesmas Contoh',status='TINDAK_LANJUT',actual_date='2026-10-30',doctor='dr. Contoh',companion='Wali Asuh Demo',result='Contoh hasil pemeriksaan untuk uji aplikasi.',follow_up='Pantau kondisi dan koordinasikan kontrol.',guardian_instruction='Dampingi siswa sesuai arahan perawat.',responsible='Perawat Demo',needs_control=True,next_date='2026-11-07')),db,admin)

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8127)
