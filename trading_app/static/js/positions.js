/* Positions page: holdings with P/L + portfolio summary cards. */

(function () {
  const body = document.getElementById("positions-body");
  const cards = document.getElementById("summary-cards");

  function statCard(label, value, cls = "") {
    return `<div class="stat-card"><div class="label">${label}</div>
            <div class="value ${cls}">${value}</div></div>`;
  }

  async function load() {
    try {
      const [{ positions }, acct] = await Promise.all([
        API.get("/api/positions"),
        API.get("/api/account"),
      ]);

      const totalPl = positions.reduce((s, p) => s + (p.unrealized_pl || 0), 0);
      cards.innerHTML =
        statCard("Total equity", fmtMoney(acct.total_equity)) +
        statCard("Positions value", fmtMoney(acct.positions_value)) +
        statCard("Cash", fmtMoney(acct.cash_balance)) +
        statCard("Unrealized P/L", fmtSignedMoney(totalPl), changeClass(totalPl));

      if (!positions.length) {
        body.innerHTML = `<tr><td colspan="8" class="empty-note">
          No positions yet — head to <a href="/">Browse</a> to place your first trade.</td></tr>`;
        return;
      }
      body.innerHTML = positions.map((p) => `
        <tr class="clickable" data-symbol="${esc(p.symbol)}">
          <td class="sym">${esc(p.symbol)}</td>
          <td class="company-col muted">${esc(p.name)}</td>
          <td class="num">${fmtQty(p.qty)}</td>
          <td class="num">${fmtMoney(p.avg_cost)}</td>
          <td class="num">${fmtMoney(p.price)}</td>
          <td class="num">${fmtMoney(p.market_value)}</td>
          <td class="num ${changeClass(p.unrealized_pl)}">
            ${fmtSignedMoney(p.unrealized_pl)}
            <span class="muted">(${fmtPct(p.unrealized_pl_pct)})</span>
          </td>
          <td class="num">
            <div class="row-actions">
              <button class="btn btn-buy btn-sm" data-action="buy">Buy</button>
              <button class="btn btn-sell btn-sm" data-action="sell">Sell</button>
            </div>
          </td>
        </tr>`).join("");
    } catch (e) {
      body.innerHTML = `<tr><td colspan="8" class="empty-note">Failed to load: ${esc(e.message)}</td></tr>`;
    }
  }

  body.addEventListener("click", (ev) => {
    const row = ev.target.closest("tr[data-symbol]");
    if (!row) return;
    const action = ev.target.closest("button[data-action]");
    if (action) {
      OrderPanel.open(row.dataset.symbol, action.dataset.action);
    } else {
      window.location.href = `/stock/${encodeURIComponent(row.dataset.symbol)}`;
    }
  });

  document.addEventListener("portfolio:changed", load);
  load();
  setInterval(load, 30000);
})();
