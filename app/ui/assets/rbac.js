(function () {
  const token = localStorage.getItem("access_token") || "";

  function hideAdminLinks(role) {
    const waliAsuhLinks = new Set(["/students", "/settings"]);
    const timLinks = new Set(["/dashboard", "/students", "/ckg", "/settings"]);
    const kepalaLinks = new Set(["/dashboard", "/students", "/reports", "/ckg", "/settings"]);
    const adminLinks = new Set(["/dashboard", "/students", "/reports", "/ckg", "/users", "/audit-logs", "/settings"]);
    const perawatLinks = new Set(["/dashboard", "/students", "/reports", "/ckg", "/users", "/settings"]);
    const superAdminLinks = new Set([...adminLinks, "/schools"]);
    const sidebar = document.querySelector(".sidebar");
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

  document.addEventListener("DOMContentLoaded", async () => {
    const user = await loadCurrentUser();
    if (user) {
      hideAdminLinks(user.role);
      document.body.dataset.role = user.role;
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
  });
})();
