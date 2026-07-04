"""Domain models.

Plain dataclasses serialized to/from dicts so the storage layer can persist
them as JSON today and as database rows later.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class OrderSide:
    BUY = "buy"
    SELL = "sell"
    ALL = (BUY, SELL)


class OrderType:
    MARKET = "market"
    LIMIT = "limit"
    ALL = (MARKET, LIMIT)


class OrderStatus:
    OPEN = "open"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    ALL = (OPEN, FILLED, CANCELED, REJECTED)


class TransactionType:
    BUY = "buy"
    SELL = "sell"
    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"
    ALL = (BUY, SELL, DEPOSIT, WITHDRAW)


@dataclass
class Account:
    id: str
    name: str
    cash_balance: float = 0.0
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Account":
        return cls(**d)


@dataclass
class Position:
    account_id: str
    symbol: str
    qty: float
    avg_cost: float

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        return cls(**d)


@dataclass
class Order:
    id: str
    account_id: str
    symbol: str
    side: str  # OrderSide
    qty: float
    order_type: str  # OrderType
    status: str = OrderStatus.OPEN
    limit_price: Optional[float] = None
    fill_price: Optional[float] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    filled_at: Optional[str] = None
    canceled_at: Optional[str] = None
    reject_reason: Optional[str] = None

    @classmethod
    def create(cls, account_id: str, symbol: str, side: str, qty: float,
               order_type: str, limit_price: Optional[float] = None) -> "Order":
        return cls(id=new_id("ord"), account_id=account_id, symbol=symbol.upper(),
                   side=side, qty=qty, order_type=order_type, limit_price=limit_price)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Order":
        return cls(**d)


@dataclass
class Transaction:
    id: str
    account_id: str
    type: str  # TransactionType
    amount: float  # signed cash effect: deposits/sells positive, withdrawals/buys negative
    timestamp: str = field(default_factory=now_iso)
    symbol: Optional[str] = None
    qty: Optional[float] = None
    price: Optional[float] = None
    order_id: Optional[str] = None
    description: str = ""

    @classmethod
    def create(cls, account_id: str, type: str, amount: float, **kwargs) -> "Transaction":
        return cls(id=new_id("txn"), account_id=account_id, type=type,
                   amount=round(amount, 2), **kwargs)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Transaction":
        return cls(**d)
