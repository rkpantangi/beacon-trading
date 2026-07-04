# Beacon Trading — paper-trading app

A minimal trading application for testing MCP integrations.
One customer, fake money, delayed public market data — but real order
mechanics: market & limit orders, reservations, cancels, deposits and
withdrawals.

## Run

```bash
./run.sh
# → http://127.0.0.1:8321        (UI)
# → http://127.0.0.1:8321/docs   (interactive OpenAPI docs)
```

First run creates a `.venv`, installs dependencies, downloads the US symbol
catalog (~12.9k tickers from the NASDAQ Trader symbol directory, refreshed
weekly), and seeds one account (`acct-1`) with **$0** — make a deposit on the
Balances page before trading.

## Pages

| Page | What it does |
|---|---|
| **Browse** (`/`) | Search any US ticker/company, stock list with delayed prices, Buy/Sell buttons open a slide-in order ticket (market & limit) |
| **Positions** | Holdings with avg cost, market value, unrealized P/L |
| **Orders** | Open orders (cancelable) + full order history with status filters |
| **History** | Every transaction: buys, sells, deposits, withdrawals |
| **Balances** | Cash / reserved / buying power / equity, instant fake-bank deposit & withdraw |

Dark & light mode via the toggle in the nav bar.

## REST API

All under `/api`; the default account is implied (`?account_id=` is accepted
everywhere for future multi-customer use).

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/stocks` | Browse list (popular + watchlist) with quotes |
| GET | `/api/stocks/search?q=` | Typeahead search over the full symbol catalog |
| GET | `/api/stocks/{symbol}` | Quote for one symbol |
| GET | `/api/quotes?symbols=` | Batch quotes (comma-separated, ≤50) |
| POST | `/api/watchlist` | Add a symbol to the browse list |
| DELETE | `/api/watchlist/{symbol}` | Remove it |
| GET | `/api/accounts` | All account summaries |
| GET | `/api/account` | Cash, reserved, buying power, equity, day change, P/L |
| GET | `/api/positions` | Holdings with P/L and day change |
| GET | `/api/orders?status=` | Orders (`open` uses the fast open-orders file) |
| POST | `/api/orders/review` | Preview an order; returns single-use `review_token` |
| POST | `/api/orders` | Place `{symbol, side, qty, type, limit_price?, review_token?}` |
| POST | `/api/orders/{id}/cancel` | Cancel an open order |
| GET | `/api/transactions?type=` | Transaction history |
| POST | `/api/transfers` | `{type: deposit\|withdraw, amount}` — settles instantly |

The full external-client contract (used by the MCP server) lives in
[`docs/api.md`](docs/api.md), with a static OpenAPI snapshot in
[`docs/openapi.json`](docs/openapi.json).

## Order semantics

- **Market** orders fill immediately at the latest fetched price (Yahoo
  Finance chart endpoint, cached 5 min — delayed data by design).
- **Limit** orders rest in `data/open_orders.json`; a background task checks
  every 60s and fills when the price crosses the limit. Cash (limit buys) and
  shares (limit sells) are reserved while an order is open.
- Buys are rejected beyond buying power; sells beyond unreserved shares. No
  shorting, no margin.

## Architecture

```
app/
├── models.py        # Account, Position, Order, Transaction dataclasses
├── storage/
│   ├── base.py      # abstract repos (AccountRepo, OrderRepo, …) — swap in a
│   │                #   SQL implementation later without touching logic
│   └── file_store.py# text-file implementation (atomic writes + lock)
├── symbols.py       # NASDAQ Trader symbol catalog download + search
├── prices.py        # PriceProvider interface + Yahoo implementation + cache
├── trading.py       # TradingService: all business rules
├── api.py           # REST routes
└── main.py          # FastAPI wiring, page routes, background order filler
```

Data lives in plain text files under `data/`:

| File | Contents |
|---|---|
| `accounts.json` | Accounts and cash balances |
| `positions.json` | Holdings per account |
| `open_orders.json` | Working orders only (fast access) |
| `orders.jsonl` | Append-only log of **every** order state transition |
| `transactions.jsonl` | Append-only log of fills, deposits, withdrawals |
| `symbols.json` | Cached symbol catalog |
| `watchlists.json` | User-added browse symbols |

The UI is just another client of the REST API, so an MCP server can be built
directly on the same endpoints (see `/docs` for the schema).
