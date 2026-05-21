# Panduan Operasional UKS (1 Halaman)

## 1) Start Aplikasi
1. Buka terminal di folder project.
2. Aktifkan venv: `\.venv\Scripts\Activate.ps1`
3. Jalankan server: `python -m uvicorn app.main:app --reload`
4. Buka Swagger: `http://127.0.0.1:8000/docs`

## 2) Login
1. Jalankan `POST /api/auth/login`.
2. Copy `access_token`.
3. Klik `Authorize`, isi: `Bearer <access_token>`.

## 3) Input Data Harian UKS
1. Buat siswa baru (jika belum ada): `POST /api/patients`
2. Catat kunjungan: `POST /api/uks/visits`
3. Tambah obat (jika ada): `POST /api/uks/visits/{visit_id}/medications`
4. Update rujukan (jika perlu): `PATCH /api/uks/visits/{visit_id}/referral`

## 4) Lihat Riwayat
1. Riwayat kunjungan siswa: `GET /api/patients/{patient_id}/uks-visits`
2. Detail kunjungan: `GET /api/uks/visits/{visit_id}`
3. Obat pada kunjungan: `GET /api/uks/visits/{visit_id}/medications`

## 5) Laporan
1. Laporan harian: `GET /api/reports/uks/daily?date=YYYY-MM-DD`
2. Laporan bulanan: `GET /api/reports/uks/monthly?month=YYYY-MM`

## 6) Backup Data
1. Jalankan: `\.\backup_db.ps1`
2. File backup ada di folder `backups\`.

## 7) Troubleshooting Cepat
1. `401 Invalid token`: login ulang, lalu Authorize ulang.
2. `400 Date format`: cek format tanggal report.
3. Server tidak jalan: pastikan venv aktif dan port 8000 tidak dipakai proses lain.
