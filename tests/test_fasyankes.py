import base64
import pytest
from datetime import date
from app.db.database import SessionLocal
from app.db.models import UserORM, SchoolORM, GuardianStudentAssignmentORM
from app.auth.security import hash_password


def login(client, name='admin'):
    r=client.post('/api/auth/login',json={'username':name,'password':'admin123'})
    assert r.status_code==200,r.text
    return {'Authorization':'Bearer '+r.json()['access_token']}


@pytest.fixture(scope="module", autouse=True)
def fasy_setup(client):
    admin=login(client)
    r=client.post('/api/patients',headers=admin,json={'id':'FASY-01','name':'Siswa Kolaborasi','age':15,'gender':'P','class_name':'X A'})
    assert r.status_code==201,r.text
    with SessionLocal() as db:
        owner=db.query(UserORM).filter_by(username='admin').one()
        other=SchoolORM(school_code='FASY-OTHER',school_name='Other school');db.add(other);db.flush()
        for name,role,school in [('fasy_guardian','wali_asuh',owner.school_id),('fasy_head','kepala_sekolah',owner.school_id),('fasy_stranger','wali_asuh',owner.school_id),('fasy_other','perawat',other.id)]:
            u=UserORM(username=name,full_name=name,role=role,school_id=school,password_hash=hash_password('admin123'),is_active=True);db.add(u);db.flush()
            if name=='fasy_guardian':db.add(GuardianStudentAssignmentORM(school_id=school,guardian_id=u.id,patient_id='FASY-01'))
        db.commit()


def test_collaboration_full_flow_and_permissions(client):
    admin=login(client)
    guardian=login(client,'fasy_guardian');head=login(client,'fasy_head');stranger=login(client,'fasy_stranger');other=login(client,'fasy_other')
    v={'id':'first','facility':'Puskesmas A','status':'TINDAK_LANJUT','actual_date':'2026-01-01','doctor':'dr. Contoh','result':'Hasil privat','diagnosis':'Diagnosis privat','therapy':'Obat privat','guardian_instruction':'Dampingi istirahat','needs_control':True,'next_date':'2026-01-08','responsible':'Perawat SR'}
    created=client.post('/api/fasyankes',headers=admin,json={'patient_id':'FASY-01','visit':v})
    assert created.status_code==201,created.text
    c=created.json();cid=c['id'];assert c['version']==1
    schedule=client.get('/api/fasyankes/schedule',headers=admin).json()
    assert any(x['case_id']==cid and x['date']=='2026-01-08' for x in schedule)
    for headers in [guardian,head]:
        visible=next(x for x in client.get('/api/fasyankes',headers=headers).json() if x['id']==cid)
        assert not {'diagnosis','result','therapy','reason','follow_up'} & visible['visits'][0].keys()
        assert client.put(f'/api/fasyankes/{cid}/visit',headers=headers,json={'version':1,'visit':v}).status_code==403
    for headers in [other,stranger]:
        assert not client.get('/api/fasyankes',headers=headers).json()
        assert client.get(f'/api/fasyankes/{cid}/history',headers=headers).status_code==404
    inbox=client.get('/api/fasyankes/notices/inbox',headers=guardian).json()
    notice=next(n for n in inbox if n['case_id']==cid)
    assert client.post(f"/api/fasyankes/notices/{notice['id']}/read",headers=stranger).status_code==404
    assert client.post(f"/api/fasyankes/notices/{notice['id']}/read",headers=guardian).status_code==200
    preview=client.get(f'/api/fasyankes/{cid}/notification-preview',headers=admin).json()
    assert preview['whatsapp_enabled'] is False
    assert 'Siswa Kolaborasi' not in preview['group'] and 'Diagnosis privat' not in preview['group']
    assert preview['recipients'][0]['read_at']
    invalid={**v,'status':'DIBATALKAN'}
    assert client.put(f'/api/fasyankes/{cid}/visit',headers=admin,json={'version':1,'visit':invalid}).status_code==422
    v['planned_date']='2026-01-01';v['doctor']='dr. Baru'
    updated=client.put(f'/api/fasyankes/{cid}/visit',headers=admin,json={'version':1,'visit':v})
    assert updated.status_code==200,updated.text
    assert client.put(f'/api/fasyankes/{cid}/visit',headers=admin,json={'version':1,'visit':v}).status_code==409
    undone=client.post(f'/api/fasyankes/{cid}/undo',headers=admin,json={'version':2})
    assert undone.status_code==200
    assert undone.json()['visits'][0]['doctor']=='dr. Contoh'
    control={'id':'second','facility':'Puskesmas A','status':'SELESAI','actual_date':'2026-01-08','result':'Kontrol selesai','parent_visit_id':'first'}
    r=client.put(f'/api/fasyankes/{cid}/visit',headers=admin,json={'version':3,'visit':control})
    assert r.status_code==200,r.text
    assert len(r.json()['visits'])==2
    assert not any(x['case_id']==cid for x in client.get('/api/fasyankes/schedule',headers=admin).json())
    # Cancellation preserves history and restores the outstanding source control.
    control.update(status='DIBATALKAN',cancel_reason='Salah input')
    r=client.put(f'/api/fasyankes/{cid}/visit',headers=admin,json={'version':4,'visit':control})
    assert r.status_code==200,r.text
    assert any(x['case_id']==cid for x in client.get('/api/fasyankes/schedule',headers=admin).json())
    assert len(client.get(f'/api/fasyankes/{cid}/history',headers=admin).json())==5


