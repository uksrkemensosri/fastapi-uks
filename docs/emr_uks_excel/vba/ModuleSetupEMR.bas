Attribute VB_Name = "ModuleSetupEMR"
Option Explicit

Public Sub SetupWorkbookEMR()
    Dim wsForm As Worksheet, wsDb As Worksheet

    Set wsForm = EnsureSheet("FormKunjungan")
    Set wsDb = EnsureSheet("DataKunjungan")

    SetupFormSheet wsForm
    SetupDbSheet wsDb

    MsgBox "Setup EMR selesai. Lanjutkan dengan input data dan assign tombol macro.", vbInformation
End Sub

Private Function EnsureSheet(ByVal sheetName As String) As Worksheet
    On Error Resume Next
    Set EnsureSheet = ThisWorkbook.Worksheets(sheetName)
    On Error GoTo 0

    If EnsureSheet Is Nothing Then
        Set EnsureSheet = ThisWorkbook.Worksheets.Add(After:=ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.Count))
        EnsureSheet.Name = sheetName
    End If
End Function

Private Sub SetupFormSheet(ByVal ws As Worksheet)
    ws.Cells.Clear

    ws.Range("A1").Value = "FORM KUNJUNGAN UKS"
    ws.Range("A1").Font.Bold = True
    ws.Range("A1").Font.Size = 14

    ws.Range("A2").Value = "Tanggal Kunjungan"
    ws.Range("A3").Value = "ID Kunjungan"
    ws.Range("A4").Value = "NISN/NIS"
    ws.Range("A5").Value = "Nama Siswa"
    ws.Range("A6").Value = "Kelas"
    ws.Range("A7").Value = "Jenis Kelamin"
    ws.Range("A8").Value = "Tanggal Lahir"
    ws.Range("A9").Value = "Alamat"
    ws.Range("A10").Value = "Penanggung Jawab"
    ws.Range("A11").Value = "Keluhan Utama"
    ws.Range("A12").Value = "Riwayat Singkat"
    ws.Range("A13").Value = "TTV"
    ws.Range("A14").Value = "Pemeriksaan Fisik"
    ws.Range("A15").Value = "Diagnosa Keperawatan"
    ws.Range("A16").Value = "Intervensi/Asuhan"
    ws.Range("A17").Value = "Edukasi"
    ws.Range("A18").Value = "Rencana Tindak Lanjut"
    ws.Range("A19").Value = "Perlu Rujukan (Ya/Tidak)"
    ws.Range("A20").Value = "Tujuan Rujukan"
    ws.Range("A21").Value = "Jadwal Kontrol Ulang"
    ws.Range("A22").Value = "Nama Perawat/Petugas"
    ws.Range("A23").Value = "Status Kunjungan"

    ws.Range("A2:A23").Font.Bold = True
    ws.Columns("A").ColumnWidth = 30
    ws.Columns("B").ColumnWidth = 50
    ws.Range("B2").Value = Date
End Sub

Private Sub SetupDbSheet(ByVal ws As Worksheet)
    Dim headers As Variant
    Dim i As Long

    ws.Cells.Clear

    headers = Array( _
        "TanggalKunjungan", "IDKunjungan", "NISN", "NamaSiswa", "Kelas", "JenisKelamin", "TglLahir", "Alamat", _
        "PenanggungJawab", "KeluhanUtama", "RiwayatSingkat", "TTV", "PemeriksaanFisik", "DiagnosaKeperawatan", _
        "Intervensi", "Edukasi", "RencanaTL", "PerluRujukan", "TujuanRujukan", "JadwalKontrolUlang", "Petugas", _
        "StatusKunjungan", "CreatedAt", "UpdatedAt" _
    )

    For i = LBound(headers) To UBound(headers)
        ws.Cells(1, i + 1).Value = headers(i)
    Next i

    ws.Rows(1).Font.Bold = True
    ws.Rows(1).Interior.Color = RGB(220, 230, 241)
    ws.Columns.AutoFit
End Sub
