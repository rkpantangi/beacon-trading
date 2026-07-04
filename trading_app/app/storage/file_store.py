"""Text-file-backed DataStore.

Layout under the data directory:
  accounts.json       — list of account dicts
  positions.json      — {account_id: {symbol: {qty, avg_cost}}}
  open_orders.json    — {order_id: order dict}  (working orders only, fast access)
  orders.jsonl        — append-only log of every order state transition
  transactions.jsonl  — append-only log of fills, deposits, withdrawals

Writes are atomic (tmp file + os.replace) and serialized with an RLock, so a
crash never leaves a half-written JSON file.
"""
from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional

from ..models import Account, Order, OrderStatus, Position, Transaction
from . import base


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _append_jsonl(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _read_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


class FileDataStore(base.DataStore):
    def __init__(self, data_dir: str):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.accounts = _FileAccountRepo(self)
        self.positions = _FilePositionRepo(self)
        self.orders = _FileOrderRepo(self)
        self.transactions = _FileTransactionRepo(self)
        self.watchlists = _FileWatchlistRepo(self)

    @contextmanager
    def lock(self):
        with self._lock:
            yield

    def path(self, name: str) -> Path:
        return self.dir / name

    def seed_default_account(self, account_id: str, name: str) -> Account:
        """Create the default account (with $0 cash) if it doesn't exist."""
        with self.lock():
            existing = self.accounts.get(account_id)
            if existing:
                return existing
            account = Account(id=account_id, name=name, cash_balance=0.0)
            self.accounts.save(account)
            return account


class _FileAccountRepo(base.AccountRepo):
    def __init__(self, store: FileDataStore):
        self.store = store

    def _load(self) -> List[dict]:
        return _read_json(self.store.path("accounts.json"), [])

    def get(self, account_id: str) -> Optional[Account]:
        for d in self._load():
            if d["id"] == account_id:
                return Account.from_dict(d)
        return None

    def list(self) -> List[Account]:
        return [Account.from_dict(d) for d in self._load()]

    def save(self, account: Account) -> None:
        with self.store.lock():
            records = self._load()
            records = [d for d in records if d["id"] != account.id]
            account.cash_balance = round(account.cash_balance, 2)
            records.append(account.to_dict())
            _atomic_write(self.store.path("accounts.json"),
                          json.dumps(records, indent=2))


class _FilePositionRepo(base.PositionRepo):
    def __init__(self, store: FileDataStore):
        self.store = store

    def _load(self) -> Dict[str, Dict[str, dict]]:
        return _read_json(self.store.path("positions.json"), {})

    def get(self, account_id: str, symbol: str) -> Optional[Position]:
        d = self._load().get(account_id, {}).get(symbol.upper())
        if not d:
            return None
        return Position(account_id=account_id, symbol=symbol.upper(), **d)

    def list(self, account_id: str) -> List[Position]:
        return [Position(account_id=account_id, symbol=sym, **d)
                for sym, d in sorted(self._load().get(account_id, {}).items())]

    def save(self, position: Position) -> None:
        with self.store.lock():
            data = self._load()
            acct = data.setdefault(position.account_id, {})
            if position.qty <= 0:
                acct.pop(position.symbol, None)
            else:
                acct[position.symbol] = {
                    "qty": position.qty,
                    "avg_cost": round(position.avg_cost, 4),
                }
            _atomic_write(self.store.path("positions.json"),
                          json.dumps(data, indent=2))


class _FileOrderRepo(base.OrderRepo):
    def __init__(self, store: FileDataStore):
        self.store = store

    def _load_open(self) -> Dict[str, dict]:
        return _read_json(self.store.path("open_orders.json"), {})

    def record(self, order: Order) -> None:
        with self.store.lock():
            _append_jsonl(self.store.path("orders.jsonl"), order.to_dict())
            open_orders = self._load_open()
            if order.status == OrderStatus.OPEN:
                open_orders[order.id] = order.to_dict()
            else:
                open_orders.pop(order.id, None)
            _atomic_write(self.store.path("open_orders.json"),
                          json.dumps(open_orders, indent=2))

    def get(self, order_id: str) -> Optional[Order]:
        open_orders = self._load_open()
        if order_id in open_orders:
            return Order.from_dict(open_orders[order_id])
        latest = None
        for d in _read_jsonl(self.store.path("orders.jsonl")):
            if d["id"] == order_id:
                latest = d
        return Order.from_dict(latest) if latest else None

    def list(self, account_id: str, status: Optional[str] = None) -> List[Order]:
        latest: Dict[str, dict] = {}
        for d in _read_jsonl(self.store.path("orders.jsonl")):
            if d["account_id"] == account_id:
                latest[d["id"]] = d
        orders = [Order.from_dict(d) for d in latest.values()]
        if status:
            orders = [o for o in orders if o.status == status]
        orders.sort(key=lambda o: o.created_at, reverse=True)
        return orders

    def list_open(self, account_id: Optional[str] = None) -> List[Order]:
        orders = [Order.from_dict(d) for d in self._load_open().values()]
        if account_id:
            orders = [o for o in orders if o.account_id == account_id]
        orders.sort(key=lambda o: o.created_at, reverse=True)
        return orders


class _FileWatchlistRepo(base.WatchlistRepo):
    def __init__(self, store: FileDataStore):
        self.store = store

    def _load(self) -> Dict[str, List[str]]:
        return _read_json(self.store.path("watchlists.json"), {})

    def _save(self, data: Dict[str, List[str]]) -> None:
        _atomic_write(self.store.path("watchlists.json"),
                      json.dumps(data, indent=2))

    def list(self, account_id: str) -> List[str]:
        return self._load().get(account_id, [])

    def add(self, account_id: str, symbol: str) -> None:
        with self.store.lock():
            data = self._load()
            symbols = data.setdefault(account_id, [])
            if symbol.upper() not in symbols:
                symbols.insert(0, symbol.upper())
                self._save(data)

    def remove(self, account_id: str, symbol: str) -> None:
        with self.store.lock():
            data = self._load()
            symbols = data.get(account_id, [])
            if symbol.upper() in symbols:
                symbols.remove(symbol.upper())
                self._save(data)


class _FileTransactionRepo(base.TransactionRepo):
    def __init__(self, store: FileDataStore):
        self.store = store

    def record(self, txn: Transaction) -> None:
        with self.store.lock():
            _append_jsonl(self.store.path("transactions.jsonl"), txn.to_dict())

    def list(self, account_id: str) -> List[Transaction]:
        txns = [Transaction.from_dict(d)
                for d in _read_jsonl(self.store.path("transactions.jsonl"))
                if d["account_id"] == account_id]
        txns.sort(key=lambda t: t.timestamp, reverse=True)
        return txns
