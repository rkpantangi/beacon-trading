# Trading MCP Server — Plan

A living document. Edit freely; sections marked `[TBD]` are waiting on decisions
or on the trading API being built in the other session.

## Goal

An MCP server that exposes our own Robinhood-style trading API as MCP tools, so
any MCP client (Claude Code, Claude Desktop, Cursor, …) can query the market,
view the portfolio, and place trades against **our** backend. No custom MCP
client — like Robinhood's agentic trading, we ship the server and existing
agents bring their own client.

End-state architecture:

```
MCP client (Claude / custom)
        │  MCP protocol (stdio now, HTTP later)
        ▼
   MCP server  (this repo)
        │  REST/HTTP calls
        ▼
 Trading API  (being built separately — contract TBD)
        │
        ▼
 Trading app / engine / DB
```

## Stack

| Choice | Decision | Why |
|---|---|---|
| Language | Python 3.12+ | Official `mcp` SDK with FastMCP is the fastest way to define typed tools; easy to swap HTTP clients and to test. (TypeScript SDK is the alternative if the trading app ends up TS — revisit then.) |
| MCP SDK | `mcp` (official Anthropic Python SDK, FastMCP API) | Decorator-based tools, handles protocol/transport for us. |
| Package mgmt | `uv` | Fast, single-file lockfile, standard for new Python projects. |
| HTTP client | `httpx` (async) | For calling the trading API. |
| Models | `pydantic` v2 | Tool inputs/outputs get JSON schemas for free; same models can validate API responses. |
| Transport | stdio first, Streamable HTTP later | stdio needs zero infra and works with Claude Code immediately. |
| Testing | `pytest` + `pytest-asyncio`, plus MCP Inspector for manual poking | |

## Repo layout

`beacon_trading/` is just a parent folder for self-contained sibling projects:

```
beacon_trading/
├── trading_app/     # Beacon Trading app + API (built in a separate session)
└── mcp_server/      # this project — own pyproject, venv, git repo, tests
```

Rules: everything for this server stays inside `mcp_server/`; no cross-folder
imports — the MCP server talks to the trading app **only over HTTP**, like any
external consumer. Each project is its own git repo.

## Internal design

Three layers, so the not-yet-built API never blocks us:

```
src/beacon_trading_mcp/
├── server.py          # FastMCP app: transport, lifecycle, tool registration
├── tools/             # MCP tool definitions — thin, no business logic
│   ├── market_data.py #   search, quotes
│   ├── portfolio.py   #   accounts, positions, P&L
│   └── orders.py      #   review / place / cancel / list orders
├── client/
│   ├── base.py        # TradingApiClient protocol (abstract interface)
│   ├── fake.py        # FakeTradingApiClient — in-memory data, works TODAY
│   └── http.py        # HttpTradingApiClient — real API, written once contract lands
├── models.py          # Pydantic models: Quote, Position, Order...
└── config.py          # env-driven: API base URL, credentials, fake vs real
```

Key idea: **tools depend only on the `TradingApiClient` protocol.** We build and
test the whole server against `fake.py` now; when the trading API is ready we
implement `http.py` and flip a config switch. The fake also stays useful forever
as the test double.

### Tool surface (v1 target)

Mirroring the Robinhood-style taxonomy (a real robinhood-trading MCP server's
tool list is our reference):

- **Market data:** `search`, `get_equity_quotes`
- **Portfolio:** `get_accounts` (metadata, cash, buying power), `get_portfolio`
  (valuation snapshot: total value, day change, unrealized P&L),
  `get_equity_positions`, `get_equity_orders`
- **Orders:** `review_equity_order` → `place_equity_order`, `cancel_equity_order`
- **Watchlist:** `get_watchlist`, `add_to_watchlist`, `remove_from_watchlist`
  (brought into the contract 2026-07-04, reversing the earlier out-of-scope
  call; a pure convenience list — no effect on trading/positions/reservations)

Historicals, fundamentals, options, indexes, scans, earnings, P&L history:
later phases, if/when the trading API supports them.

### Safety conventions

- Two-step trading: `review_*_order` returns cost/impact and a `review_token`;
  `place_*_order` requires that token. Prevents an LLM from YOLO-ing an order
  in one call.
- Mutating tools return explicit confirmations (order id, state), never silent
  success.
- Read-only tools marked with `readOnlyHint` annotation so clients can
  auto-approve them.

## Phases

- **Phase 0 — Scaffold.** `uv init`, deps, FastMCP hello-world server with one
  dummy tool, runs over stdio, registered in Claude Code via `claude mcp add`.
  *Proves the plumbing.*
- **Phase 1 — Read-only tools on fake data.** Models, `TradingApiClient`
  protocol, `FakeTradingApiClient` with a handful of tickers/positions, market
  data + portfolio tools, pytest coverage. *Server is demo-able.*
- **Phase 2 — Trading tools on fake data.** Order lifecycle in the fake client
  (pending → filled), review/place/cancel tools. *Full loop works without the
  real API.*
- **Phase 3 — Real API client.** ✅ Done. `http.py` implements the Beacon Trading
  contract (`trading_app/docs/api.md`, base `http://127.0.0.1:8321`, no auth,
  single account `acct-1`). Models mirror the API exactly (statuses
  open/filled/canceled/rejected, no time-in-force, quotes without bid/ask,
  portfolio folded into the account summary). Business refusals are data, not
  errors: reviews return `can_place=false` + reason, placed orders can come
  back `status="rejected"` + reject_reason. The API's review token is optional
  at the HTTP layer; the MCP layer enforces the strict two-step flow by caching
  review bodies per token. Live integration tests in
  `tests/test_http_integration.py` (auto-skip when the app is down).
- **Phase 4 — HTTP transport + hardening.** Streamable HTTP so the server can
  run as a service; authentication for the MCP layer itself; error mapping,
  pagination, rate-limit handling.
- **Phase 5 — Extensions.** Options chains/orders, indexes, scans, earnings,
  MCP resources (e.g. `portfolio://summary`) and prompts — as and when Beacon
  Trade's API grows the corresponding features.

## Resolved questions

- [x] Trading API contract: REST at `http://127.0.0.1:8321`, spec in
  `trading_app/docs/api.md` + `docs/openapi.json` (live at `/openapi.json`).
  App is named **Beacon Trading**, started with `./run.sh`.
- [x] Auth: none (local-only fake app). All endpoints take `?account_id=`,
  default `acct-1`; we expose `TRADING_ACCOUNT_ID` env for future use.
- [x] SDK choice stands: Python (`mcp` SDK), talking to the app over HTTP only.
