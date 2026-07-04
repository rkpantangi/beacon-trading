"""End-to-end: talk to the server through a real in-memory MCP session."""

import json

from mcp.shared.memory import create_connected_server_and_client_session

from beacon_trading_mcp.server import build_server

EXPECTED_TOOLS = {
    "search",
    "get_equity_quotes",
    "get_accounts",
    "get_portfolio",
    "get_equity_positions",
    "get_equity_orders",
    "review_equity_order",
    "place_equity_order",
    "cancel_equity_order",
    "get_watchlist",
    "add_to_watchlist",
    "remove_from_watchlist",
}

# Tools that mutate state and are therefore not marked readOnlyHint.
MUTATING_TOOLS = {
    "place_equity_order",
    "cancel_equity_order",
    "add_to_watchlist",
    "remove_from_watchlist",
}


def _fake_server():
    from beacon_trading_mcp.client import FakeTradingApiClient

    return build_server(FakeTradingApiClient())


async def test_lists_all_tools():
    async with create_connected_server_and_client_session(
        _fake_server()._mcp_server
    ) as session:
        tools = await session.list_tools()
        assert {t.name for t in tools.tools} == EXPECTED_TOOLS


async def test_read_only_hints():
    async with create_connected_server_and_client_session(
        _fake_server()._mcp_server
    ) as session:
        tools = {t.name: t for t in (await session.list_tools()).tools}
        for name in EXPECTED_TOOLS - MUTATING_TOOLS:
            assert tools[name].annotations.readOnlyHint, name


async def test_full_trade_over_mcp():
    async with create_connected_server_and_client_session(
        _fake_server()._mcp_server
    ) as session:
        review = await session.call_tool(
            "review_equity_order",
            {"symbol": "NVDA", "side": "buy", "quantity": "10"},
        )
        assert not review.isError
        payload = json.loads(review.content[0].text)
        assert payload["can_place"] is True

        placed = await session.call_tool(
            "place_equity_order", {"review_token": payload["review_token"]}
        )
        assert not placed.isError
        assert json.loads(placed.content[0].text)["status"] == "filled"

        positions = await session.call_tool("get_equity_positions", {})
        symbols = [json.loads(b.text)["symbol"] for b in positions.content]
        assert "NVDA" in symbols


async def test_refusal_is_data_not_error():
    async with create_connected_server_and_client_session(
        _fake_server()._mcp_server
    ) as session:
        result = await session.call_tool(
            "review_equity_order",
            {"symbol": "AAPL", "side": "sell", "quantity": "999"},
        )
        assert not result.isError  # business refusal is a normal response
        payload = json.loads(result.content[0].text)
        assert payload["can_place"] is False
        assert payload["review_token"] is None


async def test_malformed_input_is_tool_error():
    async with create_connected_server_and_client_session(
        _fake_server()._mcp_server
    ) as session:
        result = await session.call_tool(
            "review_equity_order",
            {"symbol": "ZZZZ", "side": "buy", "quantity": "1"},
        )
        assert result.isError
        assert "Unknown symbol" in result.content[0].text
