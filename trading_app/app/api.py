"""REST API routes (/api/*).

All endpoints operate on the default account unless ?account_id= is given —
multi-customer ready, single customer today. These same endpoints will back
the MCP server later.
"""
from __future__ import annotations

import secrets
import threading
import time
import re
import os
import urllib.request
import json
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .models import OrderStatus, TransactionType
from .trading import TradingError, TradingService

REVIEW_TOKEN_TTL = 300  # seconds a review token stays valid

DEFAULT_ACCOUNT_ID = "acct-1"

# Shown on the browse page before the user has added anything of their own.
POPULAR_SYMBOLS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
    "JPM", "V", "WMT", "UNH", "XOM", "PG", "KO", "DIS", "NFLX", "AMD",
    "BA", "SPY", "QQQ",
]

router = APIRouter(prefix="/api")


def _svc(request: Request) -> TradingService:
    return request.app.state.service


def _acct(account_id: Optional[str]) -> str:
    return account_id or DEFAULT_ACCOUNT_ID


class PlaceOrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10)
    side: str  # buy | sell
    qty: float = Field(..., gt=0)
    type: str  # market | limit
    limit_price: Optional[float] = None
    review_token: Optional[str] = None  # from POST /api/orders/review


class _ReviewTokens:
    """Short-lived, in-memory tokens binding a review to its exact order
    parameters. Optional for the UI; MCP clients use them for a safe
    review-then-place flow."""

    def __init__(self):
        self._tokens = {}
        self._lock = threading.Lock()

    def issue(self, key: tuple) -> str:
        token = secrets.token_urlsafe(16)
        with self._lock:
            self._tokens[token] = (key, time.time() + REVIEW_TOKEN_TTL)
        return token

    def consume(self, token: str, key: tuple) -> None:
        """Raises HTTPException if the token is missing, expired, or was
        issued for different order parameters. Valid tokens are single-use."""
        with self._lock:
            self._tokens = {t: v for t, v in self._tokens.items()
                            if v[1] > time.time()}  # drop expired
            entry = self._tokens.get(token)
            if entry is None:
                raise HTTPException(400, "Invalid or expired review_token — call "
                                         "POST /api/orders/review again")
            if entry[0] != key:
                # keep the token: a mismatched attempt shouldn't burn it
                raise HTTPException(400, "review_token was issued for different "
                                         "order parameters")
            del self._tokens[token]


_review_tokens = _ReviewTokens()


def _order_key(account_id: str, body: PlaceOrderRequest) -> tuple:
    return (account_id, body.symbol.upper().replace(".", "-"), body.side.lower(),
            body.qty, body.type.lower(), body.limit_price)


class TransferRequest(BaseModel):
    type: str  # deposit | withdraw
    amount: float = Field(..., gt=0)


class WatchRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10)


# ---- stocks ---------------------------------------------------------------

@router.get("/stocks")
def browse_stocks(request: Request, account_id: Optional[str] = None):
    """Popular stocks + the user's watchlist, with quotes."""
    svc = _svc(request)
    acct = _acct(account_id)
    watchlist = svc.store.watchlists.list(acct)
    symbols = list(dict.fromkeys(watchlist + POPULAR_SYMBOLS))  # dedupe, keep order
    quotes = svc.prices.get_quotes(symbols)
    stocks = []
    for sym in symbols:
        entry = svc.catalog.get(sym) or {}
        q = quotes.get(sym)
        stocks.append({
            "symbol": sym,
            "name": entry.get("name") or (q.name if q else sym),
            "exchange": entry.get("exchange"),
            "watched": sym in watchlist,
            **({"price": q.price, "change": q.change, "change_pct": q.change_pct}
               if q else {"price": None, "change": None, "change_pct": None}),
        })
    return {"stocks": stocks}


@router.get("/stocks/search")
def search_stocks(request: Request, q: str = Query(..., min_length=1), limit: int = 15):
    return {"results": _svc(request).catalog.search(q, limit=min(limit, 50))}


@router.get("/quotes")
def get_quotes(request: Request, symbols: str = Query(..., min_length=1)):
    """Batch quotes: ?symbols=AAPL,MSFT,BRK-B (max 50)."""
    svc = _svc(request)
    requested = [s.strip().upper().replace(".", "-")
                 for s in symbols.split(",") if s.strip()][:50]
    quotes = svc.prices.get_quotes(requested)
    return {"quotes": {sym: (quotes[sym].to_dict() if sym in quotes else None)
                       for sym in requested}}


