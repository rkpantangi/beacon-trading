/* Balances page: account summary + instant deposit/withdraw (fake bank). */

(function () {
  const cards = document.getElementById("balance-cards");
  const transfersBody = document.getElementById("transfers-body");

  function statCard(label, value, cls = "") {
    return `<div class="stat-card"><div class="label">${label}</div>
            <div class="value ${cls}">${value}</div></div>`;
  }

  async function load() {
    try {
      const acct = await API.get("/api/account");
      cards.innerHTML =
        statCard("Cash balance", fmtMoney(acct.cash_balance)) +
        statCard("Reserved (open orders)", fmtMoney(acct.reserved_cash)) +
        statCard("Buying power", fmtMoney(acct.buying_power)) +
        statCard("Positions value", fmtMoney(acct.positions_value)) +
        statCard("Total equity", fmtMoney(acct.total_equity));
    } catch (e) {
      cards.innerHTML = `<div class="stat-card"><div class="label">Error</div>
        <div class="value loss">${esc(e.message)}</div></div>`;
    }
    loadTransfers();
  }

  async function loadTransfers() {
    try {
      const [deps, wds] = await Promise.all([
        API.get("/api/transactions?type=deposit"),
        API.get("/api/transactions?type=withdraw"),
      ]);
      const transfers = deps.transactions.concat(wds.transactions)
        .sort((a, b) => b.timestamp.localeCompare(a.timestamp)).slice(0, 20);
      if (!transfers.length) {
        transfersBody.innerHTML = `<tr><td colspan="4" class="empty-note">No transfers yet — make your first deposit above.</td></tr>`;
        return;
      }
      transfersBody.innerHTML = transfers.map((t) => `
        <tr>
          <td class="muted">${fmtDate(t.timestamp)}</td>
          <td><span class="chip ${t.type === "deposit" ? "deposit" : "withdraw"}">${esc(t.type)}</span></td>
          <td>${esc(t.description)}</td>
          <td class="num ${changeClass(t.amount)}">${fmtSignedMoney(t.amount)}</td>
        </tr>`).join("");
    } catch (e) {
      transfersBody.innerHTML = `<tr><td colspan="4" class="empty-note">Failed to load: ${esc(e.message)}</td></tr>`;
    }
  }

  function wireForm(formId, inputId, errorId, type, verb) {
    const form = document.getElementById(formId);
    const input = document.getElementById(inputId);
    const error = document.getElementById(errorId);
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      error.hidden = true;
      const amount = parseFloat(input.value);
      if (!amount || amount <= 0) {
        error.textContent = "Enter an amount greater than zero.";
        error.hidden = false;
        return;
      }
      try {
        await API.post("/api/transfers", { type, amount });
        toast(`${verb} ${fmtMoney(amount)} — settled instantly`, "success");
        input.value = "";
        document.dispatchEvent(new CustomEvent("portfolio:changed"));
      } catch (e) {
        error.textContent = e.message;
        error.hidden = false;
      }
    });
  }

  wireForm("deposit-form", "deposit-amount", "deposit-error", "deposit", "Deposited");
  wireForm("withdraw-form", "withdraw-amount", "withdraw-error", "withdraw", "Withdrew");

  document.addEventListener("portfolio:changed", load);
  load();
})();