def test_bpjs_auto_integration_and_input_validation(client):
    admin=login(client)
    referral=client.post('/api/bpjs-referrals',headers=admin,json={'patient_id':'FASY-01','referral_date':'2026-01-01','control_date':'2026-01-08','referring_facility':'Puskesmas A','destination_facility':'RS B','document_name':'referral.pdf','document_base64':base64.b64encode(b'%PDF-1.4\nexample').decode()})
    assert referral.status_code==201,referral.text
    rid=referral.json()['id']
    cs=client.get('/api/fasyankes',headers=admin).json()
    c=next(c for c in cs if c['referral_id']==rid)
    assert c['visits'][0]['status']=='TERJADWAL'
    again=client.post(f'/api/fasyankes/from-referral/{rid}',headers=admin)
    assert again.json()['id']==c['id']
    assert len([x for x in client.get('/api/fasyankes',headers=admin).json() if x['referral_id']==rid])==1
    visit=c['visits'][0]
    visit.update(actual_date='2026-01-08',status='TINDAK_LANJUT',result='Hasil pemeriksaan',needs_control=True,next_date='2026-01-15')
    updated=client.put(f"/api/fasyankes/{c['id']}/visit",headers=admin,json={'version':1,'visit':visit})
    assert updated.status_code==200,updated.text
    records=client.get('/api/patients/FASY-01/bpjs-referrals',headers=admin).json()
    linked=next(x for x in records if x['id']==rid)
    assert linked['control_date']=='2026-01-15' and linked['control_done'] is False
    for bad in [{'status':'SELESAI'},{'status':'TERJADWAL'},{'status':'DIBATALKAN'},{'actual_date':'2099-01-01'}]:
        r=client.post('/api/fasyankes',headers=admin,json={'patient_id':'FASY-01','visit':{'id':'bad','facility':'Puskesmas',**bad}})
        assert r.status_code==422,r.text
    other=login(client,'fasy_other')
    assert client.post(f'/api/fasyankes/from-referral/{rid}',headers=other).status_code==404


def test_page_available(client):
    login(client)
    r=client.get('/kolaborasi-fasyankes')
    assert r.status_code==200
    assert 'WhatsApp dan pengiriman grup belum diaktifkan' in r.text


def test_additive_migration_preserves_existing_tables():
    import importlib.util
    from sqlalchemy import create_engine, inspect, text
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.db.database import Base
    spec=importlib.util.spec_from_file_location('fasy_migration','alembic/versions/20261031_0011_fasyankes.py')
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=create_engine('sqlite://')
    legacy=[t for t in Base.metadata.sorted_tables if not t.name.startswith('fasyankes_')]
    Base.metadata.create_all(engine,tables=legacy)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO schools (id, school_code, school_name, is_active) VALUES (1, 'KEPT', 'Preserved school', 1)"))
        migration.op=Operations(MigrationContext.configure(conn))
        migration.upgrade();migration.upgrade()
        assert conn.execute(text('SELECT school_name FROM schools WHERE id=1')).scalar()=='Preserved school'
        assert {'fasyankes_cases','fasyankes_revisions','fasyankes_notifications'} <= set(inspect(conn).get_table_names())
        with pytest.raises(RuntimeError):migration.downgrade()
    engine.dispose()


