/* Orders page: open orders with cancel + filterable full history. */

(function () {
  const openBody = document.getElementById("open-orders-body");
  const allBody = document.getElementById("all-orders-body");
  const statusFilter = document.getElementById("status-filter");

  function sideChip(side) {
    return `<span class="chip ${side === "buy" ? "buy" : "sell"}">${esc(side)}</span>`;
  }

  async function loadOpen() {
    try {
      const { orders } = await API.get("/api/orders?status=open");
      if (!orders.length) {
        openBody.innerHTML = `<tr><td colspan="7" class="empty-note">No open orders.</td></tr>`;
        return;
      }
      openBody.innerHTML = orders.map((o) => `
        <tr>
          <td class="muted">${fmtDate(o.created_at)}</td>
          <td class="sym">${esc(o.symbol)}</td>
          <td>${sideChip(o.side)}</td>
          <td>${esc(o.order_type)}</td>
          <td class="num">${fmtQty(o.qty)}</td>
          <td class="num">${fmtMoney(o.limit_price)}</td>
          <td class="num">
            <button class="btn btn-ghost btn-sm" data-cancel="${esc(o.id)}">Cancel</button>
          </td>
        </tr>`).join("");
    } catch (e) {
      openBody.innerHTML = `<tr><td colspan="7" class="empty-note">Failed to load: ${esc(e.message)}</td></tr>`;
    }
  }

  async function loadAll() {
    const status = statusFilter.value;
    try {
      const { orders } = await API.get(`/api/orders${status ? `?status=${status}` : ""}`);
      if (!orders.length) {
        allBody.innerHTML = `<tr><td colspan="8" class="empty-note">No orders yet.</td></tr>`;
        return;
      }
      allBody.innerHTML = orders.map((o) => `
        <tr title="${o.status === "rejected" ? esc(o.reject_reason || "") : ""}">
          <td class="muted">${fmtDate(o.created_at)}</td>
          <td class="sym">${esc(o.symbol)}</td>
          <td>${sideChip(o.side)}</td>
          <td>${esc(o.order_type)}</td>
          <td class="num">${fmtQty(o.qty)}</td>
          <td class="num">${fmtMoney(o.limit_price)}</td>
          <td class="num">${fmtMoney(o.fill_price)}</td>
          <td><span class="chip ${esc(o.status)}">${esc(o.status)}</span></td>
        </tr>`).join("");
    } catch (e) {
      allBody.innerHTML = `<tr><td colspan="8" class="empty-note">Failed to load: ${esc(e.message)}</td></tr>`;
    }
  }

  openBody.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("button[data-cancel]");
    if (!btn) return;
    btn.disabled = true;
    try {
      await API.post(`/api/orders/${encodeURIComponent(btn.dataset.cancel)}/cancel`, {});
      toast("Order canceled", "success");
      document.dispatchEvent(new CustomEvent("portfolio:changed"));
    } catch (e) {
      toast(e.message, "error");
      btn.disabled = false;
    }
  });

  function reload() { loadOpen(); loadAll(); }
  statusFilter.addEventListener("change", loadAll);
  document.addEventListener("portfolio:changed", reload);
  reload();
  setInterval(reload, 30000); // pick up background limit-order fills
})();
