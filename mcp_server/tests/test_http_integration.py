"""Integration tests against a live Beacon Trading app at 127.0.0.1:8321.

Skipped automatically when the app isn't running (start it with ./run.sh in
the app repo). Tests are resilient to a fresh reset: those that need buying
power top up acct-1 through the fake bank first rather than assuming an ambient
balance. The trade test uses a far-below-market limit buy that is reviewed,
placed, and immediately canceled (one canceled order remains in history).
"""

from decimal import Decimal

import httpx
import pytest

from beacon_trading_mcp.client import HttpTradingApiClient
from beacon_trading_mcp.models import OrderSide, OrderStatus, OrderType

BASE_URL = "http://127.0.0.1:8321"


def _app_is_up() -> bool:
    try:
        return httpx.get(f"{BASE_URL}/api/account", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(
    not _app_is_up(), reason="Beacon Trading app not running at 127.0.0.1:8321"
)


def _ensure_buying_power(minimum: Decimal = Decimal("5000")) -> None:
    """Top up acct-1 via the fake bank so funded-account tests establish their
    own precondition instead of depending on ambient balance (reset-proof)."""
    params = {"account_id": "acct-1"}
    account = httpx.get(f"{BASE_URL}/api/account", params=params, timeout=5).json()
    if Decimal(str(account["buying_power"])) < minimum:
        httpx.post(
            f"{BASE_URL}/api/transfers",
            params=params,
            json={"type": "deposit", "amount": float(minimum)},
            timeout=5,
        ).raise_for_status()


@pytest.fixture
async def http_client():
    client = HttpTradingApiClient(BASE_URL)
    yield client
    await client.aclose()


async def test_read_endpoints(http_client: HttpTradingApiClient):
    _ensure_buying_power()
    accounts = await http_client.get_accounts()
    assert accounts and accounts[0].account_id == "acct-1"
    assert accounts[0].buying_power == (
        accounts[0].cash_balance - accounts[0].reserved_cash
    )

    portfolio = await http_client.get_portfolio()
    assert portfolio.total_value > 0

    quotes = await http_client.get_quotes(["AAPL", "ZZZZ"])
    assert quotes["AAPL"] is not None and quotes["AAPL"].price > 0
    assert quotes["ZZZZ"] is None

    results = await http_client.search("apple")
    assert any(i.symbol == "AAPL" for i in results)

    await http_client.get_positions()
    await http_client.get_orders()


async def test_refused_review_has_no_token(http_client: HttpTradingApiClient):
    review = await http_client.review_order(
        "AAPL", OrderSide.BUY, Decimal("999999"), OrderType.MARKET, None
    )
    assert review.can_place is False
    assert review.review_token is None
    assert review.reason


async def test_review_place_cancel_roundtrip(http_client: HttpTradingApiClient):
    _ensure_buying_power()
    quotes = await http_client.get_quotes(["AAPL"])
    assert quotes["AAPL"] is not None
    low_limit = (quotes["AAPL"].price / 2).quantize(Decimal("0.01"))

    review = await http_client.review_order(
        "AAPL", OrderSide.BUY, Decimal("1"), OrderType.LIMIT, low_limit
    )
    assert review.can_place is True
    assert review.would_fill_immediately is False
    assert review.review_token is not None

    order = await http_client.place_order(review.review_token)
    assert order.status == OrderStatus.OPEN

    canceled = await http_client.cancel_order(order.id)
    assert canceled.status == OrderStatus.CANCELED


async def test_watchlist_roundtrip(http_client: HttpTradingApiClient):
    """Add then remove a symbol, leaving the watchlist as we found it."""
    initial = {i.symbol for i in await http_client.get_watchlist()}
    symbol = "NVDA"
    try:
        assert await http_client.add_to_watchlist("nvda") == symbol
        entry = next(
            (i for i in await http_client.get_watchlist() if i.symbol == symbol),
            None,
        )
        assert entry is not None and entry.name
    finally:
        if symbol not in initial:
            await http_client.remove_from_watchlist(symbol)
    assert {i.symbol for i in await http_client.get_watchlist()} == initial
