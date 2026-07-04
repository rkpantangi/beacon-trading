"""REST API routes (/api/*).

All endpoints operate on the default account unless ?account_id= is given —
multi-customer ready, single customer today. These same endpoints will back
the MCP server later.
"""
from __future__ import annotations

import secrets
import threading
import time
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
