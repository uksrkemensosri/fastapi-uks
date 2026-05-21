Attribute VB_Name = "ModuleEMR"
Option Explicit

Private Const SHEET_FORM As String = "FormKunjungan"
Private Const SHEET_DB As String = "DataKunjungan"

Private Enum FormRow
    rTanggal = 2
    rID = 3
    rNISN = 4
    rNama = 5
    rKelas = 6
    rJK = 7
    rTglLahir = 8
    rAlamat = 9
    rPenanggungJawab = 10
    rKeluhan = 11
    rRiwayat = 12
    rTTV = 13
    rPemeriksaan = 14
    rDiagnosa = 15
    rIntervensi = 16
    rEdukasi = 17
    rRencanaTL = 18
    rPerluRujuk = 19
    rTujuanRujuk = 20
    rKontrol = 21
    rPetugas = 22
    rStatus = 23
End Enum

Public Sub InitFormBaru()
    Dim ws As Worksheet
    Set ws = ThisWorkbook.Worksheets(SHEET_FORM)

    With ws
        .Range("B2:B23").ClearContents
        .Range("B2").Value = Date
        .Range("B3").Value = GenerateVisitID(CDate(.Range("B2").Value))
        .Range("B19").Value = "Tidak"
        .Range("B23").Value = "Selesai"
    End With

    MsgBox "Form baru siap diisi.", vbInformation
End Sub

Public Sub SimpanKunjungan()
    Dim wsForm As Worksheet, wsDb As Worksheet
    Dim nextRow As Long

    Set wsForm = ThisWorkbook.Worksheets(SHEET_FORM)
    Set wsDb = ThisWorkbook.Worksheets(SHEET_DB)

    If Not ValidateForm(wsForm) Then Exit Sub

    If Trim$(CStr(wsForm.Cells(rID, "B").Value)) = "" Then
        wsForm.Cells(rID, "B").Value = GenerateVisitID(CDate(wsForm.Cells(rTanggal, "B").Value))
    End If

    If FindRowByID(wsDb, CStr(wsForm.Cells(rID, "B").Value)) > 0 Then
        MsgBox "ID Kunjungan sudah ada. Gunakan Update jika ingin mengubah data.", vbExclamation
        Exit Sub
    End If

    nextRow = wsDb.Cells(wsDb.Rows.Count, "A").End(xlUp).Row + 1
    WriteFormToDb wsForm, wsDb, nextRow, True

    MsgBox "Kunjungan berhasil disimpan.", vbInformation
End Sub

Public Sub UpdateKunjungan()
    Dim wsForm As Worksheet, wsDb As Worksheet
    Dim targetRow As Long
    Dim idKunjungan As String

    Set wsForm = ThisWorkbook.Worksheets(SHEET_FORM)
    Set wsDb = ThisWorkbook.Worksheets(SHEET_DB)

    If Not ValidateForm(wsForm) Then Exit Sub

    idKunjungan = Trim$(CStr(wsForm.Cells(rID, "B").Value))
    If idKunjungan = "" Then
        MsgBox "ID Kunjungan kosong. Cari data dulu sebelum update.", vbExclamation
        Exit Sub
    End If

    targetRow = FindRowByID(wsDb, idKunjungan)
    If targetRow = 0 Then
        MsgBox "ID Kunjungan tidak ditemukan.", vbExclamation
        Exit Sub
    End If

    WriteFormToDb wsForm, wsDb, targetRow, False
    MsgBox "Data kunjungan berhasil diupdate.", vbInformation
End Sub

Public Sub CariKunjunganByID()
    Dim wsForm As Worksheet, wsDb As Worksheet
    Dim idKunjungan As String
    Dim targetRow As Long

    Set wsForm = ThisWorkbook.Worksheets(SHEET_FORM)
    Set wsDb = ThisWorkbook.Worksheets(SHEET_DB)

    idKunjungan = InputBox("Masukkan ID Kunjungan (contoh: KJ-20260517-001)", "Cari Kunjungan")
    idKunjungan = Trim$(idKunjungan)

    If idKunjungan = "" Then Exit Sub

    targetRow = FindRowByID(wsDb, idKunjungan)
    If targetRow = 0 Then
        MsgBox "Data tidak ditemukan.", vbExclamation
        Exit Sub
    End If

    LoadDbToForm wsDb, wsForm, targetRow
    MsgBox "Data kunjungan ditemukan dan dimuat ke form.", vbInformation
