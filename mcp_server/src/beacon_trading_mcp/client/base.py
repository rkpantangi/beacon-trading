"""Interface every trading API client implements.

MCP tools depend only on this protocol. `FakeTradingApiClient` implements it
in memory; `HttpTradingApiClient` implements it against the Beacon Trading API
(contract: trading_app/docs/api.md).

Error semantics mirror the API: malformed input (unknown symbol on review,
bad qty, missing limit price, bad token) raises TradingApiError, but
business-rule refusals do NOT — reviews come back with can_place=false and a
reason, placed orders with status="rejected" and a reject_reason.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

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
    Transaction,
    TransferResponse,
    WatchlistItem,
)


class TradingApiError(Exception):
    """Raised for malformed requests / API failures; message is user-facing."""


class TradingApiClient(Protocol):
    # --- market data ---
    async def search(self, query: str, limit: int = 15) -> list[Instrument]: ...

    async def get_quotes(self, symbols: list[str]) -> dict[str, Quote | None]: ...

    # --- portfolio ---
    async def get_accounts(self) -> list[Account]: ...

    async def get_portfolio(self) -> Portfolio: ...

    async def get_positions(self) -> list[Position]: ...

    async def get_orders(self, status: OrderStatus | None = None) -> list[Order]: ...

    # --- transfers ---
    async def transfer(self, transfer_type: str, amount: Decimal) -> TransferResponse: ...

    # --- watchlist ---
    async def get_watchlist(self) -> list[WatchlistItem]: ...

    async def add_to_watchlist(self, symbol: str) -> str: ...

    async def remove_from_watchlist(self, symbol: str) -> None: ...

    # --- orders ---
    async def review_order(
        self,
        symbol: str,
        side: OrderSide,
        qty: Decimal,
        order_type: OrderType,
        limit_price: Decimal | None,
    ) -> OrderReview: ...

    async def place_order(self, review_token: str) -> Order: ...

    async def cancel_order(self, order_id: str) -> Order: ...
