(function () {
  let resolver = null;
  let payloadReader = null;

  function ensureDialog() {
    let root = document.getElementById("appDialogBackdrop");
    if (root) return root;

    const style = document.createElement("style");
    style.textContent = `
      .app-dialog-backdrop{position:fixed;inset:0;z-index:999999;display:none;align-items:center;justify-content:center;padding:22px;background:rgba(15,23,42,.42);backdrop-filter:blur(8px)}
      .app-dialog-backdrop.open{display:flex}
      .app-dialog{width:min(520px,100%);background:white;border-radius:28px;padding:28px;box-shadow:0 24px 70px rgba(15,23,42,.22);border:1px solid rgba(255,255,255,.65)}
      .app-dialog h2{margin:0 0 10px;color:#312e81;font-size:1.35rem;line-height:1.25}
      .app-dialog p{margin:0 0 24px;color:#64748b;line-height:1.7;white-space:pre-line}
      .app-dialog-field{width:100%;padding:14px 16px;border:1px solid #dbe3ef;border-radius:16px;margin:0 0 12px;background:white;color:#334155}
      .app-dialog-actions{display:flex;gap:12px;justify-content:flex-end;flex-wrap:wrap}
      .app-dialog-btn{border:0;border-radius:18px;padding:13px 22px;font-weight:900;cursor:pointer}
      .app-dialog-cancel{background:#eff6ff;color:#6d28d9}
      .app-dialog-confirm{background:linear-gradient(135deg,#ec6cc4,#8b5cf6,#60a5fa);color:white}
      .app-dialog-confirm.danger{background:#dc2626}
    `;
    document.head.appendChild(style);

    root = document.createElement("div");
    root.id = "appDialogBackdrop";
    root.className = "app-dialog-backdrop";
    root.innerHTML = `
      <div class="app-dialog" role="dialog" aria-modal="true" aria-labelledby="appDialogTitle">
        <h2 id="appDialogTitle">Informasi</h2>
        <p id="appDialogMessage"></p>
        <div id="appDialogFields"></div>
        <div class="app-dialog-actions">
          <button class="app-dialog-btn app-dialog-cancel" id="appDialogCancel" type="button">Batal</button>
          <button class="app-dialog-btn app-dialog-confirm" id="appDialogConfirm" type="button">Oke</button>
        </div>
      </div>
    `;
    document.body.appendChild(root);

    document.getElementById("appDialogCancel").addEventListener("click", () => close(false));
    document.getElementById("appDialogConfirm").addEventListener("click", () => {
      close(payloadReader ? payloadReader() : true);
    });
    root.addEventListener("click", event => {
      if (event.target === root) close(false);
    });
    return root;
  }

  function open(options) {
    const root = ensureDialog();
    const title = document.getElementById("appDialogTitle");
    const message = document.getElementById("appDialogMessage");
    const fields = document.getElementById("appDialogFields");
    const cancel = document.getElementById("appDialogCancel");
    const confirm = document.getElementById("appDialogConfirm");

    title.textContent = options.title || "Informasi";
    message.textContent = options.message || "";
    fields.innerHTML = options.fields || "";
    cancel.textContent = options.cancelText || "Batal";
    confirm.textContent = options.confirmText || "Oke";
    cancel.style.display = options.hideCancel ? "none" : "inline-flex";
    confirm.classList.toggle("danger", options.type === "danger" || options.type === "error");
    payloadReader = options.payloadReader || null;
    root.classList.add("open");

    setTimeout(() => fields.querySelector("input, textarea, select")?.focus(), 0);
    return new Promise(resolve => {
      resolver = resolve;
    });
  }

  function close(value) {
    const root = ensureDialog();
    root.classList.remove("open");
    if (resolver) resolver(value);
    resolver = null;
    payloadReader = null;
  }

  window.appAlert = function (title, message, type = "info") {
    return open({ title, message, type, hideCancel: true, confirmText: "Oke" });
  };

  window.appConfirm = function (title, message, options = {}) {
    return open({
      title,
      message,
      type: options.type || "danger",
      confirmText: options.confirmText || "Ya, Hapus",
      cancelText: options.cancelText || "Batal"
    });
  };

  window.appPrompt = function (title, message, defaultValue = "", options = {}) {
    const inputId = `appPrompt_${Date.now()}`;
    const field = options.multiline
      ? `<textarea id="${inputId}" class="app-dialog-field" placeholder="${options.placeholder || ""}">${defaultValue || ""}</textarea>`
      : `<input id="${inputId}" class="app-dialog-field" value="${defaultValue || ""}" placeholder="${options.placeholder || ""}">`;
    return open({
      title,
      message,
      type: options.type || "info",
      confirmText: options.confirmText || "Simpan",
      cancelText: options.cancelText || "Batal",
      fields: field,
      payloadReader: () => document.getElementById(inputId).value.trim()
    }).then(value => value === false ? null : value);
  };
})();
