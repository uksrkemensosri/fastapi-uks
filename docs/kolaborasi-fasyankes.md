# Kolaborasi Fasyankes — versi lokal untuk ditinjau

Halaman: `/kolaborasi-fasyankes`. Tidak ada pengiriman WhatsApp pada tahap ini.

- Kunjungan langsung ke puskesmas, klinik, RS, atau fasyankes lain.
- Rujukan BPJS baru membuat kasus dalam transaksi yang sama; rujukan lama tampil pada daftar integrasi dan dapat dibuka petugas tanpa duplikasi.
- Satu kasus berisi beberapa kunjungan/kontrol; jadwal berasal dari catatan yang sama. Menambahkan kontrol terkait menyelesaikan jadwal induknya; membatalkan kontrol memunculkan kembali kebutuhan kontrol induk.
- Perawat/admin dapat mengedit, membatalkan dengan alasan, atau undo perubahan terakhir. Riwayat tetap tersimpan. Optimistic locking menolak penyimpanan versi lama.
- Hasil klinis hanya untuk perawat/admin. Kepala sekolah/tim UKSR mendapat status tindakan, jadwal, petugas dan hambatan. Wali asuh hanya melihat siswa yang ditugaskan, beserta arahan pendampingan.
- Perubahan tersimpan membuat notifikasi dalam SEHATI untuk wali asuh aktif yang ditugaskan. Tidak menggunakan nomor orang tua sebagai pengganti penugasan wali asuh.
- Preview grup tanpa nama siswa, diagnosis, obat, atau hasil pemeriksaan. Tidak ada endpoint kirim/provider WhatsApp.

## Preview lokal dengan data fiktif

Jalankan `.venv-test/Scripts/python.exe scripts/preview_fasyankes.py`, lalu buka `http://127.0.0.1:8127/login`.

Akun: `demo.perawat`, `demo.walsuh`, `demo.kepala`; password demo: `DemoSehati2026!`.
Database terpisah di `tmp/fasyankes-preview.db`. Jangan gunakan akun ini di produksi.

## Rilis dan rollback

Belum di-deploy. Branch `codex/kolaborasi-fasyankes` dibuat dari kode produksi terakhir. Backup produksi dan persetujuan deployment diperlukan sebelum rilis seperti prosedur sebelumnya.

Migrasi additive `20261031_0011` dari revision produksi `20260924_0008` menambah tiga tabel: cases, revisions, notifications. Tidak menghapus/mengubah data tabel lama. Gunakan revision eksplisit karena folder lokal masih memuat migrasi Dokter Kecil yang tidak dilacak Git. Jangan memasukkan migrasi/aset Dokter Kecil ke paket rilis.

Rollback kode meninggalkan tabel dan riwayat baru. Downgrade penghapusan data sengaja ditolak. Catatan pembatalan/undo memperbarui notifikasi dalam aplikasi; tidak menghapus riwayat.

## Batas tahap ini

Belum ada integrasi sistem RS/BPJS eksternal, pengiriman grup/WhatsApp, atau upload dokumen konsultasi baru. Surat rujukan tetap tersedia lewat halaman Rujukan BPJS. Preview grup hanya bahan tinjauan. Uji PostgreSQL concurrency perlu dilakukan sebelum rilis produksi.
