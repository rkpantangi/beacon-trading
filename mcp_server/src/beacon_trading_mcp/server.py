"""FastMCP server wiring: pick a client from config, register tools, run over
the configured transport (stdio by default, Streamable HTTP when opted in)."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from beacon_trading_mcp.client import (
    FakeTradingApiClient,
    HttpTradingApiClient,
    TradingApiClient,
)
from beacon_trading_mcp.config import Settings, load_settings
from beacon_trading_mcp.tools import market_data, orders, portfolio, watchlist


def build_client(settings: Settings) -> TradingApiClient:
    if settings.api_mode == "fake":
        return FakeTradingApiClient()
    if settings.api_mode == "http":
        return HttpTradingApiClient(settings.api_base_url, settings.account_id)
    raise ValueError(f"Unknown TRADING_API_MODE: {settings.api_mode!r}")


def build_server(
    client: TradingApiClient | None = None, settings: Settings | None = None
) -> FastMCP:
    if settings is None:
        settings = load_settings()
    if client is None:
        client = build_client(settings)
    mcp = FastMCP(
        "beacon-trading",
        instructions=(
            "Trading tools for Beacon Trading, our modern brokerage. "
            "To trade: call review_equity_order first and show the user the "
            "estimated amount; if can_place is true, place_equity_order with the "
            "review_token. A placed order can still come back status='rejected' "
            "with a reject_reason — always check and report the final status. "
            "Always show the Order ID prominently to the user (e.g. in bold at the "
            "start of the confirmation message) when returning order responses."
        ),
        host=settings.mcp_host,
        port=settings.mcp_port,
    )
    market_data.register(mcp, client)
    portfolio.register(mcp, client)
    orders.register(mcp, client)
    watchlist.register(mcp, client)
    return mcp


def main() -> None:
    settings = load_settings()
    build_server(settings=settings).run(transport=settings.mcp_transport)


if __name__ == "__main__":
    main()