End Sub

Private Function ValidateForm(ByVal ws As Worksheet) As Boolean
    ValidateForm = False

    If IsEmpty(ws.Cells(rTanggal, "B").Value) Then
        MsgBox "Tanggal kunjungan wajib diisi.", vbExclamation: Exit Function
    End If
    If Trim$(CStr(ws.Cells(rNISN, "B").Value)) = "" Then
        MsgBox "NISN/NIS wajib diisi.", vbExclamation: Exit Function
    End If
    If Trim$(CStr(ws.Cells(rNama, "B").Value)) = "" Then
        MsgBox "Nama siswa wajib diisi.", vbExclamation: Exit Function
    End If
    If Trim$(CStr(ws.Cells(rKeluhan, "B").Value)) = "" Then
        MsgBox "Keluhan utama wajib diisi.", vbExclamation: Exit Function
    End If
    If Trim$(CStr(ws.Cells(rDiagnosa, "B").Value)) = "" Then
        MsgBox "Diagnosa keperawatan wajib diisi.", vbExclamation: Exit Function
    End If
    If Trim$(CStr(ws.Cells(rIntervensi, "B").Value)) = "" Then
        MsgBox "Intervensi/Asuhan wajib diisi.", vbExclamation: Exit Function
    End If
    If Trim$(CStr(ws.Cells(rPetugas, "B").Value)) = "" Then
        MsgBox "Nama petugas wajib diisi.", vbExclamation: Exit Function
    End If

    If UCase$(Trim$(CStr(ws.Cells(rPerluRujuk, "B").Value))) = "YA" Then
        If Trim$(CStr(ws.Cells(rTujuanRujuk, "B").Value)) = "" Then
            MsgBox "Tujuan rujukan wajib diisi jika Perlu Rujukan = Ya.", vbExclamation
            Exit Function
        End If
    End If

    ValidateForm = True
End Function

Private Sub WriteFormToDb(ByVal wsForm As Worksheet, ByVal wsDb As Worksheet, ByVal rowNum As Long, ByVal isNew As Boolean)
    wsDb.Cells(rowNum, 1).Value = wsForm.Cells(rTanggal, "B").Value
    wsDb.Cells(rowNum, 2).Value = wsForm.Cells(rID, "B").Value
    wsDb.Cells(rowNum, 3).Value = wsForm.Cells(rNISN, "B").Value
    wsDb.Cells(rowNum, 4).Value = wsForm.Cells(rNama, "B").Value
    wsDb.Cells(rowNum, 5).Value = wsForm.Cells(rKelas, "B").Value
    wsDb.Cells(rowNum, 6).Value = wsForm.Cells(rJK, "B").Value
    wsDb.Cells(rowNum, 7).Value = wsForm.Cells(rTglLahir, "B").Value
    wsDb.Cells(rowNum, 8).Value = wsForm.Cells(rAlamat, "B").Value
    wsDb.Cells(rowNum, 9).Value = wsForm.Cells(rPenanggungJawab, "B").Value
    wsDb.Cells(rowNum, 10).Value = wsForm.Cells(rKeluhan, "B").Value
    wsDb.Cells(rowNum, 11).Value = wsForm.Cells(rRiwayat, "B").Value
    wsDb.Cells(rowNum, 12).Value = wsForm.Cells(rTTV, "B").Value
    wsDb.Cells(rowNum, 13).Value = wsForm.Cells(rPemeriksaan, "B").Value
    wsDb.Cells(rowNum, 14).Value = wsForm.Cells(rDiagnosa, "B").Value
    wsDb.Cells(rowNum, 15).Value = wsForm.Cells(rIntervensi, "B").Value
    wsDb.Cells(rowNum, 16).Value = wsForm.Cells(rEdukasi, "B").Value
    wsDb.Cells(rowNum, 17).Value = wsForm.Cells(rRencanaTL, "B").Value
    wsDb.Cells(rowNum, 18).Value = wsForm.Cells(rPerluRujuk, "B").Value
    wsDb.Cells(rowNum, 19).Value = wsForm.Cells(rTujuanRujuk, "B").Value
    wsDb.Cells(rowNum, 20).Value = wsForm.Cells(rKontrol, "B").Value
    wsDb.Cells(rowNum, 21).Value = wsForm.Cells(rPetugas, "B").Value
    wsDb.Cells(rowNum, 22).Value = wsForm.Cells(rStatus, "B").Value

    If isNew Then
        wsDb.Cells(rowNum, 23).Value = Now
    End If
    wsDb.Cells(rowNum, 24).Value = Now
