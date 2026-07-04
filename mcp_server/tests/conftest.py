import pytest

from beacon_trading_mcp.client import FakeTradingApiClient


@pytest.fixture
def client() -> FakeTradingApiClient:
    return FakeTradingApiClient()