def test_pdf_reports_scope_period_and_privacy(client,monkeypatch):
    from app.reports import fasyankes_pdf
    captured=[]
    original=fasyankes_pdf.build_report
    def capture(**kwargs):
        captured.append(kwargs)
        return original(**kwargs)
    monkeypatch.setattr(fasyankes_pdf,'build_report',capture)
    admin=login(client)
    payload={'patient_id':'FASY-01','visit':{'id':'pdf-check','facility':'Puskesmas PDF','status':'SELESAI','actual_date':'2026-02-10','result':'PRIVATE_RESULT','diagnosis':'PRIVATE_DIAGNOSIS','therapy':'PRIVATE_MEDICINE','follow_up':'PRIVATE_PLAN'}}
    assert client.post('/api/fasyankes',headers=admin,json=payload).status_code==201
    head=login(client,'fasy_head')
    result=client.get('/api/fasyankes/reports/summary.pdf?start=2026-02-01&end=2026-02-28',headers=head)
    assert result.status_code==200,result.text[:200]
    assert result.content.startswith(b'%PDF-')
    assert result.headers['cache-control']=='no-store'
    assert result.headers['content-disposition'].startswith('attachment;')
    rows=captured[-1]['rows']
    assert len(rows)==1 and rows[0]['facility']=='Puskesmas PDF'
    assert not {'diagnosis','result','therapy','follow_up','guardian_instruction','reason'} & rows[0].keys()
    assert client.get('/api/fasyankes/reports/summary.pdf?start=2026-02-28&end=2026-02-01',headers=head).status_code==422
    assert client.get('/api/fasyankes/reports/summary.pdf?start=2020-01-01&end=2026-02-01',headers=head).status_code==422
    assert client.get('/api/fasyankes/reports/summary.pdf?start=2026-02-01&end=2026-02-28&school_id=9999',headers=head).status_code==403
    empty=client.get('/api/fasyankes/reports/summary.pdf?start=2020-01-01&end=2020-01-02',headers=head)
    assert empty.status_code==200 and captured[-1]['rows']==[]
    assert client.get('/api/fasyankes/reports/student/FASY-01.pdf',headers=head).status_code==403
    individual=client.get('/api/fasyankes/reports/student/FASY-01.pdf',headers=admin)
    assert individual.status_code==200 and individual.content.startswith(b'%PDF-')
    assert any(r['visit'].get('diagnosis')=='PRIVATE_DIAGNOSIS' for r in captured[-1]['rows'])
    guardian=login(client,'fasy_guardian')
    assert client.get('/api/fasyankes/reports/student/FASY-01.pdf',headers=guardian).status_code==403
    assert client.get('/api/fasyankes/reports/summary.pdf?start=2026-02-01&end=2026-02-28',headers=guardian).status_code==403
    other=login(client,'fasy_other')
    assert client.get('/api/fasyankes/reports/student/FASY-01.pdf',headers=other).status_code==404
    assert client.get('/api/fasyankes/reports/summary.pdf?start=2026-02-01&end=2026-02-28',headers=other).status_code==200
    assert captured[-1]['rows']==[]


def test_pdf_long_text_escapes_markup_and_paginates():
    from app.reports.fasyankes_pdf import build_report
    from app.api.fasyankes import Visit
    v=Visit(id='long',facility='Puskesmas <Contoh> & Klinik',status='SELESAI',actual_date='2026-01-01',result=('Hasil <b>bukan markup</b> & penjelasan. '*110),obstacle='Koordinasi pendamping. '*40).model_dump(mode='json')
    pdf=build_report(school_name='Sekolah & Contoh',school_address='',author='Perawat <Demo>',rows=[{'case_id':1,'version':1,'visit':v}],patient={'id':'DEMO','name':'Data Fiktif','class_name':'X'})
    assert pdf.startswith(b'%PDF-')
