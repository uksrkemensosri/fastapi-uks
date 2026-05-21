# Checklist UAT UKS

## A. Auth & Akses
1. Login admin berhasil.
2. `GET /api/auth/me` menampilkan user aktif.
3. Refresh token berhasil (`POST /api/auth/refresh`).
4. Endpoint tanpa token ditolak (`401`).

## B. Master Siswa
5. Tambah siswa baru berhasil (`POST /api/patients`).
6. Cari siswa dengan nama/id berhasil (`GET /api/patients/search`).
7. Detail siswa tampil benar (`GET /api/patients/{patient_id}`).

## C. Kunjungan UKS
8. Input kunjungan berhasil (`POST /api/uks/visits`).
9. Detail kunjungan tampil benar (`GET /api/uks/visits/{visit_id}`).
10. Riwayat kunjungan per siswa tampil urut terbaru (`GET /api/patients/{patient_id}/uks-visits`).

## D. Obat & Rujukan
11. Tambah obat per kunjungan berhasil (`POST /api/uks/visits/{visit_id}/medications`).
12. List obat kunjungan tampil benar (`GET /api/uks/visits/{visit_id}/medications`).
13. Update rujukan berhasil (`PATCH /api/uks/visits/{visit_id}/referral`).

## E. Laporan
14. Laporan harian tampil jumlah kunjungan dan top keluhan (`GET /api/reports/uks/daily`).
15. Laporan bulanan tampil jumlah kunjungan dan rujukan (`GET /api/reports/uks/monthly`).
16. Input tanggal/bulan invalid ditolak (`400`).

## F. Operasional
17. Backup manual DB berhasil (`.\backup_db.ps1`).
18. Endpoint health mengembalikan status ok (`GET /health`).

## G. Exit Criteria
1. Semua butir lulus.
2. Tidak ada error kritis pada alur harian.
3. Petugas UKS bisa menjalankan alur tanpa pendampingan teknis.
