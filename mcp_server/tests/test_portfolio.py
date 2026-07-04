from decimal import Decimal

from beacon_trading_mcp.client import FakeTradingApiClient


async def test_single_account_with_cash(client: FakeTradingApiClient):
    accounts = await client.get_accounts()
    assert len(accounts) == 1
    account = accounts[0]
    assert account.cash_balance == Decimal("100000.00")
    assert account.reserved_cash == Decimal("0")
    assert account.buying_power == account.cash_balance
    assert account.total_equity == account.cash_balance + account.positions_value


async def test_portfolio_matches_account(client: FakeTradingApiClient):
    portfolio = await client.get_portfolio()
    assert portfolio.total_value == portfolio.cash + portfolio.market_value
    assert portfolio.market_value > 0  # seeded positions
    assert portfolio.unrealized_pl > 0  # seeded 10% below market


async def test_seeded_positions(client: FakeTradingApiClient):
    positions = await client.get_positions()
    by_symbol = {p.symbol: p for p in positions}
    assert set(by_symbol) == {"AAPL", "SPY"}
    assert by_symbol["AAPL"].qty == Decimal("50")
    for pos in positions:
        assert pos.unrealized_pl > 0
        assert pos.market_value == pos.price * pos.qty


async def test_orders_empty_initially(client: FakeTradingApiClient):
    assert await client.get_orders() == []
