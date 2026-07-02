# WhatsApp Notification UKS

Sistem mengirim notifikasi WhatsApp ketika kunjungan UKS baru disimpan.

Provider yang dipakai: Fonnte.

## Data yang Dibutuhkan

Di Data Siswa, pastikan terisi:

- Nama Wali Asuh
- Nomor HP Wali Asuh

Nomor akan dinormalisasi otomatis:

- `081234567890` menjadi `6281234567890`
- `81234567890` menjadi `6281234567890`
- `6281234567890` tetap dipakai

## Environment Variable

Isi di `.env` lokal atau dashboard deploy:

```text
FONNTE_TOKEN=token_fonnte_kamu
FONNTE_API_URL=https://api.fonnte.com/send
```

`FONNTE_API_URL` opsional. Jika kosong, sistem otomatis memakai endpoint default Fonnte.

## Perilaku Sistem

- Jika token belum diisi, kunjungan tetap tersimpan.
- Jika nomor wali asuh kosong/tidak valid, kunjungan tetap tersimpan.
- Jika Fonnte error, kunjungan tetap tersimpan.
- Response API kunjungan menyertakan:

```json
{
  "whatsapp_status": "sent | skipped | failed",
  "whatsapp_message": "detail status"
}
```

## Isi Pesan

Pesan berisi:

- Nama wali asuh
- Nama siswa
- Tanggal kunjungan
- Keluhan
- Diagnosa
- Tindakan

Pesan dikirim otomatis saat data kunjungan UKS baru dibuat.
