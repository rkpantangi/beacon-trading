# Beacon Trading (trading app)

Paper-trading app: FastAPI + vanilla-JS UI, one fake
customer, delayed real market data. Overview and pages: README.md.

## Dev commands

- Run: `./run.sh` (creates .venv on first run; serves 127.0.0.1:8321;
  UI at /, OpenAPI docs at /docs)
- After changing routes/schemas: regenerate the spec snapshot with
  `.venv/bin/python -m scripts.dump_openapi` and update docs/api.md

## Things that bite

- **docs/api.md is a published contract.** The MCP server at ../mcp_server
  (separate Claude session) consumes it; its models mirror these schemas
  exactly. Coordinate breaking changes — its integration suite is
  ../mcp_server/tests/test_http_integration.py.
- data/*.json|jsonl is the persistent state (accounts, orders, positions,
  transactions). Deleting it resets the "brokerage"; don't wipe casually.
- Prices come from Yahoo chart data, cached ~5 min — tests asserting on
  exact prices will flake.
- A background task fills resting limit orders every 60s at the prevailing
  price; open limit buys reserve cash, open limit sells reserve shares.
- Business refusals return HTTP 200 with status="rejected" + reject_reason;
  only malformed input gets 400. Keep this — clients depend on it.
- Money is USD floats rounded to cents; timestamps ISO-8601 UTC.
- Single account acct-1; every endpoint accepts ?account_id= for future
  multi-customer use.