@router.get("/stocks/{symbol}")
def get_stock(request: Request, symbol: str):
    svc = _svc(request)
    entry = svc.catalog.get(symbol)
    if not entry:
        raise HTTPException(404, f"Unknown symbol '{symbol.upper()}'")
    q = svc.prices.get_quote(entry["symbol"])
    return {
        **entry,
        **({"price": q.price, "prev_close": q.prev_close, "change": q.change,
            "change_pct": q.change_pct, "currency": q.currency}
           if q else {"price": None, "prev_close": None, "change": None,
                      "change_pct": None, "currency": None}),
    }


@router.get("/stocks/{symbol}/details")
def get_stock_details(request: Request, symbol: str):
    svc = _svc(request)
    entry = svc.catalog.get(symbol)
    if not entry:
        raise HTTPException(404, f"Unknown symbol '{symbol.upper()}'")
    details = svc.get_asset_details(entry["symbol"])
    if not details:
        raise HTTPException(404, f"Details unavailable for symbol '{symbol.upper()}'")
    return details


@router.get("/stocks/{symbol}/chart")
def get_stock_chart(request: Request, symbol: str, range: str = "1mo"):
    if range not in ["1d", "5d", "1mo", "1y"]:
        raise HTTPException(400, "Invalid range. Must be one of 1d, 5d, 1mo, 1y")
    svc = _svc(request)
    entry = svc.catalog.get(symbol)
    if not entry:
        raise HTTPException(404, f"Unknown symbol '{symbol.upper()}'")
    chart_data = svc.get_chart_data(entry["symbol"], range)
    if not chart_data:
        raise HTTPException(404, f"Chart data unavailable for symbol '{symbol.upper()}'")
    return chart_data




@router.get("/watchlist")
def get_watchlist(request: Request, account_id: Optional[str] = None):
    """The account's saved symbols, newest-added first, each with a quote."""
    svc = _svc(request)
    symbols = svc.store.watchlists.list(_acct(account_id))
    quotes = svc.prices.get_quotes(symbols)
    items = []
    for sym in symbols:
        entry = svc.catalog.get(sym) or {}
        q = quotes.get(sym)
        items.append({
            "symbol": sym,
            "name": entry.get("name") or (q.name if q else sym),
            "exchange": entry.get("exchange"),
            **({"price": q.price, "change": q.change, "change_pct": q.change_pct}
               if q else {"price": None, "change": None, "change_pct": None}),
        })
    return {"watchlist": items}


@router.post("/watchlist")
def add_to_watchlist(request: Request, body: WatchRequest, account_id: Optional[str] = None):
    svc = _svc(request)
    entry = svc.catalog.get(body.symbol)
    if not entry:
        raise HTTPException(404, f"Unknown symbol '{body.symbol.upper()}'")
    svc.store.watchlists.add(_acct(account_id), entry["symbol"])
    return {"ok": True, "symbol": entry["symbol"]}


@router.delete("/watchlist/{symbol}")
def remove_from_watchlist(request: Request, symbol: str, account_id: Optional[str] = None):
    _svc(request).store.watchlists.remove(_acct(account_id), symbol)
    return {"ok": True}


# ---- account --------------------------------------------------------------

@router.get("/accounts")
def list_accounts(request: Request):
    svc = _svc(request)
    return {"accounts": [svc.account_summary(a.id)
                         for a in svc.store.accounts.list()]}


@router.get("/account")
def get_account(request: Request, account_id: Optional[str] = None):
    try:
        return _svc(request).account_summary(_acct(account_id))
    except TradingError as e:
        raise HTTPException(404, str(e))


@router.get("/positions")
def get_positions(request: Request, account_id: Optional[str] = None):
    return {"positions": _svc(request).positions_with_prices(_acct(account_id))}


@router.get("/transactions")
def get_transactions(request: Request, account_id: Optional[str] = None,
                     type: Optional[str] = None):
    if type and type not in TransactionType.ALL:
        raise HTTPException(400, f"Invalid type; one of {TransactionType.ALL}")
    txns = _svc(request).store.transactions.list(_acct(account_id))
    if type:
        txns = [t for t in txns if t.type == type]
    return {"transactions": [t.to_dict() for t in txns]}


@router.post("/transfers")
def transfer(request: Request, body: TransferRequest, account_id: Optional[str] = None):
    svc = _svc(request)
    try:
        if body.type == "deposit":
            txn = svc.deposit(_acct(account_id), body.amount)
        elif body.type == "withdraw":
            txn = svc.withdraw(_acct(account_id), body.amount)
        else:
            raise HTTPException(400, "type must be 'deposit' or 'withdraw'")
    except TradingError as e:
        raise HTTPException(400, str(e))
    return {"transaction": txn.to_dict(),
            "account": svc.account_summary(_acct(account_id))}


