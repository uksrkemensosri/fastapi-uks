(function () {
  const token = localStorage.getItem("access_token") || "";

  function hideAdminLinks(role) {
    const waliAsuhLinks = new Set(["/dashboard", "/students", "/settings"]);
    const timLinks = new Set(["/dashboard", "/students", "/complaints", "/ckg", "/fitness", "/settings"]);
    const kepalaLinks = new Set(["/dashboard", "/students", "/reports", "/ckg", "/fitness", "/settings"]);
    const adminLinks = new Set(["/dashboard", "/students", "/complaints", "/reports", "/ckg", "/fitness", "/users", "/audit-logs", "/settings"]);
    const perawatLinks = new Set(["/dashboard", "/students", "/complaints", "/reports", "/ckg", "/fitness", "/users", "/settings"]);
    const superAdminLinks = new Set([...adminLinks, "/schools"]);
    const sidebar = document.querySelector(".sidebar");
    if (sidebar && !sidebar.querySelector('a[href="/fitness"]')) {
      const ckgLink = sidebar.querySelector('a[href="/ckg"]');
      const fitnessLink = document.createElement("a");
      fitnessLink.href = "/fitness";
      fitnessLink.className = `menu-item${window.location.pathname === "/fitness" ? " active" : ""}`;
      fitnessLink.textContent = "Cek Kebugaran";
      if (ckgLink) {
        ckgLink.insertAdjacentElement("afterend", fitnessLink);
      }
    }
    if (["admin", "perawat", "tim_uksr", "super_admin"].includes(role) && sidebar && !sidebar.querySelector('a[href="/complaints"]')) {
      const studentsLink = sidebar.querySelector('a[href="/students"]');
      const complaintLink = document.createElement("a");
      complaintLink.href = "/complaints";
      complaintLink.className = `menu-item${window.location.pathname === "/complaints" ? " active" : ""}`;
      complaintLink.textContent = "Keluhan Masuk";
      if (studentsLink) {
        studentsLink.insertAdjacentElement("afterend", complaintLink);
      } else {
        sidebar.appendChild(complaintLink);
      }
    }
    if (role === "super_admin" && sidebar && !sidebar.querySelector('a[href="/schools"]')) {
      const usersLink = sidebar.querySelector('a[href="/users"]');
      const schoolLink = document.createElement("a");
      schoolLink.href = "/schools";
      schoolLink.className = `menu-item${window.location.pathname === "/schools" ? " active" : ""}`;
      schoolLink.textContent = "Schools";
      if (usersLink) {
        usersLink.insertAdjacentElement("beforebegin", schoolLink);
      } else {
        sidebar.appendChild(schoolLink);
      }
    }
    document.querySelectorAll(".menu-item").forEach((item) => {
      const href = item.getAttribute("href") || "";
      if (role === "wali_asuh" && !waliAsuhLinks.has(href)) {
        item.remove();
        return;
      }
      if (role === "tim_uksr" && !timLinks.has(href)) {
        item.remove();
        return;
      }
      if (role === "kepala_sekolah" && !kepalaLinks.has(href)) {
        item.remove();
        return;
      }
      if (role === "admin" && !adminLinks.has(href)) {
        item.remove();
        return;
      }
      if (role === "perawat" && !perawatLinks.has(href)) {
        item.remove();
        return;
      }
      if (role === "super_admin" && !superAdminLinks.has(href)) {
        item.remove();
        return;
      }
      if (!["admin", "perawat", "super_admin"].includes(role) && ["/users", "/audit-logs", "/schools"].includes(href)) {
        item.remove();
      }
    });
  }

  async function loadCurrentUser() {
    if (!token) {
      return null;
    }

    const res = await fetch("/api/auth/me", {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (!res.ok) {
      localStorage.removeItem("access_token");
      window.location.href = "/login";
      return null;
    }

    return res.json();
  }

  async function logout() {
    try {
      if (token) {
        await fetch("/api/auth/logout", {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        });
      }
    } catch (err) {
      console.warn("Logout audit failed", err);
    } finally {
      localStorage.removeItem("access_token");
      window.location.href = "/login";
    }
  }

  function applySavedTheme() {
    const savedTheme = localStorage.getItem("theme");
    if (savedTheme === "dark" || savedTheme === "true") {
      document.body.classList.add("dark");
      localStorage.setItem("theme", "dark");
    }
  }

  function updateThemeButton(button) {
    if (!button) {
      return;
    }
    const isDark = document.body.classList.contains("dark");
    button.textContent = isDark ? "\u2600\uFE0F" : "\u{1F319}";
    button.setAttribute("aria-label", isDark ? "Aktifkan mode terang" : "Aktifkan mode gelap");
    button.title = isDark ? "Mode terang" : "Mode gelap";
  }

  function setupGlobalThemeToggle() {
    applySavedTheme();

    let themeButton =
      document.getElementById("btnTheme") ||
      document.getElementById("themeToggle");

    if (!themeButton) {
      const topbar = document.querySelector(".topbar");
      if (!topbar) {
        return;
      }

      let actions =
        topbar.querySelector(".user-box") ||
        topbar.querySelector(".topbar-actions") ||
        topbar.querySelector(".user-actions");

      if (!actions) {
        actions = document.createElement("div");
        actions.className = "user-box";
        while (topbar.children.length > 1) {
          actions.appendChild(topbar.children[1]);
        }
        topbar.appendChild(actions);
      }

      themeButton = document.createElement("button");
      themeButton.id = "btnTheme";
      themeButton.type = "button";
      themeButton.dataset.globalTheme = "true";
      themeButton.className = "btn btn-secondary theme-toggle";
      const logoutButton = actions.querySelector("#btnLogout");
      if (logoutButton) {
        actions.insertBefore(themeButton, logoutButton);
      } else {
        actions.prepend(themeButton);
      }
    }

    themeButton.classList.add("btn", "btn-secondary", "theme-toggle");
    if (themeButton.dataset.globalTheme !== "true") {
      return;
    }

    updateThemeButton(themeButton);

    if (themeButton.dataset.globalTheme === "true" && themeButton.dataset.themeBound !== "true") {
      themeButton.dataset.themeBound = "true";
      themeButton.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        document.body.classList.toggle("dark");
        localStorage.setItem(
          "theme",
          document.body.classList.contains("dark") ? "dark" : "light"
        );
        updateThemeButton(themeButton);
      }, true);
    }
  }

  function loadAppTour() {
    if (document.getElementById("sehatiAppTourScript")) {
      return;
    }

    const script = document.createElement("script");
    script.id = "sehatiAppTourScript";
    script.src = "/ui/assets/app-tour.js?v=4";
    script.async = false;
    document.body.appendChild(script);
  }

  async function loadComplaintBadge(role) {
    if (!["admin", "perawat", "tim_uksr", "super_admin"].includes(role)) {
      return;
    }
    const link = document.querySelector('a[href="/complaints"]');
    if (!link) {
      return;
    }
    try {
      const response = await fetch("/api/complaints/pending-count", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        return;
      }
      const { count } = await response.json();
      link.textContent = count > 0 ? `Keluhan Masuk (${count})` : "Keluhan Masuk";
    } catch (err) {
      console.warn("Complaint badge unavailable", err);
    }
  }

  async function initRbacUi() {
    setupGlobalThemeToggle();

    const user = await loadCurrentUser();
    if (user) {
      hideAdminLinks(user.role);
      loadComplaintBadge(user.role);
      document.body.dataset.role = user.role;
      loadAppTour();
    }

    const logoutButton = document.getElementById("btnLogout");
    if (logoutButton) {
      logoutButton.addEventListener(
        "click",
        (event) => {
          event.preventDefault();
          event.stopImmediatePropagation();
          logout();
        },
          true
      );
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initRbacUi);
  } else {
    initRbacUi();
  }
})();
