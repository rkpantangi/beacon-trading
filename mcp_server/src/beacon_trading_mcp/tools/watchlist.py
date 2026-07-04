from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from beacon_trading_mcp.client.base import TradingApiClient
from beacon_trading_mcp.models import WatchlistItem


def register(mcp: FastMCP, client: TradingApiClient) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_watchlist() -> list[WatchlistItem]:
        """Get the watchlist, newest-added first, enriched with current quote
        data (price fields are null if unpriceable). A pure convenience list —
        it has no effect on trading, positions, or reservations."""
        return await client.get_watchlist()

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def add_to_watchlist(symbol: str) -> str:
        """Add a ticker to the watchlist and return its canonical symbol.
        Re-adding an existing symbol is a no-op; unknown symbols error."""
        return await client.add_to_watchlist(symbol)

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def remove_from_watchlist(symbol: str) -> str:
        """Remove a ticker from the watchlist. No-op if it isn't on the list."""
        sym = symbol.strip().upper()
        await client.remove_from_watchlist(sym)
        return f"{sym} removed from watchlist"
