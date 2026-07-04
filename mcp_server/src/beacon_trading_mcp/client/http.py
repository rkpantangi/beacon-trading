"""HTTP client for the Beacon Trading API (contract: trading_app/docs/api.md).

The place endpoint requires the full order body and treats the review token
as optional, but this MCP server enforces the strict two-step flow: we cache
the exact body each token was bound to at review time, and place_order only
accepts a token. Tokens from a previous server process are unknown here and
require a fresh review — matching the token's single-use, short-TTL spirit.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx

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


class HttpTradingApiClient:
    def __init__(self, base_url: str, account_id: str = "acct-1") -> None:
        self._http = httpx.AsyncClient(base_url=base_url, timeout=15.0)
        self._account_id = account_id
        self._review_bodies: dict[str, dict[str, Any]] = {}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        try:
            response = await self._http.request(method, path, params=params, json=json)
        except httpx.HTTPError as exc:
            raise TradingApiError(
                f"Beacon Trading API unreachable at {self._http.base_url} "
                f"({type(exc).__name__}) — start it with ./run.sh in the app repo"
            ) from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise TradingApiError(str(detail))
        return response.json()

    def _scoped(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"account_id": self._account_id}
        if extra:
            params.update(extra)
        return params

    # --- market data ---

    async def search(self, query: str, limit: int = 15) -> list[Instrument]:
        data = await self._request(
            "GET", "/api/stocks/search", params={"q": query, "limit": limit}
        )
        return [Instrument.model_validate(item) for item in data["results"]]

    async def get_quotes(self, symbols: list[str]) -> dict[str, Quote | None]:
        data = await self._request(
            "GET", "/api/quotes", params={"symbols": ",".join(symbols)}
        )
        return {
            symbol: Quote.model_validate(quote) if quote is not None else None
            for symbol, quote in data["quotes"].items()
        }

    # --- portfolio ---

    async def get_accounts(self) -> list[Account]:
        data = await self._request("GET", "/api/accounts")
        return [Account.model_validate(item) for item in data["accounts"]]

    async def get_portfolio(self) -> Portfolio:
        data = await self._request("GET", "/api/account", params=self._scoped())
        return Portfolio.from_account(Account.model_validate(data))

    async def get_positions(self) -> list[Position]:
        data = await self._request("GET", "/api/positions", params=self._scoped())
        return [Position.model_validate(item) for item in data["positions"]]

    async def get_orders(self, status: OrderStatus | None = None) -> list[Order]:
        extra = {"status": status.value} if status is not None else None
        data = await self._request("GET", "/api/orders", params=self._scoped(extra))
        return [Order.model_validate(item) for item in data["orders"]]

    # --- watchlist ---

    async def get_watchlist(self) -> list[WatchlistItem]:
        data = await self._request("GET", "/api/watchlist", params=self._scoped())
        return [WatchlistItem.model_validate(item) for item in data["watchlist"]]

    async def add_to_watchlist(self, symbol: str) -> str:
        data = await self._request(
            "POST",
            "/api/watchlist",
            params=self._scoped(),
            json={"symbol": symbol.strip().upper()},
        )
        return data["symbol"]

    async def remove_from_watchlist(self, symbol: str) -> None:
        await self._request(
            "DELETE",
            f"/api/watchlist/{symbol.strip().upper()}",
            params=self._scoped(),
        )

    # --- orders ---

    async def review_order(
        self,
        symbol: str,
        side: OrderSide,
        qty: Decimal,
        order_type: OrderType,
        limit_price: Decimal | None,
    ) -> OrderReview:
        body: dict[str, Any] = {
            "symbol": symbol.strip().upper(),
            "side": side.value,
            "qty": float(qty),
            "type": order_type.value,
            "limit_price": float(limit_price) if limit_price is not None else None,
        }
        data = await self._request(
            "POST", "/api/orders/review", params=self._scoped(), json=body
        )
        review = OrderReview.model_validate(
            {
                **data["review"],
                "review_token": data.get("review_token"),
                "review_token_expires_in": data.get("review_token_expires_in"),
            }
        )
        if review.review_token is not None:
            self._review_bodies[review.review_token] = body
        return review

    async def place_order(self, review_token: str) -> Order:
        body = self._review_bodies.pop(review_token, None)
        if body is None:
            raise TradingApiError(
                "Unknown or already-used review token; call review_equity_order first "
                "(tokens are single-use and expire after 5 minutes)"
            )
        data = await self._request(
            "POST",
            "/api/orders",
            params=self._scoped(),
            json={**body, "review_token": review_token},
        )
        return Order.model_validate(data["order"])

    async def cancel_order(self, order_id: str) -> Order:
        data = await self._request(
            "POST", f"/api/orders/{order_id}/cancel", params=self._scoped()
        )
        return Order.model_validate(data.get("order", data))

    async def aclose(self) -> None:
        await self._http.aclose()
