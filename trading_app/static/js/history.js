/* History page: all transactions (trades + transfers). */

(function () {
  const body = document.getElementById("txns-body");
  const typeFilter = document.getElementById("type-filter");

  const chipClass = { buy: "buy", sell: "withdraw", deposit: "deposit", withdraw: "withdraw" };

  async function load() {
    const type = typeFilter.value;
    try {
      const { transactions } = await API.get(`/api/transactions${type ? `?type=${type}` : ""}`);
      if (!transactions.length) {
        body.innerHTML = `<tr><td colspan="6" class="empty-note">No transactions yet.</td></tr>`;
        return;
      }
      body.innerHTML = transactions.map((t) => `
        <tr>
          <td class="muted">${fmtDate(t.timestamp)}</td>
          <td><span class="chip ${chipClass[t.type] || ""}">${esc(t.type)}</span></td>
          <td>${esc(t.description)}</td>
          <td class="num">${t.qty !== null && t.qty !== undefined ? fmtQty(t.qty) : "—"}</td>
          <td class="num">${fmtMoney(t.price)}</td>
          <td class="num ${changeClass(t.amount)}">${fmtSignedMoney(t.amount)}</td>
        </tr>`).join("");
    } catch (e) {
      body.innerHTML = `<tr><td colspan="6" class="empty-note">Failed to load: ${esc(e.message)}</td></tr>`;
    }
  }

  typeFilter.addEventListener("change", load);
  document.addEventListener("portfolio:changed", load);
  load();
})();
