// ============ 横火统一鉴权前端 ============
window.Auth = {
    async me() {
        try {
            const r = await fetch("/api/auth/me");
            const j = await r.json();
            return j.success ? j.data : null;
        } catch { return null; }
    },
    async login(identifier, password, remember = true) {
        const fd = new FormData();
        fd.append("identifier", identifier);
        fd.append("password", password);
        fd.append("remember", remember ? "true" : "false");
        const r = await fetch("/api/auth/login", { method: "POST", body: fd });
        return await r.json();
    },
    async logout() {
        await fetch("/api/auth/logout", { method: "POST" });
    },
    async register(data) {
        const fd = new FormData();
        Object.entries(data).forEach(([k, v]) => fd.append(k, v ?? ""));
        const r = await fetch("/api/auth/register", { method: "POST", body: fd });
        return await r.json();
    },
    async changePassword(oldPw, newPw, confirmPw) {
        const fd = new FormData();
        fd.append("old_password", oldPw);
        fd.append("new_password", newPw);
        fd.append("confirm_password", confirmPw);
        const r = await fetch("/api/auth/change-password", { method: "POST", body: fd });
        return await r.json();
    },
    async requireLogin(redirect = "/login") {
        const u = await this.me();
        if (!u) { location.href = redirect; return null; }
        return u;
    }
};

// 通用 Toast
window.showToast = function(msg, type = "info") {
    let t = document.getElementById("__toast");
    if (!t) {
        t = document.createElement("div");
        t.id = "__toast";
        t.style.cssText = `position:fixed;top:24px;left:50%;transform:translateX(-50%) translateY(-20px);
            background:#fff;border:1px solid #e2e6ef;box-shadow:0 6px 20px rgba(0,0,0,.18);
            padding:12px 22px;z-index:9999;opacity:0;transition:opacity .25s,transform .25s;max-width:80%;
            border-left:4px solid #a51c30;font-size:14px;border-radius:2px;`;
        document.body.appendChild(t);
    }
    t.textContent = msg;
    t.style.borderLeftColor =
        type === "success" ? "#2d7a3d" : type === "warn" ? "#a05b14" :
        type === "error" ? "#a51c30" : "#1a4fa0";
    t.classList.add("__show");
    t.style.opacity = "1"; t.style.transform = "translateX(-50%) translateY(0)";
    clearTimeout(window.__toast_t);
    window.__toast_t = setTimeout(() => {
        t.style.opacity = "0"; t.style.transform = "translateX(-50%) translateY(-20px)";
    }, 2600);
};
