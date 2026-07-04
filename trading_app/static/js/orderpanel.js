/* Order ticket: the right slide-in panel, shared by every page.
   Open with OrderPanel.open("AAPL", "buy"). Dispatches "portfolio:changed"
   on the document after a successful order. */

const OrderPanel = (function () {
  const els = {
    backdrop: document.getElementById("panel-backdrop"),
    panel: document.getElementById("order-panel"),
    symbol: document.getElementById("op-symbol"),
    name: document.getElementById("op-name"),
    price: document.getElementById("op-price"),
    change: document.getElementById("op-change"),
    sideBuy: document.getElementById("op-side-buy"),
    sideSell: document.getElementById("op-side-sell"),
    typeSeg: document.getElementById("op-type-seg"),
    qty: document.getElementById("op-qty"),
    limitRow: document.getElementById("op-limit-row"),
    limit: document.getElementById("op-limit"),
    estLabel: document.getElementById("op-est-label"),
    est: document.getElementById("op-est"),
    avail: document.getElementById("op-avail"),
    error: document.getElementById("op-error"),
    submit: document.getElementById("op-submit"),
    form: document.getElementById("op-form"),
    close: document.getElementById("op-close"),
  };

  const state = { symbol: null, side: "buy", type: "market", quote: null,
                  buyingPower: 0, sharesHeld: 0, busy: false };

  async function open(symbol, side) {
    state.symbol = symbol;
    state.side = side || "buy";
    state.type = "market";
    state.quote = null;
    els.qty.value = "";
    els.limit.value = "";
    hideError();

    els.symbol.textContent = symbol;
    els.name.textContent = "";
    els.price.textContent = "…";
    els.change.textContent = "";
    show();
    render();

    try {
      const [quote, acct, positions] = await Promise.all([
        API.get(`/api/stocks/${encodeURIComponent(symbol)}`),
        API.get("/api/account"),
        API.get("/api/positions"),
      ]);
      state.quote = quote;
      state.buyingPower = acct.buying_power;
      const pos = positions.positions.find((p) => p.symbol === symbol);
      state.sharesHeld = pos ? pos.qty : 0;
      els.name.textContent = quote.name || "";
      els.price.textContent = fmtMoney(quote.price);
      els.change.textContent = fmtPct(quote.change_pct);
      els.change.className = "chg " + changeClass(quote.change_pct);
      if (state.type === "limit" && !els.limit.value && quote.price) {
        els.limit.value = quote.price.toFixed(2);
      }
    } catch (e) {
      showError(e.message);
    }
    render();
    els.qty.focus();
  }

  function show() {
    els.backdrop.hidden = false;
    els.panel.hidden = false;
    requestAnimationFrame(() => {
      els.backdrop.classList.add("show");
      els.panel.classList.add("show");
    });
  }

  function hide() {
    els.backdrop.classList.remove("show");
    els.panel.classList.remove("show");
    setTimeout(() => { els.backdrop.hidden = true; els.panel.hidden = true; }, 220);
  }

  function render() {
    const buy = state.side === "buy";
    els.sideBuy.classList.toggle("active", buy);
    els.sideSell.classList.toggle("active", !buy);
    els.typeSeg.querySelectorAll("button").forEach((b) =>
      b.classList.toggle("active", b.dataset.type === state.type));
    els.limitRow.hidden = state.type !== "limit";
    els.estLabel.textContent = buy ? "Estimated cost" : "Estimated credit";
    els.submit.textContent = state.busy ? "Placing…"
      : `${buy ? "Buy" : "Sell"} ${state.symbol || ""}`;
    els.submit.className = `btn ${buy ? "btn-buy" : "btn-sell"}`;
    els.submit.disabled = state.busy;
    els.avail.textContent = buy
      ? `Buying power: ${fmtMoney(state.buyingPower)}`
      : `Shares held: ${fmtQty(state.sharesHeld)}`;
    renderEstimate();
  }

  function perShare() {
    if (state.type === "limit") return parseFloat(els.limit.value) || null;
    return state.quote ? state.quote.price : null;
  }

  function renderEstimate() {
    const qty = parseFloat(els.qty.value);
    const px = perShare();
    els.est.textContent = qty > 0 && px ? fmtMoney(qty * px) : "—";
  }

  function showError(msg) { els.error.textContent = msg; els.error.hidden = false; }
  function hideError() { els.error.hidden = true; }

  async function submit(ev) {
    ev.preventDefault();
    hideError();
    const qty = parseFloat(els.qty.value);
    if (!qty || qty <= 0) return showError("Enter a quantity greater than zero.");
    const body = { symbol: state.symbol, side: state.side, qty, type: state.type };
    if (state.type === "limit") {
      body.limit_price = parseFloat(els.limit.value);
      if (!body.limit_price || body.limit_price <= 0)
        return showError("Enter a positive limit price.");
    }
    state.busy = true;
    render();
    try {
      const { order } = await API.post("/api/orders", body);
      if (order.status === "rejected") {
        showError(order.reject_reason || "Order rejected.");
      } else {
        toast(order.status === "filled"
          ? `Filled: ${order.side} ${fmtQty(order.qty)} ${order.symbol} @ ${fmtMoney(order.fill_price)}`
          : `Order placed: ${order.side} ${fmtQty(order.qty)} ${order.symbol} limit ${fmtMoney(order.limit_price)}`,
          "success");
        hide();
        document.dispatchEvent(new CustomEvent("portfolio:changed"));
      }
    } catch (e) {
      showError(e.message);
    } finally {
      state.busy = false;
      render();
    }
  }

  els.sideBuy.addEventListener("click", () => { state.side = "buy"; render(); });
  els.sideSell.addEventListener("click", () => { state.side = "sell"; render(); });
  els.typeSeg.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-type]");
    if (!btn) return;
    state.type = btn.dataset.type;
    if (state.type === "limit" && !els.limit.value && state.quote && state.quote.price) {
      els.limit.value = state.quote.price.toFixed(2);
    }
    render();
  });
  els.qty.addEventListener("input", renderEstimate);
  els.limit.addEventListener("input", renderEstimate);
  els.form.addEventListener("submit", submit);
  els.close.addEventListener("click", hide);
  els.backdrop.addEventListener("click", hide);
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !els.panel.hidden) hide();
  });

  return { open };
})();
