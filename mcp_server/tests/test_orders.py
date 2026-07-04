from decimal import Decimal

import pytest

from beacon_trading_mcp.client import FakeTradingApiClient, TradingApiError
from beacon_trading_mcp.models import OrderSide, OrderStatus, OrderType


async def _review_market_buy(client, symbol="MSFT", qty="10"):
    return await client.review_order(
        symbol, OrderSide.BUY, Decimal(qty), OrderType.MARKET, None
    )


async def test_review_then_place_market_buy(client: FakeTradingApiClient):
    review = await _review_market_buy(client)
    assert review.can_place is True
    assert review.review_token is not None
    assert review.estimated_amount_label == "cost"
    assert review.would_fill_immediately is True
    assert review.buying_power == Decimal("100000.00")

    order = await client.place_order(review.review_token)
    assert order.status == OrderStatus.FILLED
    assert order.fill_price is not None
    assert order.filled_at is not None

    positions = {p.symbol: p for p in await client.get_positions()}
    assert positions["MSFT"].qty == Decimal("10")
    account = (await client.get_accounts())[0]
    assert account.cash_balance == Decimal("100000.00") - order.fill_price * 10


async def test_review_token_is_single_use(client: FakeTradingApiClient):
    review = await _review_market_buy(client)
    await client.place_order(review.review_token)
    with pytest.raises(TradingApiError, match="review token"):
        await client.place_order(review.review_token)


async def test_place_without_review_fails(client: FakeTradingApiClient):
    with pytest.raises(TradingApiError, match="review"):
        await client.place_order("rev_bogus")


async def test_insufficient_buying_power_refused_not_raised(
    client: FakeTradingApiClient,
):
    review = await _review_market_buy(client, qty="100000")
    assert review.can_place is False
    assert review.review_token is None
    assert "buying power" in review.reason.lower()


async def test_oversell_refused_with_shares_available(client: FakeTradingApiClient):
    review = await client.review_order(
        "AAPL", OrderSide.SELL, Decimal("51"), OrderType.MARKET, None
    )
    assert review.can_place is False
    assert review.shares_available == Decimal("50")  # seeded qty
    assert review.review_token is None


async def test_sell_updates_cash_and_position(client: FakeTradingApiClient):
    review = await client.review_order(
        "AAPL", OrderSide.SELL, Decimal("50"), OrderType.MARKET, None
    )
    assert review.can_place is True
    assert review.estimated_amount_label == "credit"
    order = await client.place_order(review.review_token)
    assert order.status == OrderStatus.FILLED
    assert "AAPL" not in {p.symbol for p in await client.get_positions()}
    account = (await client.get_accounts())[0]
    assert account.cash_balance > Decimal("100000.00")


async def test_resting_limit_buy_reserves_cash_and_cancels(
    client: FakeTradingApiClient,
):
    review = await client.review_order(
        "TSLA", OrderSide.BUY, Decimal("5"), OrderType.LIMIT, Decimal("100.00")
    )
    assert review.can_place is True
    assert review.would_fill_immediately is False

    order = await client.place_order(review.review_token)
    assert order.status == OrderStatus.OPEN

    account = (await client.get_accounts())[0]
    assert account.cash_balance == Decimal("100000.00")  # nothing spent yet
    assert account.reserved_cash == Decimal("500.00")  # 5 x $100 reserved
    assert account.buying_power == Decimal("99500.00")

    open_orders = await client.get_orders(OrderStatus.OPEN)
    assert [o.id for o in open_orders] == [order.id]

    canceled = await client.cancel_order(order.id)
    assert canceled.status == OrderStatus.CANCELED
    assert canceled.canceled_at is not None
    account = (await client.get_accounts())[0]
    assert account.reserved_cash == Decimal("0")
    assert account.buying_power == Decimal("100000.00")


async def test_open_sell_limit_reserves_shares(client: FakeTradingApiClient):
    review = await client.review_order(
        "AAPL", OrderSide.SELL, Decimal("30"), OrderType.LIMIT, Decimal("9999.00")
    )
    order = await client.place_order(review.review_token)
    assert order.status == OrderStatus.OPEN

    second = await client.review_order(
        "AAPL", OrderSide.SELL, Decimal("30"), OrderType.MARKET, None
    )
    assert second.can_place is False
    assert second.shares_available == Decimal("20")  # 50 held - 30 reserved


async def test_cancel_filled_order_fails(client: FakeTradingApiClient):
    review = await _review_market_buy(client)
    order = await client.place_order(review.review_token)
    with pytest.raises(TradingApiError, match="only open"):
        await client.cancel_order(order.id)


async def test_malformed_reviews_raise(client: FakeTradingApiClient):
    with pytest.raises(TradingApiError, match="Unknown symbol"):
        await client.review_order(
            "ZZZZ", OrderSide.BUY, Decimal("1"), OrderType.MARKET, None
        )
    with pytest.raises(TradingApiError, match="require a limit_price"):
        await client.review_order(
            "AAPL", OrderSide.BUY, Decimal("1"), OrderType.LIMIT, None
        )
    with pytest.raises(TradingApiError, match="must not set limit_price"):
        await client.review_order(
            "AAPL", OrderSide.BUY, Decimal("1"), OrderType.MARKET, Decimal("200")
        )
    with pytest.raises(TradingApiError, match="positive"):
        await client.review_order(
            "AAPL", OrderSide.BUY, Decimal("0"), OrderType.MARKET, None
        )
