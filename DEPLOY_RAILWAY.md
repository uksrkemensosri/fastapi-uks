# Deploy EMR UKS ke Railway

Panduan ini memakai konfigurasi `railway.json`, `Dockerfile`, dan `Procfile` yang sudah ada di repo.

## 1. Buat Project Railway

1. Buka Railway.
2. Pilih **New Project**.
3. Pilih **Deploy from GitHub repo**.
4. Pilih repo aplikasi EMR UKS.
5. Tambahkan service **PostgreSQL** di project yang sama.

## 2. Environment Variables

Di service aplikasi, buka **Variables**, lalu tambahkan:

```env
SECRET_KEY=isi-dengan-random-panjang-minimal-32-karakter
SESSION_COOKIE_SECURE=true
ACCESS_TOKEN_EXPIRE_SECONDS=3600
FONNTE_TOKEN=
FONNTE_API_URL=https://api.fonnte.com/send
```

Railway biasanya menyediakan `DATABASE_URL` otomatis dari service PostgreSQL. Pastikan variable `DATABASE_URL` ada di service aplikasi.

## 3. Start Command

Repo ini sudah punya `railway.json`:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Jadi tidak perlu isi start command manual, kecuali Railway meminta. Jika diminta, pakai command di atas.

## 4. Migrasi Data Lokal ke PostgreSQL Railway

Kalau ingin membawa data lokal dari `emr_keperawatan.db` ke database Railway:

```powershell
$env:DATABASE_URL="postgresql://USER:PASSWORD@HOST:PORT/DB"
.\.venv\Scripts\python.exe .\scripts\migrate_sqlite_to_postgres.py
```

Jika database Railway sudah berisi data dan ingin diganti dengan data lokal:

```powershell
$env:DATABASE_URL="postgresql://USER:PASSWORD@HOST:PORT/DB"
.\.venv\Scripts\python.exe .\scripts\migrate_sqlite_to_postgres.py --replace
```

Ambil nilai `DATABASE_URL` dari tab **Variables** service PostgreSQL Railway.

## 5. Cek Setelah Deploy

Setelah Railway selesai deploy:

1. Buka domain Railway.
2. Cek:

```text
https://domain-railway-kamu.up.railway.app/health
```

Harus muncul:

```json
{"status":"ok"}
```

3. Buka:

```text
https://domain-railway-kamu.up.railway.app/login
```

Login default:

```text
username: admin
password: admin123
```

Segera ganti password admin setelah berhasil login.

## 6. Jika Deploy Error

Cek **Deploy Logs** di Railway. Error yang paling sering:

- `DATABASE_URL` belum tersambung ke service PostgreSQL.
- `SECRET_KEY` belum diisi.
- Build gagal karena dependency belum terinstall.
- Aplikasi tidak membaca `$PORT`.

Repo ini sudah membaca `$PORT`, jadi kalau error port masih muncul, pastikan Railway memakai konfigurasi terbaru dari branch yang benar.
