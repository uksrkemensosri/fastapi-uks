# Deploy Gratis EMR UKS FastAPI

Rekomendasi paling sederhana untuk versi gratis adalah:

- Web app: Render Free Web Service
- Database: PostgreSQL hosted, misalnya Neon Free atau Render Postgres sementara

Catatan penting:

- Jangan pakai SQLite untuk deploy gratis. Filesystem Render Free bersifat ephemeral, jadi file database lokal bisa hilang saat restart/redeploy/spin down.
- Render Free bisa sleep saat idle. Saat dibuka lagi, aplikasi bisa butuh sekitar satu menit untuk aktif kembali.
- Render Postgres Free punya batas waktu. Untuk data yang ingin lebih awet, pakai PostgreSQL eksternal yang free tier-nya lebih cocok.

## File yang Sudah Disiapkan

- `Procfile`
- `render.yaml`
- `requirements.txt`
- `runtime.txt`

## Environment Variables

Set di dashboard Render:

```text
DATABASE_URL=postgresql://...
SECRET_KEY=isi-dengan-random-panjang-minimal-32-karakter
ACCESS_TOKEN_EXPIRE_SECONDS=3600
SESSION_COOKIE_SECURE=true
```

Opsional:

```text
OPENROUTER_API_KEY=
FONNTE_TOKEN=
```

## Build dan Start Command

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Health check path:

```text
/health
```

## Langkah Deploy Render

1. Push project ke GitHub.
2. Buat PostgreSQL database, ambil connection string `DATABASE_URL`.
3. Buka Render, pilih `New Web Service`.
4. Connect repository GitHub project ini.
5. Pilih instance `Free`.
6. Isi build command dan start command di atas, atau pakai `render.yaml`.
7. Tambahkan environment variables.
8. Deploy.
9. Setelah deploy selesai, buka:

```text
https://nama-service.onrender.com/health
```

Kalau hasilnya:

```json
{"status":"ok"}
```

aplikasi sudah hidup.

## Setelah Deploy

Login awal default masih:

```text
username: admin
password: admin123
```

Segera ganti password admin setelah deploy.
