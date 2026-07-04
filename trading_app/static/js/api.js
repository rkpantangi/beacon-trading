/* Shared API client + formatting helpers. */

const API = {
  async request(path, options = {}) {
    const resp = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    let data = null;
    try { data = await resp.json(); } catch (e) { /* non-JSON error body */ }
    if (!resp.ok) {
      const msg = data && data.detail ? data.detail : `Request failed (${resp.status})`;
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    return data;
  },
  get(path) { return this.request(path); },
  post(path, body) { return this.request(path, { method: "POST", body: JSON.stringify(body) }); },
  del(path) { return this.request(path, { method: "DELETE" }); },
};

function fmtMoney(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function fmtSignedMoney(v) {
  if (v === null || v === undefined) return "—";
  return (v > 0 ? "+" : "") + fmtMoney(v);
}

function fmtPct(v) {
  if (v === null || v === undefined) return "—";
  return (v > 0 ? "+" : "") + v.toFixed(2) + "%";
}

function fmtQty(v) {
  if (v === null || v === undefined) return "—";
  return Number(v).toLocaleString("en-US", { maximumFractionDigits: 6 });
}

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("en-US", {
    month: "short", day: "numeric", year: "numeric",
    hour: "numeric", minute: "2-digit",
  });
}

function changeClass(v) {
  if (v === null || v === undefined) return "";
  return v > 0 ? "gain" : v < 0 ? "loss" : "";
}

function esc(s) {
  const div = document.createElement("div");
  div.textContent = s === null || s === undefined ? "" : String(s);
  return div.innerHTML;
}

function toast(message, kind = "info") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = message;
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

/* Buying-power chip in the nav, shared by all pages. */
async function refreshNavAccount() {
  try {
    const acct = await API.get("/api/account");
    document.getElementById("nav-buying-power").textContent = fmtMoney(acct.buying_power);
    return acct;
  } catch (e) {
    return null;
  }
}

document.addEventListener("DOMContentLoaded", refreshNavAccount);
/* Pages dispatch this after any order/transfer so shared UI stays fresh. */
document.addEventListener("portfolio:changed", refreshNavAccount);