# ---- orders ---------------------------------------------------------------

@router.get("/orders")
def get_orders(request: Request, account_id: Optional[str] = None,
               status: Optional[str] = None):
    svc = _svc(request)
    acct = _acct(account_id)
    if status and status not in OrderStatus.ALL:
        raise HTTPException(400, f"Invalid status; one of {OrderStatus.ALL}")
    if status == OrderStatus.OPEN:
        orders = svc.store.orders.list_open(acct)  # fast path
    else:
        orders = svc.store.orders.list(acct, status=status)
    return {"orders": [o.to_dict() for o in orders]}


@router.post("/orders/review")
def review_order(request: Request, body: PlaceOrderRequest,
                 account_id: Optional[str] = None):
    """Preview an order without placing it. Returns the estimated cost/credit
    and a single-use review_token (valid 5 min) that POST /api/orders will
    accept for the same parameters."""
    svc = _svc(request)
    acct = _acct(account_id)
    try:
        review = svc.review_order(acct, body.symbol, body.side.lower(),
                                  body.qty, body.type.lower(), body.limit_price)
    except TradingError as e:
        raise HTTPException(400, str(e))
    token = _review_tokens.issue(_order_key(acct, body)) if review["can_place"] else None
    return {"review": review, "review_token": token,
            "review_token_expires_in": REVIEW_TOKEN_TTL if token else None}


@router.post("/orders")
def place_order(request: Request, body: PlaceOrderRequest,
                account_id: Optional[str] = None):
    """Place an order. review_token is optional: if present it must match a
    prior review of these exact parameters (the safe two-step flow)."""
    svc = _svc(request)
    acct = _acct(account_id)
    if body.review_token:
        _review_tokens.consume(body.review_token, _order_key(acct, body))
    try:
        order = svc.place_order(acct, body.symbol, body.side.lower(),
                                body.qty, body.type.lower(), body.limit_price)
    except TradingError as e:
        raise HTTPException(400, str(e))
    return {"order": order.to_dict()}


@router.post("/orders/{order_id}/cancel")
def cancel_order(request: Request, order_id: str, account_id: Optional[str] = None):
    try:
        order = _svc(request).cancel_order(_acct(account_id), order_id)
    except TradingError as e:
        raise HTTPException(400, str(e))
    return {"order": order.to_dict()}


class ChatRequest(BaseModel):
    message: str


GEMINI_SYSTEM_PROMPT = """You are the AI trading assistant for Beacon Trading.
Analyze the user's message and determine the appropriate action to take.
You must respond with a single valid JSON object containing exactly these fields:
1. "action": one of "balance", "positions", "buy", "sell", "search", "quote", "orders_list", "cancel_order", "watchlist_view", "watchlist_add", "watchlist_remove", "deposit", "withdraw", or "none"
2. "symbol": the ticker symbol (in uppercase, e.g. "AAPL") if applicable, else null
3. "qty": the integer quantity to buy/sell, else null
4. "limit_price": the float limit price if specified, else null
5. "query": the search query string if searching, else null
6. "order_id": the order ID string (e.g. "ord-abc") if canceling an order, else null
7. "amount": the float dollar amount for deposit/withdrawal, else null
8. "response": a friendly conversational response to show the user (e.g. "Checking your balance..." or answering general questions)

Example mapping:
- "what is my balance?" -> {"action": "balance", "symbol": null, "qty": null, "limit_price": null, "query": null, "order_id": null, "amount": null, "response": "Sure, checking your account balance now..."}
- "buy 10 AAPL at 150" -> {"action": "buy", "symbol": "AAPL", "qty": 10, "limit_price": 150.0, "query": null, "order_id": null, "amount": null, "response": "Let me place that limit order for you..."}
- "what is Tesla's stock price?" -> {"action": "quote", "symbol": "TSLA", "qty": null, "limit_price": null, "query": null, "order_id": null, "amount": null, "response": "Getting quote for Tesla..."}
- "search for Microsoft" -> {"action": "search", "symbol": null, "qty": null, "limit_price": null, "query": "Microsoft", "order_id": null, "amount": null, "response": "Searching catalog for Microsoft..."}

Always return ONLY a raw JSON string. Do not wrap in backticks or markdown codeblocks."""


