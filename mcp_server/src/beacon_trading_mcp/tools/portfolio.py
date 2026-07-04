from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from beacon_trading_mcp.client.base import TradingApiClient
from beacon_trading_mcp.models import Account, Order, OrderStatus, Portfolio, Position

_READ_ONLY = ToolAnnotations(readOnlyHint=True)


def register(mcp: FastMCP, client: TradingApiClient) -> None:
    @mcp.tool(annotations=_READ_ONLY)
    async def get_accounts() -> list[Account]:
        """List trading accounts: cash balance, reserved cash (backing open
        limit buys), buying power, and total equity."""
        return await client.get_accounts()

    @mcp.tool(annotations=_READ_ONLY)
    async def get_portfolio() -> Portfolio:
        """Get the portfolio valuation snapshot: total value, cash, market
        value of positions, day change, and unrealized P&L."""
        return await client.get_portfolio()

    @mcp.tool(annotations=_READ_ONLY)
    async def get_equity_positions() -> list[Position]:
        """List current stock positions with quantity, average cost, market
        value, unrealized P&L, and day change."""
        return await client.get_positions()

    @mcp.tool(annotations=_READ_ONLY)
    async def get_equity_orders(status: OrderStatus | None = None) -> list[Order]:
        """List equity orders, newest first, optionally filtered by status
        (open, filled, canceled, rejected). Rejected orders carry a
        reject_reason."""
        return await client.get_orders(status)
