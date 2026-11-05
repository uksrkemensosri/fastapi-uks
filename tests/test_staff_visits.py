from datetime import datetime
from zoneinfo import ZoneInfo
from app.db.database import SessionLocal
from app.db.models import UserORM, SchoolORM, MedicineInventoryORM
from app.auth.security import hash_password


def test_staff_visit_scope_counts_stock_and_recipient(client,monkeypatch):
    def login(name):
        r=client.post('/api/auth/login',json={'username':name,'password':'admin123'})
        return {'Authorization':'Bearer '+r.json()['access_token']}
    h=login('admin')
    def stats():return client.get('/api/dashboard/stats',headers=h).json()
    before=stats();calls=[]
    monkeypatch.setattr('app.api.staff.send_whatsapp_message',lambda phone,msg:(calls.append((phone,msg)) or ('queued','ok')))
    with SessionLocal() as db:
        school=db.query(UserORM).filter_by(username='admin').one().school_id
        other=SchoolORM(school_code='STAFF-OTHER',school_name='Sekolah lain');db.add(other);db.flush()
        for name,role,sid in [('staff_guard','wali_asuh',school),('staff_other','perawat',other.id)]:
            db.add(UserORM(username=name,full_name=name,role=role,school_id=sid,password_hash=hash_password('admin123'),is_active=True))
        db.add(MedicineInventoryORM(school_id=school,name='Obat Uji Tendik',stock=2));db.commit()
    r=client.post('/api/staff',headers=h,json={'name':'Indah Contoh','position':'Perawat','phone':'081234567890'})
    assert r.status_code==201,r.text
    url='/api/staff/'+str(r.json()['id'])+'/visits'
    payload={'visit_date':datetime.now(ZoneInfo('Asia/Jakarta')).date().isoformat(),'complaint':'Pusing','examination':'Hasil contoh','advice':'Anjuran contoh','notes':'Privat internal','medications':[{'medicine_name':'Obat Uji Tendik','quantity':3,'dosage':'Contoh'}]}
    assert client.post(url,headers=h,json=payload).status_code==409
    assert not client.get(url,headers=h).json() and not calls
    payload['medications'][0]['quantity']=1
    assert client.post(url,headers=h,json=payload).status_code==201
    assert len(calls)==1 and calls[0][0]=='081234567890'
    assert all(x in calls[0][1] for x in ['Hai Indah Contoh','Hasil contoh','Anjuran contoh','Obat Uji Tendik'])
    assert 'Privat internal' not in calls[0][1]
    after=stats()
    assert after['total_students']==before['total_students']
    assert after['total_staff']==before['total_staff']+1
    assert after['today_student_visits']==before['today_student_visits']
    assert after['today_visits']==before['today_visits']+1
    assert client.get(url,headers=h).json()[0]['notes']=='Privat internal'
    assert client.get('/api/staff/visits',headers=h).json()[0]['kind']=='staff'
    with SessionLocal() as db:assert db.query(MedicineInventoryORM).filter_by(name='Obat Uji Tendik').one().stock==1
    for name,status in [('staff_guard',403),('staff_other',404)]:
        restricted=login(name)
        assert client.get(url,headers=restricted).status_code==status
        assert client.post(url,headers=restricted,json=payload).status_code==status