def _call_gemini_api(message: str, api_key: str) -> Optional[dict]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"{GEMINI_SYSTEM_PROMPT}\n\nUser Message: {message}"}
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }
    try:
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=4) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            text_content = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            return json.loads(text_content)
    except Exception as e:
        print(f"DEBUG ERROR: Gemini API call failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


@router.post("/chat")
def chat_agent(request: Request, body: ChatRequest, account_id: Optional[str] = None):
    svc = _svc(request)
    acct = _acct(account_id)
    msg = body.message.strip()

    # Attempt to route via Gemini LLM if API key is present
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        llm_res = _call_gemini_api(msg, api_key)
        if llm_res and isinstance(llm_res, dict):
            action = llm_res.get("action", "none")
            symbol = llm_res.get("symbol")
            qty = llm_res.get("qty")
            limit_price = llm_res.get("limit_price")
            query = llm_res.get("query")
            order_id = llm_res.get("order_id")
            amount = llm_res.get("amount")
            initial_response = llm_res.get("response", "")

            # 1. Check Balances
            if action == "balance":
                try:
                    portfolio = svc.account_summary(acct)
                    cash = float(portfolio["cash_balance"])
                    equity = float(portfolio["total_equity"])
                    pl = float(portfolio["unrealized_pl"])
                    sign = "+" if pl >= 0 else ""
                    return {
                        "response": (
                            f"{initial_response}\n\n"
                            f"💳 **Account Balances**:\n"
                            f"* **Total Equity**: ${equity:,.2f}\n"
                            f"* **Buying Power**: ${cash:,.2f}\n"
                            f"* **Unrealized P&L**: {sign}${pl:,.2f} ({portfolio['day_change_pct']}% today)"
                        )
                    }
                except Exception as e:
                    return {"response": f"Failed to retrieve balance details: {str(e)}"}

            # 2. Check Positions
            elif action == "positions":
                try:
                    positions = svc.positions_with_prices(acct)
                    if not positions:
                        return {"response": f"{initial_response}\n\nYou currently hold **no positions** in your portfolio."}
                    res = f"{initial_response}\n\n💼 **Your Active Holdings**:\n"
                    for p in positions:
                        p_sym = p["symbol"]
                        p_qty = p["qty"]
                        val = float(p["market_value"]) if p["market_value"] is not None else 0.0
                        pl = float(p["unrealized_pl"]) if p["unrealized_pl"] is not None else 0.0
                        sign = "+" if pl >= 0 else ""
                        res += f"* **{p_sym}**: {p_qty} shares (Valued at ${val:,.2f} | P&L: {sign}${pl:,.2f})\n"
                    return {"response": res}
                except Exception as e:
                    return {"response": f"Failed to retrieve positions: {str(e)}"}

            # 3. Buy / Sell Trade Execution
            elif action in ["buy", "sell"] and symbol and qty:
                try:
                    qty = int(qty)
                    symbol = symbol.upper()
                    entry = svc.catalog.get(symbol)
                    if not entry:
                        search_res = svc.catalog.search(symbol, limit=1)
                        if search_res:
                            symbol = search_res[0]["symbol"]
                            entry = svc.catalog.get(symbol)

                    if not entry:
                        return {"response": f"Sorry, I couldn't find a stock matching '{symbol}' in the catalog."}

                    order_type = "limit" if limit_price else "market"
                    order = svc.place_order(acct, symbol, action, qty, order_type, limit_price)
                    exec_action = "Bought" if action == "buy" else "Sold"
                    executed_price = float(order.fill_price) if order.fill_price is not None else (limit_price or 0.0)

                    if order.status == OrderStatus.FILLED:
                        status_msg = f"filled at **${executed_price:,.2f}**"
                    else:
                        status_msg = "placed as pending"

                    return {
                        "response": (
                            f"{initial_response}\n\n"
                            f"✅ **Trade Processed Successfully!**\n"
                            f"I have {exec_action.lower()} **{qty} shares** of **{symbol}** ({entry['name']}) {status_msg}.\n"
                            f"* **Order ID**: `{order.id}`\n"
                            f"* **Order Type**: {order_type.upper()}\n"
                            f"* **Status**: {order.status.capitalize()}"
                        )
                    }
                except TradingError as e:
                    return {"response": f"❌ **Trade Failed**: {str(e)}"}
                except Exception as e:
                    return {"response": f"❌ **Error executing trade**: {str(e)}"}

            # 4. Search Catalog
            elif action == "search" and query:
                results = svc.catalog.search(query, limit=5)
                if not results:
                    return {"response": f"No stocks found matching '{query}'."}
                res = f"🔍 **Search Results for '{query}'**:\n"
                for r in results:
                    res += f"* **{r['symbol']}**: {r['name']} ({r['exchange']})\n"
                return {"response": res}

            # 4b. Quote Check
            elif action == "quote" and symbol:
                symbol = symbol.upper()
                entry = svc.catalog.get(symbol)
                if not entry:
                    search_res = svc.catalog.search(symbol, limit=1)
                    if search_res:
                        symbol = search_res[0]["symbol"]
                        entry = svc.catalog.get(symbol)
                
                quotes = svc.prices.get_quotes([symbol])
                q = quotes.get(symbol)
                if not q:
                    return {"response": f"Sorry, I couldn't fetch a quote for symbol **'{symbol}'**."}
                
                change_sign = "+" if q.change >= 0 else ""
                return {
                    "response": (
                        f"{initial_response}\n\n"
                        f"📊 **{symbol}** ({q.name or (entry['name'] if entry else symbol)}) Quote:\n"
                        f"* **Current Price**: ${q.price:,.2f}\n"
                        f"* **Change Today**: {change_sign}${q.change:,.2f} ({q.change_pct:+.2f}%)"
                    )
                }

            # 5. Orders List
            elif action == "orders_list":
                orders = svc.store.orders.list(acct)
                if not orders:
                    return {"response": "You have no active or historical orders."}
                res = "📝 **Your Recent Orders**:\n"
                for o in orders[-10:]:  # Last 10 orders
                    price_str = f"at ${o.limit_price:,.2f}" if o.limit_price else "at market price"
                    res += f"* **{o.side.upper()} {o.qty} {o.symbol}** {price_str} | Status: **{o.status.capitalize()}** (ID: `{o.id}`)\n"
                return {"response": res}

            # 6. Cancel Order
            elif action == "cancel_order" and order_id:
                try:
                    order = svc.cancel_order(acct, order_id)
                    return {
                        "response": (
                            f"✅ **Order Canceled Successfully!**\n"
                            f"Canceled order `{order.id}` (**{order.side.upper()} {order.qty} {order.symbol}**)."
                        )
                    }
                except Exception as e:
                    return {"response": f"❌ **Failed to cancel order**: {str(e)}"}

            # 7. Watchlist View
            elif action == "watchlist_view":
                watchlist = svc.store.watchlists.list(acct)
                if not watchlist:
                    return {"response": "Your watchlist is currently empty."}
                quotes = svc.prices.get_quotes(watchlist)
                res = "⭐ **Your Watchlist**:\n"
                for sym in watchlist:
                    q = quotes.get(sym)
                    price_str = f"${q.price:,.2f}" if q else "N/A"
                    res += f"* **{sym}**: {price_str}\n"
                return {"response": res}

            # 8. Watchlist Add
            elif action == "watchlist_add" and symbol:
                symbol = symbol.upper()
                entry = svc.catalog.get(symbol)
                if not entry:
                    search_res = svc.catalog.search(symbol, limit=1)
                    if search_res:
                        symbol = search_res[0]["symbol"]
                        entry = svc.catalog.get(symbol)
                if not entry:
                    return {"response": f"Symbol '{symbol}' was not found in the catalog."}
                svc.store.watchlists.add(acct, symbol)
                return {"response": f"✅ Added **{symbol}** ({entry['name']}) to your watchlist."}

            # 9. Watchlist Remove
            elif action == "watchlist_remove" and symbol:
                symbol = symbol.upper()
                svc.store.watchlists.remove(acct, symbol)
                return {"response": f"❌ Removed **{symbol}** from your watchlist."}

            # 10. Deposit Funding
            elif action == "deposit" and amount:
                try:
                    txn = svc.deposit(acct, amount)
                    return {"response": f"💰 **Deposit Successful!**\nAdded **${amount:,.2f}** to your buying power (Transaction ID: `{txn.id}`)."}
                except Exception as e:
                    return {"response": f"❌ **Deposit Failed**: {str(e)}"}

            # 11. Withdraw Funding
            elif action == "withdraw" and amount:
                try:
                    txn = svc.withdraw(acct, amount)
                    return {"response": f"💸 **Withdrawal Successful!**\nWithdrew **${amount:,.2f}** from your buying power (Transaction ID: `{txn.id}`)."}
                except Exception as e:
                    return {"response": f"❌ **Withdrawal Failed**: {str(e)}"}

            else:
                return {"response": initial_response}

    # Fallback response if API key is missing or model request failed / rate-limited
    return {
        "response": "Sorry, the trading assistant is currently unavailable. Please try again later."
    }



