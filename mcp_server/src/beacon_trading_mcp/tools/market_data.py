from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from beacon_trading_mcp.client.base import TradingApiClient
from beacon_trading_mcp.models import Instrument, Quote

_READ_ONLY = ToolAnnotations(readOnlyHint=True)


def register(mcp: FastMCP, client: TradingApiClient) -> None:
    @mcp.tool(annotations=_READ_ONLY)
    async def search(query: str, limit: int = 15) -> list[Instrument]:
        """Search US-listed stocks and ETFs by ticker or company name.
        Exact ticker matches rank first."""
        return await client.search(query, limit)

    @mcp.tool(annotations=_READ_ONLY)
    async def get_equity_quotes(symbols: list[str]) -> dict[str, Quote | None]:
        """Get current quotes for up to 50 ticker symbols. Prices are delayed
        ~5 minutes. Unknown symbols map to null instead of erroring."""
        return await client.get_quotes(symbols)