End Sub

Private Sub LoadDbToForm(ByVal wsDb As Worksheet, ByVal wsForm As Worksheet, ByVal rowNum As Long)
    wsForm.Cells(rTanggal, "B").Value = wsDb.Cells(rowNum, 1).Value
    wsForm.Cells(rID, "B").Value = wsDb.Cells(rowNum, 2).Value
    wsForm.Cells(rNISN, "B").Value = wsDb.Cells(rowNum, 3).Value
    wsForm.Cells(rNama, "B").Value = wsDb.Cells(rowNum, 4).Value
    wsForm.Cells(rKelas, "B").Value = wsDb.Cells(rowNum, 5).Value
    wsForm.Cells(rJK, "B").Value = wsDb.Cells(rowNum, 6).Value
    wsForm.Cells(rTglLahir, "B").Value = wsDb.Cells(rowNum, 7).Value
    wsForm.Cells(rAlamat, "B").Value = wsDb.Cells(rowNum, 8).Value
    wsForm.Cells(rPenanggungJawab, "B").Value = wsDb.Cells(rowNum, 9).Value
    wsForm.Cells(rKeluhan, "B").Value = wsDb.Cells(rowNum, 10).Value
    wsForm.Cells(rRiwayat, "B").Value = wsDb.Cells(rowNum, 11).Value
    wsForm.Cells(rTTV, "B").Value = wsDb.Cells(rowNum, 12).Value
    wsForm.Cells(rPemeriksaan, "B").Value = wsDb.Cells(rowNum, 13).Value
    wsForm.Cells(rDiagnosa, "B").Value = wsDb.Cells(rowNum, 14).Value
    wsForm.Cells(rIntervensi, "B").Value = wsDb.Cells(rowNum, 15).Value
    wsForm.Cells(rEdukasi, "B").Value = wsDb.Cells(rowNum, 16).Value
    wsForm.Cells(rRencanaTL, "B").Value = wsDb.Cells(rowNum, 17).Value
    wsForm.Cells(rPerluRujuk, "B").Value = wsDb.Cells(rowNum, 18).Value
    wsForm.Cells(rTujuanRujuk, "B").Value = wsDb.Cells(rowNum, 19).Value
    wsForm.Cells(rKontrol, "B").Value = wsDb.Cells(rowNum, 20).Value
    wsForm.Cells(rPetugas, "B").Value = wsDb.Cells(rowNum, 21).Value
    wsForm.Cells(rStatus, "B").Value = wsDb.Cells(rowNum, 22).Value
End Sub

Private Function FindRowByID(ByVal wsDb As Worksheet, ByVal idKunjungan As String) As Long
    Dim lastRow As Long, i As Long
    lastRow = wsDb.Cells(wsDb.Rows.Count, "B").End(xlUp).Row

    For i = 2 To lastRow
        If Trim$(CStr(wsDb.Cells(i, 2).Value)) = idKunjungan Then
            FindRowByID = i
            Exit Function
        End If
    Next i

    FindRowByID = 0
End Function

Private Function GenerateVisitID(ByVal visitDate As Date) As String
    Dim wsDb As Worksheet
    Dim lastRow As Long, i As Long, counter As Long
    Dim prefix As String, currID As String

    Set wsDb = ThisWorkbook.Worksheets(SHEET_DB)
    prefix = "KJ-" & Format$(visitDate, "yyyymmdd") & "-"
    counter = 0

    lastRow = wsDb.Cells(wsDb.Rows.Count, "B").End(xlUp).Row
    For i = 2 To lastRow
        currID = Trim$(CStr(wsDb.Cells(i, 2).Value))
        If Left$(currID, Len(prefix)) = prefix Then
            counter = counter + 1
        End If
    Next i

    GenerateVisitID = prefix & Format$(counter + 1, "000")
End Function
