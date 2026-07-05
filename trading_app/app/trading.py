"""Trading service: order lifecycle, cash transfers, balance/position math.

Rules:
- Market orders fill immediately at the latest (delayed) quote — the
  "prevailing price".
- Limit orders stay open until the prevailing price crosses the limit
  (buy: price <= limit, sell: price >= limit); they then fill at the
  prevailing price (never worse than the limit).
- Cash for open limit buys and shares for open limit sells are reserved:
  reservations are derived from the open-orders file rather than stored,
  so they can never drift out of sync.
- No shorting, no margin. Deposits/withdrawals are instant (fake bank).
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .models import (Order, OrderSide, OrderStatus, OrderType, Position,
                     Transaction, TransactionType, now_iso)
from .prices import PriceProvider
from .storage.base import DataStore
from .symbols import SymbolCatalog


class TradingError(Exception):
    """Validation/business-rule failure; maps to HTTP 400."""


class TradingService:
    def __init__(self, store: DataStore, prices: PriceProvider, catalog: SymbolCatalog):
        self.store = store
        self.prices = prices
        self.catalog = catalog

    # ---- balances ----------------------------------------------------------

    def reserved_cash(self, account_id: str) -> float:
        return round(sum(o.qty * (o.limit_price or 0)
                         for o in self.store.orders.list_open(account_id)
                         if o.side == OrderSide.BUY), 2)

    def reserved_shares(self, account_id: str, symbol: str) -> float:
        return sum(o.qty for o in self.store.orders.list_open(account_id)
                   if o.side == OrderSide.SELL and o.symbol == symbol.upper())

    def account_summary(self, account_id: str) -> dict:
        account = self._account(account_id)
        reserved = self.reserved_cash(account_id)
        positions = self.positions_with_prices(account_id)
        positions_value = round(sum(p["market_value"] or 0 for p in positions), 2)
        unrealized_pl = round(sum(p["unrealized_pl"] or 0 for p in positions), 2)
        day_change = round(sum(p["day_change"] or 0 for p in positions), 2)
        prev_value = positions_value - day_change
        return {
            "account_id": account.id,
            "name": account.name,
            "cash_balance": account.cash_balance,
            "reserved_cash": reserved,
            "buying_power": round(account.cash_balance - reserved, 2),
            "positions_value": positions_value,
            "total_equity": round(account.cash_balance + positions_value, 2),
            "unrealized_pl": unrealized_pl,
            "day_change": day_change,
            "day_change_pct": round(day_change / prev_value * 100, 2) if prev_value else None,
        }

    def positions_with_prices(self, account_id: str) -> List[dict]:
        positions = self.store.positions.list(account_id)
        quotes = self.prices.get_quotes([p.symbol for p in positions])
        out = []
        for p in positions:
            q = quotes.get(p.symbol)
            price = q.price if q else None
            market_value = round(p.qty * price, 2) if price else None
            cost_basis = round(p.qty * p.avg_cost, 2)
            pl = round(market_value - cost_basis, 2) if market_value is not None else None
            pl_pct = round(pl / cost_basis * 100, 2) if pl is not None and cost_basis else None
            day_change = (round(p.qty * q.change, 2)
                          if q and q.change is not None else None)
            entry = self.catalog.get(p.symbol) or {}
            out.append({
                "symbol": p.symbol,
                "name": (q.name if q else None) or entry.get("name") or p.symbol,
                "qty": p.qty,
                "avg_cost": p.avg_cost,
                "price": price,
                "market_value": market_value,
                "cost_basis": cost_basis,
                "unrealized_pl": pl,
                "unrealized_pl_pct": pl_pct,
                "day_change": day_change,
                "day_change_pct": q.change_pct if q else None,
            })
        return out

    def get_asset_details(self, symbol: str) -> Optional[dict]:
        details = self.prices.get_details(symbol)
        return details.to_dict() if details else None

    def get_chart_data(self, symbol: str, range_str: str) -> Optional[dict]:
        return self.prices.get_chart_data(symbol, range_str)

    # ---- transfers ---------------------------------------------------------


    def deposit(self, account_id: str, amount: float) -> Transaction:
        self._validate_amount(amount)
        with self.store.lock():
            account = self._account(account_id)
            account.cash_balance += amount
            self.store.accounts.save(account)
            txn = Transaction.create(account_id, TransactionType.DEPOSIT, amount,
                                     description=f"Deposit from bank")
            self.store.transactions.record(txn)
            return txn

    def withdraw(self, account_id: str, amount: float) -> Transaction:
        self._validate_amount(amount)
        with self.store.lock():
            account = self._account(account_id)
            available = account.cash_balance - self.reserved_cash(account_id)
            if amount > available + 1e-9:
                raise TradingError(
                    f"Insufficient available cash: ${available:,.2f} available "
                    f"(cash minus open limit-buy reservations)")
            account.cash_balance -= amount
            self.store.accounts.save(account)
            txn = Transaction.create(account_id, TransactionType.WITHDRAW, -amount,
                                     description=f"Withdrawal to bank")
            self.store.transactions.record(txn)
            return txn

    # ---- orders ------------------------------------------------------------

    def _normalize_order_inputs(self, symbol: str, side: str, qty: float,
                                order_type: str, limit_price: Optional[float]):
        """Shared validation for review and place; raises TradingError."""
        symbol = symbol.upper().replace(".", "-")
        if side not in OrderSide.ALL:
            raise TradingError(f"Invalid side '{side}' (buy or sell)")
        if order_type not in OrderType.ALL:
            raise TradingError(f"Invalid order type '{order_type}' (market or limit)")
        if not isinstance(qty, (int, float)) or qty <= 0:
            raise TradingError("Quantity must be a positive number")
        if order_type == OrderType.LIMIT:
            if not limit_price or limit_price <= 0:
                raise TradingError("Limit orders require a positive limit price")
        else:
            limit_price = None
        if not self.catalog.get(symbol):
            raise TradingError(f"Unknown symbol '{symbol}'")
        return symbol, limit_price

    def review_order(self, account_id: str, symbol: str, side: str, qty: float,
                     order_type: str, limit_price: Optional[float] = None) -> dict:
        """Preview an order without placing it: estimated cost/credit, whether
        it would fill immediately, and whether it would be accepted."""
        symbol, limit_price = self._normalize_order_inputs(
            symbol, side, qty, order_type, limit_price)
        account = self._account(account_id)
        quote = self.prices.get_quote(symbol)

        per_share = limit_price if order_type == OrderType.LIMIT else \
            (quote.price if quote else None)
        estimated_amount = round(qty * per_share, 2) if per_share else None

        can_place, reason = True, None
        if side == OrderSide.BUY:
            available = round(account.cash_balance - self.reserved_cash(account_id), 2)
            if per_share is None:
                can_place, reason = False, f"No market price available for {symbol}"
            elif estimated_amount > available + 1e-9:
                can_place, reason = False, (f"Insufficient buying power: need "
                                            f"${estimated_amount:,.2f}, have ${available:,.2f}")
        else:
            position = self.store.positions.get(account_id, symbol)
            held = position.qty if position else 0
            available = held - self.reserved_shares(account_id, symbol)
            if qty > available + 1e-9:
                can_place, reason = False, (f"Insufficient shares: {available:g} "
                                            f"of {symbol} available to sell")

        would_fill_immediately = bool(
            quote and (order_type == OrderType.MARKET or
                       self._crosses_price(side, limit_price, quote.price)))
        return {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "order_type": order_type,
            "limit_price": limit_price,
            "market_price": quote.price if quote else None,
            "estimated_price": per_share,
            "estimated_amount": estimated_amount,
            "estimated_amount_label": "cost" if side == OrderSide.BUY else "credit",
            "buying_power" if side == OrderSide.BUY else "shares_available": available,
            "would_fill_immediately": would_fill_immediately,
            "can_place": can_place,
            "reason": reason,
        }

    def place_order(self, account_id: str, symbol: str, side: str, qty: float,
                    order_type: str, limit_price: Optional[float] = None) -> Order:
        symbol, limit_price = self._normalize_order_inputs(
            symbol, side, qty, order_type, limit_price)
        quote = self.prices.get_quote(symbol)
        if order_type == OrderType.MARKET and not quote:
            raise TradingError(f"No market price available for {symbol}")

        with self.store.lock():
            self._account(account_id)  # ensure the account exists
            order = Order.create(account_id, symbol, side, qty, order_type, limit_price)

            # Validate funds/shares. Buys reserve worst-case cost (market: the
            # prevailing price; limit: the limit price).
            if side == OrderSide.BUY:
                per_share = quote.price if order_type == OrderType.MARKET else limit_price
                cost = qty * per_share
                available = self._account(account_id).cash_balance - self.reserved_cash(account_id)
                if cost > available + 1e-9:
                    return self._reject(order, f"Insufficient buying power: need "
                                        f"${cost:,.2f}, have ${available:,.2f}")
            else:
                position = self.store.positions.get(account_id, symbol)
                held = position.qty if position else 0
                available_shares = held - self.reserved_shares(account_id, symbol)
                if qty > available_shares + 1e-9:
                    return self._reject(order, f"Insufficient shares: {available_shares:g} "
                                        f"of {symbol} available to sell")

            if order_type == OrderType.MARKET:
                self._fill(order, quote.price)
            elif quote and self._crosses(order, quote.price):
                self._fill(order, quote.price)  # marketable limit fills right away
            else:
                self.store.orders.record(order)  # rests as an open order
            return order

    def cancel_order(self, account_id: str, order_id: str) -> Order:
        with self.store.lock():
            order = self.store.orders.get(order_id)
            if not order or order.account_id != account_id:
                raise TradingError(f"Order '{order_id}' not found")
            if order.status != OrderStatus.OPEN:
                raise TradingError(f"Order {order_id} is {order.status}, not open")
            order.status = OrderStatus.CANCELED
            order.canceled_at = order.updated_at = now_iso()
            self.store.orders.record(order)
            return order

    def process_open_orders(self) -> List[Order]:
        """Fill any open limit orders the prevailing price has crossed.
        Runs periodically in the background and after quote refreshes."""
        open_orders = self.store.orders.list_open()
        if not open_orders:
            return []
        quotes = self.prices.get_quotes(sorted({o.symbol for o in open_orders}))
        filled = []
        with self.store.lock():
            for order in open_orders:
                current = self.store.orders.get(order.id)
                if not current or current.status != OrderStatus.OPEN:
                    continue
                q = quotes.get(order.symbol)
                if q and self._crosses(current, q.price):
                    self._fill(current, q.price)
                    filled.append(current)
        return filled

    # ---- internals ---------------------------------------------------------

    def _crosses(self, order: Order, price: float) -> bool:
        return self._crosses_price(order.side, order.limit_price, price)

    @staticmethod
    def _crosses_price(side: str, limit_price: Optional[float], price: float) -> bool:
        if limit_price is None:
            return True
        if side == OrderSide.BUY:
            return price <= limit_price
        return price >= limit_price

    def _fill(self, order: Order, price: float) -> None:
        account = self._account(order.account_id)
        price = round(price, 4)
        amount = round(order.qty * price, 2)
        position = self.store.positions.get(order.account_id, order.symbol) or \
            Position(account_id=order.account_id, symbol=order.symbol, qty=0, avg_cost=0)

        if order.side == OrderSide.BUY:
            account.cash_balance -= amount
            total_cost = position.qty * position.avg_cost + amount
            position.qty += order.qty
            position.avg_cost = total_cost / position.qty
            txn_amount = -amount
        else:
            if position.qty < order.qty:  # safety net; validated at placement
                order.status = OrderStatus.REJECTED
                order.reject_reason = "Position no longer covers order quantity"
                order.updated_at = now_iso()
                self.store.orders.record(order)
                return
            account.cash_balance += amount
            position.qty -= order.qty
            txn_amount = amount

        order.status = OrderStatus.FILLED
        order.fill_price = price
        order.filled_at = order.updated_at = now_iso()

        self.store.accounts.save(account)
        self.store.positions.save(position)
        self.store.orders.record(order)
        self.store.transactions.record(Transaction.create(
            order.account_id,
            TransactionType.BUY if order.side == OrderSide.BUY else TransactionType.SELL,
            txn_amount, symbol=order.symbol, qty=order.qty, price=price,
            order_id=order.id,
            description=f"{order.side.capitalize()} {order.qty:g} {order.symbol} "
                        f"@ ${price:,.2f} ({order.order_type})"))

    def _reject(self, order: Order, reason: str) -> Order:
        order.status = OrderStatus.REJECTED
        order.reject_reason = reason
        order.updated_at = now_iso()
        self.store.orders.record(order)
        return order

    def _account(self, account_id: str):
        account = self.store.accounts.get(account_id)
        if not account:
            raise TradingError(f"Account '{account_id}' not found")
        return account

    @staticmethod
    def _validate_amount(amount) -> None:
        if not isinstance(amount, (int, float)) or amount <= 0:
            raise TradingError("Amount must be a positive number")
