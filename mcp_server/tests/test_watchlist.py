import pytest

from beacon_trading_mcp.client import FakeTradingApiClient, TradingApiError


async def test_watchlist_starts_empty(client: FakeTradingApiClient):
    assert await client.get_watchlist() == []


async def test_add_returns_canonical_symbol(client: FakeTradingApiClient):
    assert await client.add_to_watchlist("aapl") == "AAPL"


async def test_get_lists_newest_added_first(client: FakeTradingApiClient):
    await client.add_to_watchlist("AAPL")
    await client.add_to_watchlist("MSFT")
    items = await client.get_watchlist()
    assert [i.symbol for i in items] == ["MSFT", "AAPL"]
    top = items[0]
    assert top.name and top.exchange
    assert top.price is not None and top.price > 0


async def test_add_is_idempotent(client: FakeTradingApiClient):
    await client.add_to_watchlist("AAPL")
    await client.add_to_watchlist("aapl")
    items = await client.get_watchlist()
    assert [i.symbol for i in items] == ["AAPL"]


async def test_add_unknown_symbol_raises(client: FakeTradingApiClient):
    with pytest.raises(TradingApiError):
        await client.add_to_watchlist("ZZZZ")


async def test_remove_symbol(client: FakeTradingApiClient):
    await client.add_to_watchlist("AAPL")
    await client.remove_from_watchlist("aapl")
    assert await client.get_watchlist() == []


async def test_remove_absent_is_noop(client: FakeTradingApiClient):
    await client.remove_from_watchlist("AAPL")
    assert await client.get_watchlist() == []
