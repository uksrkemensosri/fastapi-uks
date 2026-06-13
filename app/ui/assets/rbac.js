(function () {
  const token = localStorage.getItem("access_token") || "";

  function hideAdminLinks(role) {
    document.querySelectorAll(".menu-item").forEach((item) => {
      const href = item.getAttribute("href") || "";
      if (role !== "admin" && ["/users", "/settings", "/audit-logs"].includes(href)) {
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
