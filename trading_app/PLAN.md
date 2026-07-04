# Beacon Trading — plan & roadmap

Living doc. Edit scope freely; keep it honest about what exists vs. what's
intended. Companion doc on the MCP side: `../mcp_server/PLAN.md`.

## Goal

A small, realistic **paper-trading** brokerage whose REST API
(`/api/*`) is the real product surface — a clean, documented HTTP contract that
the sibling **MCP server** (`../mcp_server`) wraps as tools. The web UI is just
another client of that API; nothing the UI can do bypasses it. The whole thing
is a testbed for MCP development, so API clarity and contract stability matter
more than feature breadth.

## Current state

FastAPI backend + server-rendered vanilla-JS UI, single fake account (`acct-1`),
delayed real quotes from Yahoo. Working today: browse/search symbols, quotes,
watchlist, deposit/withdraw, review→place→cancel order flow (market + resting
limit orders filled by a 60s background task), positions with live P&L,
transactions history, account balances. Storage is file-based behind swappable
repo abstractions. See [README.md](README.md) for pages/overview and
[docs/api.md](docs/api.md) for the endpoint contract (the authoritative surface;
OpenAPI at `/docs`, snapshot in `docs/openapi.json`).

## Roadmap (rough phases)

**Phase 1 — core brokerage (done).** Accounts, transfers, equity orders
(market/limit), positions, transactions, watchlist, quotes/search.

**Phase 2 — richer market data (next).** Historicals (price series for charts),
fundamentals. These are the first things the MCP server would consume once they
land in the contract — see "Cross-project threads" #2.

**Phase 3 — depth.** Options, realized P&L / trade history, richer order types
(stop, stop-limit). Each is optional and independently scoped.

**Phase 4 — durability & multi-account.** Swap the file store for a real DB
behind the existing repo interfaces; make `account_id` a first-class,
user-selectable dimension rather than a stub (see #3).

**Phase 5 — remote access.** If/when the API is exposed beyond localhost, add an
auth story (see #4). Tracks the MCP server's own Phase 4 (remote transport).

## Cross-project threads

These live only in conversation history otherwise; capturing so they survive.

1. **Watchlist is in scope for MCP** (reversed 2026-07-04, done). `/api/watchlist`
   now has GET (list, quote-enriched) + POST (add) + DELETE (remove), documented
   in `docs/api.md`, and its inclusion feeds `/api/stocks` for the browse page.
   Originally UI-only/out of MCP scope; the user reopened it. The MCP-server
   session has shipped matching get/add/remove watchlist tools (their commit
   ff94c6f) with round-trip coverage in test_http_integration.py. Fully closed.

2. **Deferred API areas the MCP server will consume when they exist:**
   historicals, fundamentals, options, P&L / trade history. These are not in
   `docs/api.md` yet. **When any of them lands in the contract, send a
   cross-session message to the MCP-server session** and it will extend the tool
   surface to match.

3. **Multi-account is stubbed, not built.** Every endpoint accepts `?account_id=`
   and defaults to `acct-1`; there is exactly one seeded account today. The
   intent is to make this real later (multiple customers) without changing the
   API shape — the parameter is already there so clients don't have to change.

4. **Auth: none today (open question).** The API is local-only and unauthenticated
   by design. The MCP server's Phase 4 is a remote Streamable-HTTP transport,
   which will eventually want *some* auth on this API — even a static bearer
   token would do. Parked as an open decision; revisit when either side goes
   remote. No work until then.

5. **Contract stability is a shared constraint.** `docs/api.md` is consumed
   externally; the MCP server's models mirror its schemas exactly. Breaking
   changes (routes, request/response shapes, the review-token flow, the
   HTTP-200-with-`status="rejected"` refusal convention) need coordination. The
   early-warning net is the MCP server's integration suite at
   `../mcp_server/tests/test_http_integration.py`, pinned to `docs/api.md` —
   but don't rely on it to *discover* a break; message the other session first.

## Open questions

- Auth model for remote access (#4) — static token, per-account token, none?
- When does multi-account (#3) become real, and does it need login/session?
- Do historicals/fundamentals (#2) come before or after options (#3)? User picks.
- Keep file storage or move to SQLite for Phase 4? Repo interfaces already allow
  either.
