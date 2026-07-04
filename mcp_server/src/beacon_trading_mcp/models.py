"""Domain models mirroring the Beacon Trading HTTP API.

Source of truth: trading_app/docs/api.md (and /openapi.json on the live app).
Field names match the API exactly so responses validate without mapping.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(StrEnum):
    OPEN = "open"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


class Instrument(BaseModel):
    symbol: str
    name: str
    exchange: str | None = None
    etf: bool = False


class Quote(BaseModel):
    """Delayed quote (~5 min cache on the app side); no bid/ask in this API."""

    symbol: str
    name: str | None = None
    price: Decimal
    prev_close: Decimal | None = None
    change: Decimal | None = None
    change_pct: Decimal | None = None
    currency: str = "USD"
    as_of: float | None = None


class WatchlistItem(BaseModel):
    """Watchlist entry, quote-enriched; price fields are null if unpriceable."""

    symbol: str
    name: str | None = None
    exchange: str | None = None
    price: Decimal | None = None
    change: Decimal | None = None
    change_pct: Decimal | None = None


class Account(BaseModel):
    account_id: str
    name: str | None = None
    cash_balance: Decimal
    reserved_cash: Decimal  # backs open limit buys; buying_power = cash - reserved
    buying_power: Decimal
    positions_value: Decimal
    total_equity: Decimal
    unrealized_pl: Decimal
    day_change: Decimal
    day_change_pct: Decimal | None = None  # null when the account has no basis (all-zero)


class Portfolio(BaseModel):
    """Valuation snapshot. The API folds this into the account summary; this is
    the flat view of those fields."""

    account_id: str
    total_value: Decimal
    cash: Decimal
    market_value: Decimal
    day_change: Decimal
    day_change_pct: Decimal | None = None
    unrealized_pl: Decimal

    @classmethod
    def from_account(cls, account: Account) -> Portfolio:
        return cls(
            account_id=account.account_id,
            total_value=account.total_equity,
            cash=account.cash_balance,
            market_value=account.positions_value,
            day_change=account.day_change,
            day_change_pct=account.day_change_pct,
            unrealized_pl=account.unrealized_pl,
        )


class Position(BaseModel):
    symbol: str
    name: str | None = None
    qty: Decimal
    avg_cost: Decimal
    price: Decimal
    market_value: Decimal
    cost_basis: Decimal
    unrealized_pl: Decimal
    unrealized_pl_pct: Decimal
    day_change: Decimal | None = None
    day_change_pct: Decimal | None = None


class Order(BaseModel):
    id: str
    account_id: str | None = None
    symbol: str
    side: OrderSide
    qty: Decimal
    order_type: OrderType
    status: OrderStatus
    limit_price: Decimal | None = None
    fill_price: Decimal | None = None
    created_at: datetime
    updated_at: datetime
    filled_at: datetime | None = None
    canceled_at: datetime | None = None
    reject_reason: str | None = None


class OrderReview(BaseModel):
    """Flattened POST /api/orders/review response.

    review_token is present only when can_place is true; tokens are single-use
    with a 5-minute TTL and bound to these exact parameters. Business-rule
    refusals set can_place=false with a reason (not an error).
    """

    symbol: str | None = None
    side: OrderSide | None = None
    qty: Decimal | None = None
    order_type: OrderType | None = None
    limit_price: Decimal | None = None
    market_price: Decimal | None = None
    estimated_price: Decimal | None = None
    estimated_amount: Decimal | None = None
    estimated_amount_label: str | None = None  # "cost" for buys, "credit" for sells
    buying_power: Decimal | None = None  # buy reviews
    shares_available: Decimal | None = None  # sell reviews
    would_fill_immediately: bool | None = None
    can_place: bool
    reason: str | None = None
    review_token: str | None = None
    review_token_expires_in: int | None = None


class Transaction(BaseModel):
    id: str
    account_id: str | None = None
    type: str
    amount: Decimal
    timestamp: datetime | str
    symbol: str | None = None
    qty: Decimal | None = None
    price: Decimal | None = None
    order_id: str | None = None
    description: str = ""


class TransferResponse(BaseModel):
    transaction: Transaction
    account: Account
