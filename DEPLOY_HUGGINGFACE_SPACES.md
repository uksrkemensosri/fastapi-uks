# Deploy Gratis ke Hugging Face Spaces

Alternatif kalau Render meminta billing: gunakan Hugging Face Spaces dengan SDK Docker.

Tetap gunakan PostgreSQL eksternal seperti Neon untuk database. Jangan gunakan SQLite untuk deployment karena filesystem Spaces bisa hilang saat container restart.

## 1. Siapkan Database PostgreSQL

Buat database gratis di Neon, lalu copy connection string:

```text
postgresql://user:password@host/dbname?sslmode=require
```

## 2. Buat Space

1. Buka Hugging Face.
2. Pilih `New Space`.
3. Pilih SDK: `Docker`.
4. Pilih hardware gratis CPU/basic.
5. Buat Space.

Hugging Face Docker Spaces memakai port default `7860`; Dockerfile project ini sudah memakai port tersebut.

## 3. Upload Project

Push isi project ini ke repository Space.

File penting yang sudah disiapkan:

- `Dockerfile`
- `.dockerignore`
- `requirements.txt`

## 4. Set Secrets / Variables

Di Settings Space, tambahkan:

```text
DATABASE_URL=postgresql://...dari Neon...
SECRET_KEY=isi_random_panjang_minimal_32_karakter
ACCESS_TOKEN_EXPIRE_SECONDS=3600
SESSION_COOKIE_SECURE=true
```

Opsional:

```text
OPENROUTER_API_KEY=
FONNTE_TOKEN=
```

## 5. Tunggu Build

Spaces akan build Docker image otomatis setiap ada push.

Cek:

```text
https://huggingface.co/spaces/username/nama-space
```

Atau health endpoint:

```text
https://username-nama-space.hf.space/health
```

Jika muncul:

```json
{"status":"ok"}
```

aplikasi sudah aktif.

## Catatan

- Free Spaces bisa tidur/restart.
- Data tetap aman selama `DATABASE_URL` mengarah ke PostgreSQL eksternal.
- Login awal tetap:

```text
username: admin
password: admin123
```

Segera ganti password admin setelah deploy.
