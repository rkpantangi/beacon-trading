"""Storage abstraction.

Repositories are abstract so the file-backed implementation can be replaced
with a real database (SQL, etc.) without touching the trading logic. A future
SqlDataStore only needs to implement these same interfaces.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from ..models import Account, Order, Position, Transaction


class AccountRepo(ABC):
    @abstractmethod
    def get(self, account_id: str) -> Optional[Account]: ...

    @abstractmethod
    def list(self) -> List[Account]: ...

    @abstractmethod
    def save(self, account: Account) -> None: ...


class PositionRepo(ABC):
    @abstractmethod
    def get(self, account_id: str, symbol: str) -> Optional[Position]: ...

    @abstractmethod
    def list(self, account_id: str) -> List[Position]: ...

    @abstractmethod
    def save(self, position: Position) -> None:
        """Upsert; a position with qty == 0 is removed."""


class OrderRepo(ABC):
    """Orders live in two places by design:

    - an append-only event log with every order status transition (the full
      history: open, filled, canceled, rejected — everything), and
    - a small "open orders" collection for fast access to working orders.
    """

    @abstractmethod
    def record(self, order: Order) -> None:
        """Append the order's current state to the event log, and add/remove
        it from the open-orders collection based on its status."""

    @abstractmethod
    def get(self, order_id: str) -> Optional[Order]:
        """Latest state of an order."""

    @abstractmethod
    def list(self, account_id: str, status: Optional[str] = None) -> List[Order]:
        """Latest state of all orders, optionally filtered by status."""

    @abstractmethod
    def list_open(self, account_id: Optional[str] = None) -> List[Order]:
        """Open orders only (fast path; account_id None = all accounts)."""


class TransactionRepo(ABC):
    @abstractmethod
    def record(self, txn: Transaction) -> None: ...

    @abstractmethod
    def list(self, account_id: str) -> List[Transaction]: ...


class WatchlistRepo(ABC):
    """Symbols the user has added to their browse list."""

    @abstractmethod
    def list(self, account_id: str) -> List[str]: ...

    @abstractmethod
    def add(self, account_id: str, symbol: str) -> None: ...

    @abstractmethod
    def remove(self, account_id: str, symbol: str) -> None: ...


class DataStore(ABC):
    """Aggregates the repositories and provides a mutation lock so multi-step
    operations (validate → fill → update balances) stay consistent."""

    accounts: AccountRepo
    positions: PositionRepo
    orders: OrderRepo
    transactions: TransactionRepo
    watchlists: WatchlistRepo

    @abstractmethod
    def lock(self):
        """Context manager serializing mutations."""
