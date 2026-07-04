from beacon_trading_mcp.client import FakeTradingApiClient


async def test_search_by_symbol(client: FakeTradingApiClient):
    results = await client.search("AAPL")
    assert [i.symbol for i in results] == ["AAPL"]


async def test_search_by_name_fragment(client: FakeTradingApiClient):
    results = await client.search("micro")
    assert "MSFT" in [i.symbol for i in results]


async def test_search_empty_query(client: FakeTradingApiClient):
    assert await client.search("   ") == []


async def test_quotes_batch(client: FakeTradingApiClient):
    quotes = await client.get_quotes(["aapl", "SPY"])
    assert set(quotes) == {"AAPL", "SPY"}
    for quote in quotes.values():
        assert quote is not None
        assert quote.price > 0
        assert quote.prev_close is not None


async def test_unknown_symbol_maps_to_none(client: FakeTradingApiClient):
    quotes = await client.get_quotes(["AAPL", "ZZZZ"])
    assert quotes["AAPL"] is not None
    assert quotes["ZZZZ"] is None
