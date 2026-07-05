/* Browse page: watchlist + popular lists with quotes, typeahead search,
   star-to-watch, and buy/sell. */

(function () {
  const watchBody = document.getElementById("watchlist-body");
  const popularBody = document.getElementById("popular-body");
  const search = document.getElementById("stock-search");
  const results = document.getElementById("search-results");
  let searchTimer = null;

  function rowHtml(s) {
    const on = s.watched;
    return `
      <tr class="clickable" data-symbol="${esc(s.symbol)}">
        <td class="star-col">
          <button class="star ${on ? "on" : ""}" data-action="toggle-watch"
                  data-symbol="${esc(s.symbol)}" data-watched="${on ? "1" : "0"}"
                  title="${on ? "Remove from watchlist" : "Add to watchlist"}"
                  aria-label="${on ? "Remove from watchlist" : "Add to watchlist"}">${on ? "★" : "☆"}</button>
        </td>
        <td class="sym">${esc(s.symbol)}</td>
        <td class="muted">${esc(s.name)}</td>
        <td class="num">${fmtMoney(s.price)}</td>
        <td class="num ${changeClass(s.change_pct)}">${fmtPct(s.change_pct)}</td>
        <td class="num">
          <div class="row-actions">
            <button class="btn btn-buy btn-sm" data-action="buy">Buy</button>
            <button class="btn btn-sell btn-sm" data-action="sell">Sell</button>
          </div>
        </td>
      </tr>`;
  }

  async function loadStocks() {
    try {
      const { stocks } = await API.get("/api/stocks");
      const watched = stocks.filter((s) => s.watched);
      const popular = stocks.filter((s) => !s.watched);
      watchBody.innerHTML = watched.length
        ? watched.map(rowHtml).join("")
        : `<tr><td colspan="6" class="empty-note">No saved stocks yet — tap ☆ on any stock to add it here.</td></tr>`;
      popularBody.innerHTML = popular.length
        ? popular.map(rowHtml).join("")
        : `<tr><td colspan="6" class="empty-note">Nothing to show.</td></tr>`;
    } catch (e) {
      popularBody.innerHTML = `<tr><td colspan="6" class="empty-note">Failed to load stocks: ${esc(e.message)}</td></tr>`;
    }
  }

  async function onBodyClick(ev) {
    const star = ev.target.closest("[data-action='toggle-watch']");
    if (star) {
      ev.stopPropagation();
      const symbol = star.dataset.symbol;
      try {
        if (star.dataset.watched === "1") {
          await API.del(`/api/watchlist/${encodeURIComponent(symbol)}`);
        } else {
          await API.post("/api/watchlist", { symbol });
        }
        await loadStocks();
      } catch (e) {
        toast(e.message, "error");
      }
      return;
    }
    const row = ev.target.closest("tr[data-symbol]");
    if (!row) return;
    const action = ev.target.closest("button[data-action]");
    if (action) {
      OrderPanel.open(row.dataset.symbol, action.dataset.action);
    } else {
      window.location.href = `/stock/${encodeURIComponent(row.dataset.symbol)}`;
    }
  }

  watchBody.addEventListener("click", onBodyClick);
  popularBody.addEventListener("click", onBodyClick);

  /* --- typeahead search over the full symbol catalog --- */

  search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    const q = search.value.trim();
    if (!q) { results.hidden = true; return; }
    searchTimer = setTimeout(() => runSearch(q), 200);
  });

  async function runSearch(q) {
    try {
      const data = await API.get(`/api/stocks/search?q=${encodeURIComponent(q)}`);
      if (!data.results.length) {
        results.innerHTML = `<div class="result"><span class="muted">No matches</span></div>`;
      } else {
        results.innerHTML = data.results.map((r) => `
          <div class="result" data-symbol="${esc(r.symbol)}">
            <span class="sym">${esc(r.symbol)}</span>
            <span class="name">${esc(r.name)}</span>
          </div>`).join("");
      }
      results.hidden = false;
    } catch (e) { /* keep the old results visible */ }
  }

  results.addEventListener("click", async (ev) => {
    const item = ev.target.closest(".result[data-symbol]");
    if (!item) return;
    const symbol = item.dataset.symbol;
    results.hidden = true;
    search.value = "";
    window.location.href = `/stock/${encodeURIComponent(symbol)}`;
  });

  document.addEventListener("click", (ev) => {
    if (!ev.target.closest(".search-wrap")) results.hidden = true;
  });

  document.addEventListener("portfolio:changed", loadStocks);
  loadStocks();
  setInterval(loadStocks, 30000); // keep prices fresh
})();
