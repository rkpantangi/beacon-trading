(function () {
  const symbol = window.STOCK_SYMBOL;
  if (!symbol) return;

  const els = {
    exchange: document.getElementById("detail-exchange"),
    name: document.getElementById("detail-name"),
    price: document.getElementById("detail-price"),
    change: document.getElementById("detail-change"),
    asOf: document.getElementById("detail-as-of"),
    prevClose: document.getElementById("stat-prev-close"),
    volume: document.getElementById("stat-volume"),
    dayRange: document.getElementById("stat-day-range"),
    yearRange: document.getElementById("stat-year-range"),
    sector: document.getElementById("profile-sector"),
    industry: document.getElementById("profile-industry"),
    btnBuy: document.getElementById("btn-buy-stock"),
    btnSell: document.getElementById("btn-sell-stock"),
    watchBtn: document.getElementById("btn-watch-stock"),
    rangesContainer: document.getElementById("chart-ranges"),
  };

  let isWatched = false;
  let chartInstance = null;
  let currentRange = "1mo";

  async function loadDetails() {
    try {
      const [details, watchlistData] = await Promise.all([
        API.get(`/api/stocks/${encodeURIComponent(symbol)}/details`),
        API.get("/api/watchlist").catch(() => ({ watchlist: [] })),
      ]);
      
      els.exchange.textContent = details.exchange || "US";
      els.name.textContent = details.name || "";
      els.price.textContent = fmtMoney(details.price);
      
      const changeVal = details.change;
      const changePct = details.change_pct;
      if (changeVal !== null && changePct !== null) {
        const sign = changeVal > 0 ? "+" : "";
        els.change.textContent = `${sign}${changeVal.toFixed(2)} (${sign}${changePct.toFixed(2)}%)`;
        els.change.className = "detail-change " + changeClass(changePct);
      } else {
        els.change.textContent = "—";
        els.change.className = "detail-change";
      }

      if (details.as_of) {
        els.asOf.textContent = fmtDate(new Date(details.as_of * 1000).toISOString());
      } else {
        els.asOf.textContent = "—";
      }

      els.prevClose.textContent = fmtMoney(details.prev_close);
      els.volume.textContent = details.volume ? details.volume.toLocaleString() : "—";

      const dayLow = details.day_low;
      const dayHigh = details.day_high;
      els.dayRange.textContent = (dayLow !== null && dayHigh !== null)
        ? `${fmtMoney(dayLow)} - ${fmtMoney(dayHigh)}`
        : "—";

      const yrLow = details.fifty_two_week_low;
      const yrHigh = details.fifty_two_week_high;
      els.yearRange.textContent = (yrLow !== null && yrHigh !== null)
        ? `${fmtMoney(yrLow)} - ${fmtMoney(yrHigh)}`
        : "—";

      els.sector.textContent = details.sector || "—";
      els.industry.textContent = details.industry || "—";

      isWatched = watchlistData.watchlist.some(item => item.symbol === symbol);
      els.watchBtn.textContent = isWatched ? "★" : "☆";
      els.watchBtn.className = "star" + (isWatched ? " on" : "");
      els.watchBtn.title = isWatched ? "Remove from watchlist" : "Add to watchlist";

    } catch (e) {
      toast("Failed to load asset details: " + e.message, "error");
    }
  }

  // Format date helper for the chart labels
  function formatChartLabel(timestamp, range) {
    const date = new Date(timestamp * 1000);
    if (range === "1d") {
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } else if (range === "5d") {
      return date.toLocaleDateString([], { month: 'short', day: 'numeric' }) + " " + 
             date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } else if (range === "1mo") {
      return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
    } else {
      return date.toLocaleDateString([], { month: 'short', year: '2-digit' });
    }
  }

  async function loadChart(range) {
    try {
      currentRange = range;
      const chartRes = await API.get(`/api/stocks/${encodeURIComponent(symbol)}/chart?range=${range}`);
      const dataPoints = chartRes.data || [];
      
      if (dataPoints.length === 0) {
        return;
      }

      const labels = dataPoints.map(d => formatChartLabel(d.timestamp, range));
      const prices = dataPoints.map(d => d.close);

      // Fetch completed orders for this symbol to display on the chart
      let orders = [];
      try {
        const ordersRes = await API.get(`/api/orders?status=filled&symbol=${encodeURIComponent(symbol)}`);
        orders = ordersRes.orders || [];
      } catch (err) {
        console.error("Failed to load orders for chart:", err);
      }

      const buysData = new Array(dataPoints.length).fill(null);
      const sellsData = new Array(dataPoints.length).fill(null);
      const buysOrders = Array.from({ length: dataPoints.length }, () => []);
      const sellsOrders = Array.from({ length: dataPoints.length }, () => []);

      if (orders.length > 0 && dataPoints.length > 0) {
        const startSec = dataPoints[0].timestamp;
        const endSec = dataPoints[dataPoints.length - 1].timestamp;

        for (const o of orders) {
          const orderTimeMs = Date.parse(o.filled_at || o.created_at);
          if (isNaN(orderTimeMs)) continue;
          const orderTimeSec = orderTimeMs / 1000;

          // Align orders with a weekend/holiday buffer window (4 days)
          if (orderTimeSec >= startSec - 345600 && orderTimeSec <= endSec + 345600) {
            let closestIdx = -1;
            let minDiff = Infinity;
            for (let i = 0; i < dataPoints.length; i++) {
              const diff = Math.abs(dataPoints[i].timestamp - orderTimeSec);
              if (diff < minDiff) {
                minDiff = diff;
                closestIdx = i;
              }
            }

            if (closestIdx !== -1) {
              const price = o.fill_price || o.limit_price || dataPoints[closestIdx].close;
              if (o.side === "buy") {
                buysData[closestIdx] = price;
                buysOrders[closestIdx].push(o);
              } else {
                sellsData[closestIdx] = price;
                sellsOrders[closestIdx].push(o);
              }
            }
          }
        }
      }

      // Determine if net positive or negative
      const firstPrice = prices[0];
      const lastPrice = prices[prices.length - 1];
      const isUp = lastPrice >= firstPrice;

      // Extract colors from theme
      const style = getComputedStyle(document.documentElement);
      const gainColor = style.getPropertyValue('--gain').trim() || '#089981';
      const lossColor = style.getPropertyValue('--loss').trim() || '#f23645';
      const mutedColor = style.getPropertyValue('--muted').trim() || '#5f6b7f';
      const borderColor = style.getPropertyValue('--border').trim() || '#e3e8f0';

      const activeColor = isUp ? gainColor : lossColor;

      const ctx = document.getElementById("stock-chart").getContext("2d");
      
      if (chartInstance) {
        chartInstance.destroy();
      }

      const gradient = ctx.createLinearGradient(0, 0, 0, 280);
      if (isUp) {
        gradient.addColorStop(0, 'rgba(8, 203, 129, 0.16)');
        gradient.addColorStop(1, 'rgba(8, 203, 129, 0.00)');
      } else {
        gradient.addColorStop(0, 'rgba(246, 70, 93, 0.16)');
        gradient.addColorStop(1, 'rgba(246, 70, 93, 0.00)');
      }

      chartInstance = new Chart(ctx, {
        type: "line",
        data: {
          labels: labels,
          datasets: [
            {
              label: "Price",
              data: prices,
              borderColor: activeColor,
              borderWidth: 2.5,
              fill: true,
              backgroundColor: gradient,
              pointRadius: 0,
              pointHoverRadius: 5,
              pointHoverBackgroundColor: activeColor,
              pointHoverBorderColor: "#ffffff",
              pointHoverBorderWidth: 1.5,
              tension: 0.1
            },
            {
              label: "Buys",
              data: buysData,
              borderColor: "transparent",
              backgroundColor: gainColor,
              pointStyle: "circle",
              pointRadius: 5,
              pointHoverRadius: 7,
              pointBackgroundColor: gainColor,
              pointBorderColor: "#ffffff",
              pointBorderWidth: 1.5,
              showLine: false,
              fill: false
            },
            {
              label: "Sells",
              data: sellsData,
              borderColor: "transparent",
              backgroundColor: lossColor,
              pointStyle: "circle",
              pointRadius: 5,
              pointHoverRadius: 7,
              pointBackgroundColor: lossColor,
              pointBorderColor: "#ffffff",
              pointBorderWidth: 1.5,
              showLine: false,
              fill: false
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              display: false
            },
            tooltip: {
              enabled: true,
              mode: "index",
              intersect: false,
              backgroundColor: style.getPropertyValue('--surface').trim() || '#ffffff',
              titleColor: style.getPropertyValue('--text').trim() || '#1a1f2b',
              bodyColor: style.getPropertyValue('--text').trim() || '#1a1f2b',
              borderColor: borderColor,
              borderWidth: 1,
              padding: 10,
              displayColors: false,
              callbacks: {
                label: function(context) {
                  const datasetIdx = context.datasetIndex;
                  const idx = context.dataIndex;
                  if (datasetIdx === 0) {
                    return `Price: ${fmtMoney(context.parsed.y)}`;
                  } else if (datasetIdx === 1) {
                    const list = buysOrders[idx];
                    if (list && list.length > 0) {
                      return list.map(o => {
                        const p = o.fill_price || o.limit_price;
                        return `🟢 Bought ${fmtQty(o.qty)} @ ${fmtMoney(p)}`;
                      });
                    }
                  } else if (datasetIdx === 2) {
                    const list = sellsOrders[idx];
                    if (list && list.length > 0) {
                      return list.map(o => {
                        const p = o.fill_price || o.limit_price;
                        return `🔴 Sold ${fmtQty(o.qty)} @ ${fmtMoney(p)}`;
                      });
                    }
                  }
                  return null;
                }
              }
            }
          },
          scales: {
            x: {
              grid: {
                display: false
              },
              ticks: {
                color: mutedColor,
                maxTicksLimit: 7,
                font: {
                  size: 11,
                  weight: '500'
                }
              }
            },
            y: {
              grid: {
                color: borderColor
              },
              ticks: {
                color: mutedColor,
                font: {
                  size: 11
                },
                callback: function(value) {
                  return fmtMoney(value);
                }
              }
            }
          }
        }
      });

    } catch (e) {
      console.error("Failed to load chart data:", e);
    }
  }

  // Setup timeframe buttons
  els.rangesContainer.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".timeframe-btn");
    if (!btn) return;
    
    // Toggle active state
    els.rangesContainer.querySelectorAll(".timeframe-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    
    // Load range
    loadChart(btn.dataset.range);
  });

  els.btnBuy.addEventListener("click", () => {
    OrderPanel.open(symbol, "buy");
  });

  els.btnSell.addEventListener("click", () => {
    OrderPanel.open(symbol, "sell");
  });

  els.watchBtn.addEventListener("click", async () => {
    els.watchBtn.disabled = true;
    try {
      if (isWatched) {
        await API.del(`/api/watchlist/${encodeURIComponent(symbol)}`);
        isWatched = false;
        toast("Removed from watchlist", "success");
      } else {
        await API.post("/api/watchlist", { symbol });
        isWatched = true;
        toast("Added to watchlist", "success");
      }
      els.watchBtn.textContent = isWatched ? "★" : "☆";
      els.watchBtn.className = "star" + (isWatched ? " on" : "");
      els.watchBtn.title = isWatched ? "Remove from watchlist" : "Add to watchlist";
      document.dispatchEvent(new CustomEvent("portfolio:changed"));
    } catch (e) {
      toast(e.message, "error");
    } finally {
      els.watchBtn.disabled = false;
    }
  });

  // Keep theme changes monitored to refresh chart colors if theme toggles
  document.getElementById("theme-toggle").addEventListener("click", () => {
    // Wait for dataset theme to toggle (which runs inside base.html click handler)
    setTimeout(() => {
      if (chartInstance) {
        loadChart(currentRange);
      }
    }, 50);
  });

  document.addEventListener("portfolio:changed", loadDetails);
  loadDetails();
  loadChart("1mo"); // Default to 1 Month chart
})();
