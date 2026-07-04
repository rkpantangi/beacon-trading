from decimal import Decimal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from beacon_trading_mcp.client.base import TradingApiClient
from beacon_trading_mcp.models import Order, OrderReview, OrderSide, OrderType


def register(mcp: FastMCP, client: TradingApiClient) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def review_equity_order(
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        order_type: OrderType = OrderType.MARKET,
        limit_price: Decimal | None = None,
    ) -> OrderReview:
        """Preview an equity order before placing it. Never mutates state.

        Returns the estimated amount, current market price, whether it would
        fill immediately, and can_place. If can_place is false, the reason
        explains why (e.g. insufficient buying power) and no token is issued.
        If can_place is true, pass the returned review_token to
        place_equity_order — tokens are single-use and expire in 5 minutes.
        Always show the user the review before placing."""
        return await client.review_order(
            symbol, side, quantity, order_type, limit_price
        )

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=False))
    async def place_equity_order(review_token: str) -> Order:
        """Submit the order previously previewed with review_equity_order,
        using the review_token from that call.

        Check the returned status: market orders come back 'filled',
        non-marketable limit orders rest as 'open' (limit buys reserve cash,
        limit sells reserve shares) and fill in the background when the price
        crosses. The order can come back 'rejected' with a reject_reason —
        report that to the user rather than assuming success."""
        return await client.place_order(review_token)

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def cancel_equity_order(order_id: str) -> Order:
        """Cancel an open (resting) equity order by id, releasing any reserved
        cash or shares. Only open orders can be canceled."""
        return await client.cancel_order(order_id)
