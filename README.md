# EMR UKS Sekolah Rakyat + Expert System (NANDA, NIC, NOC)

Prototype backend EMR keperawatan dengan expert system berbasis aturan (rule-based).

## Fitur awal
- Input asesmen keperawatan pasien
- Inferensi diagnosis keperawatan mengacu NANDA
- Rekomendasi intervensi (NIC) dan luaran (NOC)
- API sederhana berbasis FastAPI
- Penyimpanan data EMR ke database (default SQLite lokal)
- Autentikasi JWT + role (`admin`, `perawat`)

## Database
Default: SQLite lokal di file `emr_keperawatan.db`.

Opsional PostgreSQL via environment variable:
```powershell
$env:DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/emr_keperawatan"
```

## Migrasi SQLite ke PostgreSQL Railway
1. Ambil `DATABASE_URL` PostgreSQL dari Railway.
2. Jalankan migrasi. Script akan membuat backup SQLite otomatis sebelum copy data:
```powershell
$env:DATABASE_URL="postgresql://USER:PASSWORD@HOST:PORT/DB"
.\.venv\Scripts\python.exe .\scripts\migrate_sqlite_to_postgres.py
```
3. Jika database Railway sudah berisi data dan ingin diganti dengan isi SQLite lokal:
```powershell
.\.venv\Scripts\python.exe .\scripts\migrate_sqlite_to_postgres.py --replace
```
4. Setelah migrasi selesai, jalankan aplikasi dengan `DATABASE_URL` yang sama agar API memakai PostgreSQL Railway.

## Jalankan
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Buka Swagger UI:
- http://127.0.0.1:8000/docs

Buka UI minimum UKS Sekolah Rakyat:
- http://127.0.0.1:8000/ui

## Akun default
- username: `admin`
- password: `admin123`

Segera ganti password untuk environment produksi.

## Alur Auth di Swagger
1. `POST /api/auth/login`
2. Copy `access_token` dari response
3. Klik tombol **Authorize** di Swagger
4. Isi: `Bearer <access_token>`
5. Jalankan endpoint klinis (`/api/assessment`, `/api/patients`, dll)

## Endpoint Auth
- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me`

## Endpoint EMR
- `GET /health`
- `POST /api/patients`
- `POST /api/assessment`
- `GET /api/patients`
- `GET /api/patients/search?q=...`
- `GET /api/patients/{patient_id}`
- `POST /api/uks/visits`
- `GET /api/uks/visits/{visit_id}`
- `POST /api/uks/visits/{visit_id}/medications`
- `GET /api/uks/visits/{visit_id}/medications`
- `POST /api/medicines`
- `GET /api/medicines`
- `PATCH /api/medicines/{medicine_id}`
- `PATCH /api/uks/visits/{visit_id}/referral`
- `GET /api/patients/{patient_id}/uks-visits`
- `GET /api/reports/uks/daily?date=YYYY-MM-DD`
- `GET /api/reports/uks/daily/excel?date=YYYY-MM-DD`
- `GET /api/reports/uks/monthly?month=YYYY-MM`
- `GET /api/patients/{patient_id}/assessments`
- `GET /api/assessments/{assessment_id}`

## Import Stok Obat dari Excel
1. Export Google Sheet stok obat menjadi file `.xlsx`.
2. Pastikan header minimal punya kolom `Nama Obat` dan `Stok`.
3. Jalankan:
```powershell
.\.venv\Scripts\python.exe .\import_medicines.py "C:\path\stok_obat.xlsx"
```
Opsional jika nama sheet spesifik:
```powershell
.\.venv\Scripts\python.exe .\import_medicines.py "C:\path\stok_obat.xlsx" --sheet "Sheet1"
```

## Catatan penting klinis
- Prototype ini untuk dukungan keputusan awal, bukan pengganti clinical judgment.
- Katalog NANDA-NIC-NOC pada `data/nanda_nic_noc.json` masih contoh awal dan perlu validasi perawat klinis.

## Backup SQLite
Jalankan backup manual kapan saja:
```powershell
.\backup_db.ps1
```

Opsional path custom:
```powershell
.\backup_db.ps1 -DatabasePath "emr_keperawatan.db" -BackupDir "backups"
```

## Dokumen Operasional
- Panduan 1 halaman: `docs/OPERASIONAL_UKS.md`
- Checklist UAT: `docs/UAT_CHECKLIST_UKS.md`

## Jalankan Tanpa PowerShell Terbuka
Mode background manual:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_server.ps1
```

Stop server background:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop_server.ps1
```

Auto-start saat login Windows (Task Scheduler):
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_startup_task.ps1
```

Hapus auto-start:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall_startup_task.ps1
```

