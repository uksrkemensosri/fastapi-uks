# EMR Keperawatan UKS (Excel VBA) - MVP

Dokumen ini berisi rancangan sederhana EMR keperawatan untuk UKS dengan fokus:
- Identitas kunjungan
- Asuhan keperawatan
- Rencana tindak lanjut
- Riwayat kunjungan yang mudah difilter

## 1) Struktur Workbook

Gunakan 4 sheet utama:
1. `FormKunjungan` (input petugas)
2. `DataKunjungan` (database kunjungan)
3. `MasterSiswa` (master identitas siswa)
4. `Lookup` (dropdown list: kelas, keluhan umum, diagnosis keperawatan, tindakan)

## 2) Layout Sheet FormKunjungan

Isi label di kolom A dan input di kolom B:
- B2: Tanggal Kunjungan
- B3: ID Kunjungan (auto)
- B4: NISN/NIS
- B5: Nama Siswa
- B6: Kelas
- B7: Jenis Kelamin
- B8: Tanggal Lahir
- B9: Alamat
- B10: Penanggung Jawab
- B11: Keluhan Utama
- B12: Riwayat Singkat
- B13: TTV (TD, Nadi, RR, Suhu)
- B14: Pemeriksaan Fisik
- B15: Diagnosa Keperawatan
- B16: Intervensi/Asuhan
- B17: Edukasi
- B18: Rencana Tindak Lanjut
- B19: Perlu Rujukan (Ya/Tidak)
- B20: Tujuan Rujukan
- B21: Jadwal Kontrol Ulang
- B22: Nama Perawat/Petugas
- B23: Status Kunjungan (Selesai/Kontrol/Rujuk)

Tombol (shape/form control):
- `Simpan Kunjungan`
- `Update Kunjungan`
- `Cari Kunjungan`
- `Form Baru`

## 3) Layout Sheet DataKunjungan

Baris 1 sebagai header:
1. TanggalKunjungan
2. IDKunjungan
3. NISN
4. NamaSiswa
5. Kelas
6. JenisKelamin
7. TglLahir
8. Alamat
9. PenanggungJawab
10. KeluhanUtama
11. RiwayatSingkat
12. TTV
13. PemeriksaanFisik
14. DiagnosaKeperawatan
15. Intervensi
16. Edukasi
17. RencanaTL
18. PerluRujukan
19. TujuanRujukan
20. JadwalKontrolUlang
21. Petugas
22. StatusKunjungan
23. CreatedAt
24. UpdatedAt

## 4) Alur Kerja

1. Petugas isi form.
2. Klik `Simpan Kunjungan`.
3. Sistem validasi field wajib.
4. Data tersimpan ke `DataKunjungan` + timestamp.
5. Untuk revisi, cari ID lalu klik `Update Kunjungan`.

## 5) Catatan Implementasi

- File harus disimpan sebagai `.xlsm`.
- Aktifkan macro saat membuka file.
- Lindungi sheet database (`DataKunjungan`) agar tidak diubah manual.
- Backup berkala: salin file harian ke folder backup.

## 6) Pengembangan Tahap 2 (opsional)

- Nomor antrian harian otomatis.
- Dashboard rekap (kunjungan per kelas/per bulan/per diagnosis).
- Export PDF ringkasan kunjungan.
- Log aktivitas user.
- Validasi rujukan wajib isi tujuan bila pilih Ya.
