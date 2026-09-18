(function () {
  const token = localStorage.getItem("access_token") || "";
  const tourClass = "sehati-tour-target";
  let currentUser = null;
  let steps = [];
  let stepIndex = 0;
  let overlay;
  let popover;

  const menuStep = (selector, title, description) => ({ selector, title, description });

  function tourFor(role, path) {
    const roleLabel = {
      super_admin: "Super Admin", admin: "Admin", perawat: "Perawat",
      kepala_sekolah: "Kepala Sekolah", tim_uksr: "Tim UKSR", wali_asuh: "Wali Asuh",
    };
    const intro = `Fitur ini tersedia untuk ${roleLabel[role] || "akun"} sesuai hak aksesnya.`;
    const pageSteps = {
      "/dashboard": [
        menuStep(".topbar", "Dashboard", `Lihat ringkasan aktivitas dan informasi utama SEHATI. ${intro}`),
        menuStep("#globalSearch", "Pencarian Siswa", "Cari peserta didik dengan cepat dari dashboard."),
        menuStep("#todayVisitMini", "Kunjungan Hari Ini", "Pantau jumlah pelayanan UKS yang tercatat hari ini."),
        menuStep("#lowStockList", "Stok Obat", "Periksa obat yang hampir habis agar dapat segera ditindaklanjuti."),
        menuStep("#recentActivities", "Aktivitas Terbaru", "Lihat aktivitas pelayanan dan pembaruan data terkini."),
      ],
      "/students": [
        menuStep("#siswa", "Data Peserta Didik", `Kelola data peserta didik yang tersedia untuk akun kamu. ${intro}`),
        menuStep("#searchPatientTable", "Pencarian Cepat", "Cari nama peserta didik untuk membuka data dan riwayatnya."),
        menuStep("#kunjungan", "Catat Kunjungan UKS", "Pilih siswa, isi keluhan serta tindakan, lalu simpan pelayanan UKS."),
        menuStep("#riwayat", "Riwayat Kunjungan", "Gunakan filter untuk melihat riwayat pelayanan yang telah dicatat."),
      ],
      "/reports": [
        menuStep("#panel-monthly", "Laporan Bulanan", `Pilih periode laporan sesuai kebutuhan. ${intro}`),
        menuStep("#btnPreview", "Preview Laporan", "Tampilkan ringkasan laporan sebelum diunduh."),
        menuStep("#btnDownloadPdf", "Download PDF", "Unduh laporan bulanan dalam format PDF dengan kop surat sekolah."),
        menuStep("#panel-visits", "Laporan Kunjungan", "Buka laporan kunjungan harian, mingguan, atau bulanan."),
        menuStep("#panel-medicines", "Stok dan Mutasi Obat", "Kelola stok obat serta unduh laporan stok dan mutasi."),
      ],
      "/ckg": [
        menuStep("#panel-dashboard", "Dashboard CKG", `Pantau jumlah peserta, progres, dan rujukan CKG. ${intro}`),
        menuStep("#totalRegistered", "Status Peserta", "Lihat jumlah peserta terdaftar dan status proses pemeriksaannya."),
        menuStep("#btnPrintCkgReport", "Cetak Laporan CKG", "Unduh laporan CKG yang tersedia dalam PDF."),
        menuStep("#referralRows", "Tindak Lanjut Rujukan", "Pantau peserta yang membutuhkan tindak lanjut rujukan."),
      ],
      "/fitness": [
        menuStep("#panel-dashboard", "Dashboard Kebugaran", `Pantau peserta dan progres cek kebugaran. ${intro}`),
        menuStep("#totalRegistered", "Status Pemeriksaan", "Lihat jumlah peserta yang terdaftar, selesai, dan masih menunggu."),
        menuStep("#btnPrintReport", "Cetak Laporan", "Unduh laporan cek kebugaran dalam format PDF."),
        menuStep("#recentRows", "Peserta Terbaru", "Lihat peserta yang terakhir diperiksa."),
      ],
      "/users": [
        menuStep("#btnAddUser", "Tambah Pengguna", `Buat akun pengguna baru sesuai kewenangan kamu. ${intro}`),
        menuStep("#userFormCard", "Form Pengguna", "Isi nama, username, role, dan data pendukung sebelum menyimpan akun."),
        menuStep("#userTable", "Daftar Pengguna", "Kelola data akun, reset password, atau ubah status pengguna."),
      ],
      "/schools": [
        menuStep("#schoolForm", "Tambah atau Edit School", "Isi identitas sekolah untuk membuat atau memperbarui data tenant."),
        menuStep("#schoolRows", "Daftar Schools", "Lihat status sekolah dan lakukan perubahan data bila diperlukan."),
      ],
      "/audit-logs": [
        menuStep("#filterUser", "Filter Aktivitas", "Saring audit log berdasarkan pengguna, aksi, periode, atau kata kunci."),
        menuStep("#btnFilter", "Terapkan Filter", "Tampilkan aktivitas yang sesuai dengan filter yang dipilih."),
        menuStep("#btnExportAudit", "Export Excel", "Unduh hasil audit log untuk dokumentasi atau evaluasi."),
        menuStep("#auditTable", "Riwayat Sistem", "Lihat jejak aktivitas penting yang tercatat pada sistem."),
      ],
      "/settings": [
        menuStep("#btnSaveProfile", "Profil Saya", `Perbarui nama, NIP, jabatan, dan tanda tangan akun kamu. ${intro}`),
        menuStep("#signatureFile", "Tanda Tangan Digital", "Unggah tanda tangan PNG atau JPG untuk dokumen yang membutuhkan pengesahan."),
        menuStep("#btnChangePassword", "Ubah Password", "Ganti password akun secara berkala untuk menjaga keamanan."),
        menuStep("#btnHealthCheck", "Tools Admin", "Admin dapat mengecek sistem, backup data, dan mengimpor data siswa."),
      ],
      "/student-detail": [
        menuStep("#panel-biodata", "Biodata", "Lihat informasi dasar peserta didik dan wali asuh."),
        menuStep("#panel-uks", "Riwayat UKS", "Lihat catatan pelayanan UKS yang pernah diterima."),
        menuStep("#panel-ckg", "Riwayat CKG", "Lihat hasil dan ringkasan pemeriksaan CKG."),
        menuStep("#panel-rekomendasi", "Rekomendasi", "Lihat rekomendasi kesehatan dan tindak lanjut yang dibuat."),
      ],
    };
    return pageSteps[path] || [menuStep(".topbar", "SEHATI", `Kenali fitur yang tersedia pada halaman ini. ${intro}`)];
  }

  function injectStyles() {
    if (document.getElementById("sehatiTourStyles")) return;
    const style = document.createElement("style");
    style.id = "sehatiTourStyles";
    style.textContent = `
      .sehati-tour-overlay { position: fixed; inset: 0; z-index: 9998; background: rgba(30, 35, 78, .42); backdrop-filter: blur(2px); }
      .${tourClass} { position: relative !important; z-index: 9999 !important; outline: 3px solid #8db9ff !important; outline-offset: 5px; border-radius: 10px; box-shadow: 0 0 0 7px rgba(255,255,255,.82), 0 12px 28px rgba(45,58,139,.28); }
      .sehati-tour-popover { position: fixed; z-index: 10000; width: min(360px, calc(100vw - 32px)); padding: 22px; border: 1px solid rgba(255,255,255,.9); border-radius: 18px; color: #273160; background: rgba(255,255,255,.98); box-shadow: 0 22px 56px rgba(48,45,105,.28); }
      .sehati-tour-eyebrow { margin: 0 0 8px; color: #8462e8; font-size: 13px; font-weight: 800; }
      .sehati-tour-popover h2 { margin: 0; color: #30368d; font-size: 21px; line-height: 1.3; }
      .sehati-tour-popover p { margin: 10px 0 20px; color: #66728c; font-size: 14px; line-height: 1.6; }
      .sehati-tour-actions { display: flex; align-items: center; gap: 8px; }
      .sehati-tour-progress { margin-right: auto; color: #65708a; font-size: 13px; font-weight: 700; }
      .sehati-tour-button { min-height: 38px; padding: 0 13px; border: 0; border-radius: 10px; cursor: pointer; font: inherit; font-size: 13px; font-weight: 800; }
      .sehati-tour-button.secondary { color: #7054d9; background: #f1edff; }
      .sehati-tour-button.primary { color: #fff; background: linear-gradient(90deg,#e863bd,#9b75ed,#639df2); }
      .sehati-tour-trigger { width: auto !important; white-space: nowrap; }
      @media (max-width: 600px) { .sehati-tour-popover { padding: 18px; border-radius: 16px; } .sehati-tour-actions { flex-wrap: wrap; } .sehati-tour-progress { width: 100%; } }
    `;
    document.head.appendChild(style);
  }

  function cleanup() {
    document.querySelectorAll(`.${tourClass}`).forEach((element) => element.classList.remove(tourClass));
    overlay?.remove();
    popover?.remove();
    overlay = null;
    popover = null;
  }

  function finish(markSeen) {
    if (markSeen && currentUser) localStorage.setItem(`sehati_app_tour_seen_${currentUser.id}`, "1");
    cleanup();
  }

  function positionPopover(target) {
    if (!popover || !target.isConnected) return;
    const rect = target.getBoundingClientRect();
    const popoverRect = popover.getBoundingClientRect();
    const left = Math.max(16, Math.min(rect.left, window.innerWidth - popoverRect.width - 16));
    let top = rect.bottom + 18;
    if (top + popoverRect.height > window.innerHeight - 16) top = rect.top - popoverRect.height - 18;
    if (top < 16) top = Math.max(16, (window.innerHeight - popoverRect.height) / 2);
    popover.style.left = `${left}px`;
    popover.style.top = `${top}px`;
  }

  function renderStep() {
    cleanup();
    const step = steps[stepIndex];
    const target = document.querySelector(step.selector);
    if (!target) {
      steps.splice(stepIndex, 1);
      if (!steps.length) return;
      if (stepIndex >= steps.length) stepIndex = steps.length - 1;
      renderStep();
      return;
    }

    target.scrollIntoView({ behavior: "auto", block: "center", inline: "nearest" });
    overlay = document.createElement("div");
    overlay.className = "sehati-tour-overlay";
    overlay.addEventListener("click", () => finish(true));
    document.body.appendChild(overlay);
    target.classList.add(tourClass);

    popover = document.createElement("section");
    popover.className = "sehati-tour-popover";
    popover.setAttribute("role", "dialog");
    popover.setAttribute("aria-modal", "true");
    popover.innerHTML = `<div class="sehati-tour-eyebrow">SEHATI App Tour</div><h2></h2><p></p><div class="sehati-tour-actions"><span class="sehati-tour-progress"></span><button class="sehati-tour-button secondary" data-action="skip">Lewati</button><button class="sehati-tour-button secondary" data-action="back">Kembali</button><button class="sehati-tour-button primary" data-action="next"></button></div>`;
    popover.querySelector("h2").textContent = step.title;
    popover.querySelector("p").textContent = step.description;
    popover.querySelector(".sehati-tour-progress").textContent = `${stepIndex + 1} dari ${steps.length}`;
    popover.querySelector('[data-action="back"]').hidden = stepIndex === 0;
    popover.querySelector('[data-action="next"]').textContent = stepIndex === steps.length - 1 ? "Selesai" : "Berikutnya";
    popover.addEventListener("click", (event) => {
      const action = event.target.dataset.action;
      if (action === "skip") finish(true);
      if (action === "back" && stepIndex > 0) { stepIndex -= 1; renderStep(); }
      if (action === "next") {
        if (stepIndex === steps.length - 1) finish(true);
        else { stepIndex += 1; renderStep(); }
      }
    });
    document.body.appendChild(popover);

    requestAnimationFrame(() => {
      window.setTimeout(() => {
        positionPopover(target);
      }, 0);
      popover.querySelector('[data-action="next"]').focus();
    });
  }

  function startTour() {
    if (!currentUser) return;
    steps = tourFor(currentUser.role, window.location.pathname).filter((step) => {
      const target = document.querySelector(step.selector);
      return target && target.getClientRects().length > 0;
    });
    if (!steps.length) return;
    stepIndex = 0;
    renderStep();
  }

  function addTourButton() {
    const actions =
      document.querySelector(".topbar .user-box") ||
      document.querySelector(".topbar .topbar-actions") ||
      document.querySelector(".topbar .user-actions") ||
      document.getElementById("btnLogout")?.parentElement;
    if (!actions || document.getElementById("btnAppTour")) return;
    const button = document.createElement("button");
    button.id = "btnAppTour";
    button.type = "button";
    button.className = "btn btn-secondary sehati-tour-trigger";
    button.textContent = "🧭 App Tour";
    button.addEventListener("click", startTour);
    const logoutButton = actions.querySelector("#btnLogout");
    if (logoutButton) actions.insertBefore(button, logoutButton);
    else actions.appendChild(button);
  }

  async function init() {
    if (!token) return;
    try {
      const response = await fetch("/api/auth/me", { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) return;
      currentUser = await response.json();
      injectStyles();
      setTimeout(() => {
        addTourButton();
        const pendingKey = `sehati_app_tour_pending_${currentUser.id}`;
        const seenKey = `sehati_app_tour_seen_${currentUser.id}`;
        const isLandingPage = ["/dashboard", "/students"].includes(window.location.pathname);
        if (isLandingPage && !localStorage.getItem(seenKey)) {
          localStorage.removeItem(pendingKey);
          startTour();
        }
      }, 250);
    } catch (error) {
      console.warn("App Tour tidak dapat dimuat", error);
    }
  }

  window.addEventListener("resize", () => { if (popover) renderStep(); });
  init();
})();
