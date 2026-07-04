"""In-memory stand-in for the Beacon Trading API, matching its contract semantics:

- one cash account (acct-1 equivalent), $100k seed, a few starter positions
- quotes: static seed prices with tiny deterministic jitter; unknown -> None
- review never mutates; refusals return can_place=false + reason (no error);
  a single-use review token (5-min TTL) is issued only when placeable
- place: market orders fill at the prevailing price; non-marketable limits
  rest as "open" (buys reserve cash, sells reserve shares); business refusals
  return status="rejected" with reject_reason, not an exception
- malformed input (unknown symbol, bad qty, limit-price rules, bad token)
  raises TradingApiError — the equivalent of the API's HTTP 400
- no background fill task: resting limits stay open until canceled
"""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from beacon_trading_mcp.client.base import TradingApiError
from beacon_trading_mcp.models import (
    Account,
    Instrument,
    Order,
    OrderReview,
    OrderSide,
    OrderStatus,
    OrderType,
    Portfolio,
    Position,
    Quote,
    WatchlistItem,
)

_ACCOUNT_ID = "acct-1"
_REVIEW_TTL = timedelta(minutes=5)

_INSTRUMENTS: dict[str, tuple[str, str, bool, Decimal]] = {
    "AAPL": ("Apple Inc.", "NASDAQ", False, Decimal("212.50")),
    "MSFT": ("Microsoft Corporation", "NASDAQ", False, Decimal("468.30")),
    "NVDA": ("NVIDIA Corporation", "NASDAQ", False, Decimal("157.75")),
    "TSLA": ("Tesla, Inc.", "NASDAQ", False, Decimal("315.60")),
    "AMZN": ("Amazon.com, Inc.", "NASDAQ", False, Decimal("223.10")),
    "GOOG": ("Alphabet Inc.", "NASDAQ", False, Decimal("179.85")),
    "SPY": ("SPDR S&P 500 ETF Trust", "NYSEARCA", True, Decimal("617.40")),
    "META": ("Meta Platforms, Inc.", "NASDAQ", False, Decimal("719.20")),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FakeTradingApiClient:
    def __init__(self) -> None:
        self._cash = Decimal("100000.00")
        self._holdings: dict[str, tuple[Decimal, Decimal]] = {}  # sym -> (qty, avg_cost)
        self._orders: dict[str, Order] = {}
        self._reviews: dict[str, tuple[OrderReview, datetime]] = {}
        self._order_seq = itertools.count(1)
        self._tick = itertools.count(0)
        self._watchlist: list[str] = []  # insertion order; served newest first
        for symbol, qty in (("AAPL", 50), ("SPY", 20)):
            price = _INSTRUMENTS[symbol][3]
            self._holdings[symbol] = (Decimal(qty), price * Decimal("0.9"))

    # --- reservations backing open limit orders ---

    def _reserved_cash(self) -> Decimal:
        return sum(
            (o.limit_price * o.qty
             for o in self._orders.values()
             if o.status == OrderStatus.OPEN and o.side == OrderSide.BUY),
            Decimal("0"),
        )

    def _reserved_shares(self, symbol: str) -> Decimal:
        return sum(
            (o.qty
             for o in self._orders.values()
             if o.status == OrderStatus.OPEN
             and o.side == OrderSide.SELL
             and o.symbol == symbol),
            Decimal("0"),
        )

    def _buying_power(self) -> Decimal:
        return self._cash - self._reserved_cash()

    # --- market data ---

    def _price(self, symbol: str) -> Decimal:
        seed = _INSTRUMENTS[symbol][3]
        wobble = Decimal(next(self._tick) % 7 - 3) * Decimal("0.01")
        return seed + wobble

    def _quote(self, symbol: str) -> Quote:
        name, _, _, seed = _INSTRUMENTS[symbol]
        price = self._price(symbol)
        prev_close = seed * Decimal("0.995")
        change = price - prev_close
        return Quote(
            symbol=symbol,
            name=name,
            price=price,
            prev_close=prev_close,
            change=change,
            change_pct=(change / prev_close * 100).quantize(Decimal("0.0001")),
            as_of=_now().timestamp(),
        )

    async def search(self, query: str, limit: int = 15) -> list[Instrument]:
        q = query.strip().upper()
        if not q:
            return []
        hits = [
            Instrument(symbol=sym, name=name, exchange=exch, etf=etf)
            for sym, (name, exch, etf, _) in _INSTRUMENTS.items()
            if q in sym or q in name.upper()
        ]
        hits.sort(key=lambda i: (i.symbol != q, i.symbol))
        return hits[:limit]

    async def get_quotes(self, symbols: list[str]) -> dict[str, Quote | None]:
        if len(symbols) > 50:
            raise TradingApiError("At most 50 symbols per request")
        result: dict[str, Quote | None] = {}
        for raw in symbols:
            sym = raw.strip().upper()
            result[sym] = self._quote(sym) if sym in _INSTRUMENTS else None
        return result

    # --- portfolio ---

    def _account(self) -> Account:
        positions_value = Decimal("0")
        unrealized = Decimal("0")
        day_change = Decimal("0")
        prev_value = Decimal("0")
        for sym, (qty, avg_cost) in self._holdings.items():
            quote = self._quote(sym)
            value = quote.price * qty
            positions_value += value
            unrealized += value - avg_cost * qty
            day_change += (quote.price - quote.prev_close) * qty
            prev_value += quote.prev_close * qty
        pct = (
            (day_change / prev_value * 100).quantize(Decimal("0.01"))
            if prev_value
            else Decimal("0")
        )
        return Account(
            account_id=_ACCOUNT_ID,
            name="Fake trader",
            cash_balance=self._cash,
            reserved_cash=self._reserved_cash(),
            buying_power=self._buying_power(),
            positions_value=positions_value,
            total_equity=self._cash + positions_value,
            unrealized_pl=unrealized,
            day_change=day_change,
            day_change_pct=pct,
        )

    async def get_accounts(self) -> list[Account]:
        return [self._account()]

    async def get_portfolio(self) -> Portfolio:
        return Portfolio.from_account(self._account())

    async def get_positions(self) -> list[Position]:
        result = []
        for sym, (qty, avg_cost) in self._holdings.items():
            quote = self._quote(sym)
            value = quote.price * qty
            cost_basis = avg_cost * qty
            result.append(
                Position(
                    symbol=sym,
                    name=_INSTRUMENTS[sym][0],
                    qty=qty,
                    avg_cost=avg_cost,
                    price=quote.price,
                    market_value=value,
                    cost_basis=cost_basis,
                    unrealized_pl=value - cost_basis,
                    unrealized_pl_pct=(
                        ((value - cost_basis) / cost_basis * 100).quantize(
                            Decimal("0.01")
                        )
                        if cost_basis
                        else Decimal("0")
                    ),
                    day_change=(quote.price - quote.prev_close) * qty,
                    day_change_pct=quote.change_pct,
                )
            )
        return result

    async def get_orders(self, status: OrderStatus | None = None) -> list[Order]:
        orders = sorted(self._orders.values(), key=lambda o: o.created_at, reverse=True)
        if status is not None:
            orders = [o for o in orders if o.status == status]
        return orders

    # --- watchlist ---

    async def get_watchlist(self) -> list[WatchlistItem]:
        items = []
        for sym in reversed(self._watchlist):
            quote = self._quote(sym)
            items.append(
                WatchlistItem(
                    symbol=sym,
                    name=_INSTRUMENTS[sym][0],
                    exchange=_INSTRUMENTS[sym][1],
                    price=quote.price,
                    change=quote.change,
                    change_pct=quote.change_pct,
                )
            )
        return items

    async def add_to_watchlist(self, symbol: str) -> str:
        sym = symbol.strip().upper()
        if sym not in _INSTRUMENTS:
            raise TradingApiError(f"Unknown symbol: {sym}")
        if sym not in self._watchlist:
            self._watchlist.append(sym)
        return sym

    async def remove_from_watchlist(self, symbol: str) -> None:
        sym = symbol.strip().upper()
        if sym in self._watchlist:
            self._watchlist.remove(sym)

    # --- orders ---

    async def review_order(
        self,
        symbol: str,
        side: OrderSide,
        qty: Decimal,
        order_type: OrderType,
        limit_price: Decimal | None,
    ) -> OrderReview:
        sym = symbol.strip().upper()
        if sym not in _INSTRUMENTS:
            raise TradingApiError(f"Unknown symbol: {sym}")
        if qty <= 0:
            raise TradingApiError("qty must be positive")
        if order_type == OrderType.LIMIT and limit_price is None:
            raise TradingApiError("Limit orders require a limit_price")
        if order_type == OrderType.MARKET and limit_price is not None:
            raise TradingApiError("Market orders must not set limit_price")

        market_price = self._price(sym)
        estimated_price = (
            limit_price if order_type == OrderType.LIMIT else market_price
        )
        assert estimated_price is not None
        estimated_amount = estimated_price * qty

        would_fill = order_type == OrderType.MARKET or (
            limit_price is not None
            and (
                limit_price >= market_price
                if side == OrderSide.BUY
                else limit_price <= market_price
            )
        )

        can_place = True
        reason = None
        buying_power = None
        shares_available = None
        if side == OrderSide.BUY:
            buying_power = self._buying_power()
            if estimated_amount > buying_power:
                can_place = False
                reason = (
                    f"Insufficient buying power: need ${estimated_amount:.2f}, "
                    f"have ${buying_power:.2f}"
                )
        else:
            held = self._holdings.get(sym, (Decimal("0"), Decimal("0")))[0]
            shares_available = held - self._reserved_shares(sym)
            if qty > shares_available:
                can_place = False
                reason = (
                    f"Insufficient shares: need {qty}, have {shares_available} available"
                )

        review = OrderReview(
            symbol=sym,
            side=side,
            qty=qty,
            order_type=order_type,
            limit_price=limit_price,
            market_price=market_price,
            estimated_price=estimated_price,
            estimated_amount=estimated_amount,
            estimated_amount_label="cost" if side == OrderSide.BUY else "credit",
            buying_power=buying_power,
            shares_available=shares_available,
            would_fill_immediately=would_fill,
            can_place=can_place,
            reason=reason,
            review_token=f"rev_{uuid.uuid4().hex}" if can_place else None,
            review_token_expires_in=int(_REVIEW_TTL.total_seconds())
            if can_place
            else None,
        )
        if review.review_token:
            self._reviews[review.review_token] = (review, _now() + _REVIEW_TTL)
        return review

    async def place_order(self, review_token: str) -> Order:
        entry = self._reviews.pop(review_token, None)
        if entry is None:
            raise TradingApiError(
                "Unknown or already-used review token; call review_equity_order first"
            )
        review, expires_at = entry
        if _now() > expires_at:
            raise TradingApiError("Review token expired; review the order again")

        now = _now()
        order = Order(
            id=f"ord-{next(self._order_seq):06d}",
            account_id=_ACCOUNT_ID,
            symbol=review.symbol,
            side=review.side,
            qty=review.qty,
            order_type=review.order_type,
            status=OrderStatus.OPEN,
            limit_price=review.limit_price,
            created_at=now,
            updated_at=now,
        )

        price = self._price(review.symbol)
        fill_price: Decimal | None = None
        if review.order_type == OrderType.MARKET:
            fill_price = price
        else:
            assert review.limit_price is not None
            if (review.side == OrderSide.BUY and review.limit_price >= price) or (
                review.side == OrderSide.SELL and review.limit_price <= price
            ):
                fill_price = price

        if fill_price is not None:
            self._fill(order, fill_price)
        else:
            self._validate_reservation(order)
        self._orders[order.id] = order
        return order

    def _validate_reservation(self, order: Order) -> None:
        """Re-check funds/shares at placement; refusal -> rejected, not an error."""
        if order.side == OrderSide.BUY:
            assert order.limit_price is not None
            if order.limit_price * order.qty > self._buying_power():
                order.status = OrderStatus.REJECTED
                order.reject_reason = "Insufficient buying power"
                order.updated_at = _now()
        else:
            held = self._holdings.get(order.symbol, (Decimal("0"), Decimal("0")))[0]
            if order.qty > held - self._reserved_shares(order.symbol):
                order.status = OrderStatus.REJECTED
                order.reject_reason = "Insufficient shares"
                order.updated_at = _now()

    def _fill(self, order: Order, price: Decimal) -> None:
        amount = price * order.qty
        if order.side == OrderSide.BUY:
            if amount > self._buying_power():
                order.status = OrderStatus.REJECTED
                order.reject_reason = "Insufficient buying power"
                order.updated_at = _now()
                return
            self._cash -= amount
            qty, avg_cost = self._holdings.get(
                order.symbol, (Decimal("0"), Decimal("0"))
            )
            new_qty = qty + order.qty
            self._holdings[order.symbol] = (
                new_qty,
                (avg_cost * qty + amount) / new_qty,
            )
        else:
            qty, avg_cost = self._holdings.get(
                order.symbol, (Decimal("0"), Decimal("0"))
            )
            if order.qty > qty - self._reserved_shares(order.symbol):
                order.status = OrderStatus.REJECTED
                order.reject_reason = "Insufficient shares"
                order.updated_at = _now()
                return
            self._cash += amount
            new_qty = qty - order.qty
            if new_qty == 0:
                del self._holdings[order.symbol]
            else:
                self._holdings[order.symbol] = (new_qty, avg_cost)
        now = _now()
        order.status = OrderStatus.FILLED
        order.fill_price = price
        order.filled_at = now
        order.updated_at = now

    async def cancel_order(self, order_id: str) -> Order:
        order = self._orders.get(order_id)
        if order is None:
            raise TradingApiError(f"Unknown order: {order_id}")
        if order.status != OrderStatus.OPEN:
            raise TradingApiError(
                f"Order {order_id} is {order.status.value}; only open orders can be canceled"
            )
        now = _now()
        order.status = OrderStatus.CANCELED
        order.canceled_at = now
        order.updated_at = now
        return order
