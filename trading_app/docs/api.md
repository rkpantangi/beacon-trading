# Beacon Trading — HTTP API contract

For MCP-server and other external clients. Machine-readable spec: live at
`GET /openapi.json`, static snapshot in [`docs/openapi.json`](openapi.json)
(regenerate with `.venv/bin/python -m scripts.dump_openapi`).

## Connection

- **Base URL (local dev):** `http://127.0.0.1:8321` — start with `./run.sh`
- **Auth:** none. Single fake customer, local-only app. All endpoints accept
  `?account_id=` (defaults to `acct-1`) for future multi-customer use.
- **Content type:** JSON everywhere. Errors are `{"detail": "<message>"}` with
  HTTP 400 (validation/business rule) or 404 (unknown resource).
- Money is USD floats rounded to cents; timestamps are ISO-8601 UTC.

## Market data

### `GET /api/stocks/search?q=<text>&limit=15`
Typeahead search over ~12.5k US-listed symbols (ticker prefix + company-name
substring; exact ticker match ranks first).

```json
{"results": [{"symbol": "MSFT", "name": "Microsoft Corporation",
              "exchange": "NASDAQ", "etf": false}]}
```

### `GET /api/quotes?symbols=AAPL,MSFT,BRK-B`
Batch quotes (≤50 symbols, comma-separated; `.` class notation is normalized
to `-`). Unknown/unpriceable symbols map to `null`. Prices are delayed
(Yahoo chart data, cached ~5 min) — that is the app's "prevailing price".

```json
{"quotes": {"AAPL": {"symbol": "AAPL", "name": "Apple Inc.", "price": 308.63,
                     "prev_close": 294.38, "change": 14.25, "change_pct": 4.84,
                     "currency": "USD", "as_of": 1783053723.45}, "ZZZZ": null}}
```

Also available: `GET /api/stocks` (default browse list w/ quotes) and
`GET /api/stocks/{symbol}` (single quote + catalog info, 404 if unknown).

## Portfolio

### `GET /api/accounts` / `GET /api/account`
List of account summaries / the default account's summary:

```json
{"account_id": "acct-1", "name": "Ram",
 "cash_balance": 20913.70, "reserved_cash": 700.0, "buying_power": 20213.70,
 "positions_value": 3086.30, "total_equity": 24000.00,
 "unrealized_pl": 0.0, "day_change": 142.50, "day_change_pct": 4.84}
```

`reserved_cash` backs open limit buys; `buying_power = cash − reserved`.
`day_change` is the positions' change vs. previous close ($ and %).

### `GET /api/positions`

```json
{"positions": [{"symbol": "AAPL", "name": "Apple Inc.", "qty": 10,
                "avg_cost": 308.63, "price": 308.63, "market_value": 3086.30,
                "cost_basis": 3086.30, "unrealized_pl": 0.0,
                "unrealized_pl_pct": 0.0, "day_change": 142.50,
                "day_change_pct": 4.84}]}
```

### `GET /api/orders?status=open|filled|canceled|rejected`
Orders newest-first (omit `status` for all). Order shape:

```json
{"id": "ord-662c3118c65d", "account_id": "acct-1", "symbol": "AAPL",
 "side": "buy", "qty": 10.0, "order_type": "market", "status": "filled",
 "limit_price": null, "fill_price": 308.63,
 "created_at": "2026-07-03T04:20:11+00:00", "updated_at": "…",
 "filled_at": "…", "canceled_at": null, "reject_reason": null}
```

`side`: `buy|sell` · `order_type`: `market|limit` ·
`status`: `open|filled|canceled|rejected` (rejections carry `reject_reason`).

### `GET /api/transactions?type=buy|sell|deposit|withdraw`
Cash-affecting events newest-first. `amount` is the signed cash effect
(deposits/sells +, withdrawals/buys −).

## Watchlist

Per-account saved shortlist of symbols. Purely a convenience list — it has no
effect on trading, positions, or reservations.

### `GET /api/watchlist`
The account's saved symbols, newest-added first, each enriched with a quote
(`null` price fields for unpriceable symbols):

```json
{"watchlist": [{"symbol": "NVDA", "name": "NVIDIA Corporation",
                "exchange": "NASDAQ", "price": 178.42, "change": 2.10,
                "change_pct": 1.19}]}
```

### `POST /api/watchlist`
Body `{"symbol": "NVDA"}`. Adds the symbol (idempotent; deduped, newest first).
Unknown symbols are 404. Returns `{"ok": true, "symbol": "NVDA"}` with the
catalog-canonical symbol.

### `DELETE /api/watchlist/{symbol}`
Removes the symbol (no-op if absent). Returns `{"ok": true}`.

## Orders — two-step flow

### 1. `POST /api/orders/review`
Body: `{"symbol", "side", "qty", "type", "limit_price"?}`. Never mutates
state. Returns the preview and, **only when `can_place` is true**, a
single-use `review_token` (5-minute TTL) bound to these exact parameters:

```json
{"review": {"symbol": "MSFT", "side": "buy", "qty": 2, "order_type": "market",
            "limit_price": null, "market_price": 390.49,
            "estimated_price": 390.49, "estimated_amount": 780.98,
            "estimated_amount_label": "cost", "buying_power": 20213.70,
            "would_fill_immediately": true, "can_place": true, "reason": null},
 "review_token": "zx2D9Dl5HwX7607VgsFrpw", "review_token_expires_in": 300}
```

Sell reviews return `shares_available` instead of `buying_power`. When the
order would be refused, `can_place` is false, `reason` explains why, and
`review_token` is null. Malformed input (bad side/type/qty, unknown symbol,
missing limit price) is HTTP 400 instead.

### 2. `POST /api/orders`
Same body plus optional `"review_token"`. If provided, it must match an
unexpired review of the **same account + parameters**; it is consumed on
success and rejected with 400 on mismatch/expiry/reuse (a mismatch does not
burn the token). Without a token the order is simply validated and placed
(the web UI's path) — the MCP layer can enforce token use on its side.

Returns `{"order": {…}}` — check `status`: market orders come back `filled`,
resting limits `open`, refusals `rejected` with `reject_reason` (HTTP 200;
only malformed requests get 400).

### `POST /api/orders/{id}/cancel`
Cancels an open order (400 if not open / not found). Returns the updated order.

## Order semantics (for tool descriptions)

- Market orders fill immediately at the prevailing (delayed) price.
- Limit orders rest; a background task (60s) fills them when price crosses
  (buy: price ≤ limit, sell: price ≥ limit) at the prevailing price. A limit
  already marketable at placement fills immediately.
- Open limit buys reserve cash; open limit sells reserve shares. No shorting,
  no margin, no fractional restrictions (any qty > 0).

## Transfers (in scope for balances)

`POST /api/transfers` body `{"type": "deposit"|"withdraw", "amount": >0}` —
instant fake bank; withdrawals capped at `buying_power`. Returns the
transaction and the updated account summary.
