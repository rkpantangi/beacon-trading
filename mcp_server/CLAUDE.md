# beacon-trading-mcp-server

MCP server exposing the Beacon Trading app's HTTP API as MCP tools.
Design, phases, and decisions: see PLAN.md. API contract:
../trading_app/docs/api.md (source of truth — models mirror it exactly).

## Dev commands

- `uv` is at ~/.local/bin (not on PATH by default)
- Run tests: `uv run pytest` — includes live integration tests that
  auto-skip unless the trading app is running
- Start the trading app: `../trading_app/run.sh` (serves on 127.0.0.1:8321)
- Run this server manually: `uv run beacon-trading-mcp-server` (stdio)

## Conventions

- Money is Decimal, never float
- Tools stay thin: business logic belongs in the client layer, and tools
  depend only on the TradingApiClient protocol (client/base.py)
- Business-rule refusals are data (can_place=false, status="rejected"),
  not exceptions; TradingApiError is only for malformed requests (HTTP 400)
- The two-step order flow (review token required to place) is enforced in
  the MCP layer by design — the HTTP API treats the token as optional
- TRADING_API_MODE=fake runs the in-memory client (tests/demos);
  default is http against the live app

## Coordination

- The trading app is developed in a separate Claude session at
  ../trading_app — breaking changes to docs/api.md must be coordinated;
  tests/test_http_integration.py is the early-warning net
