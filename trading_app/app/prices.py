"""Stock quotes from Yahoo Finance's public chart endpoint.

Delayed data is fine for this app — quotes are cached for CACHE_TTL seconds
and market orders fill at whatever the latest cached price is ("prevailing
price"). PriceProvider is abstract so another source can be swapped in.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

CACHE_TTL = 300  # seconds
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"


@dataclass
class Quote:
    symbol: str
    name: str
    price: float
    prev_close: Optional[float]
    change: Optional[float]
    change_pct: Optional[float]
    currency: str
    as_of: float  # unix time the quote was fetched

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AssetDetails:
    symbol: str
    name: str
    price: Optional[float]
    prev_close: Optional[float]
    change: Optional[float]
    change_pct: Optional[float]
    currency: str
    as_of: float
    fifty_two_week_high: Optional[float]
    fifty_two_week_low: Optional[float]
    day_high: Optional[float]
    day_low: Optional[float]
    volume: Optional[int]
    exchange: Optional[str]
    sector: Optional[str]
    industry: Optional[str]

    def to_dict(self) -> dict:
        return asdict(self)


class PriceProvider(ABC):
    @abstractmethod
    def get_quote(self, symbol: str) -> Optional[Quote]:
        """Latest quote, or None if the symbol can't be priced."""

    def get_details(self, symbol: str) -> Optional[AssetDetails]:
        """Get detailed asset information, or None if unavailable."""
        return None

    def get_chart_data(self, symbol: str, range_str: str) -> Optional[dict]:
        """Get historical chart data, or None if unavailable."""
        return None

    def get_quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        quotes = {}
        for s in symbols:
            q = self.get_quote(s)
            if q:
                quotes[q.symbol] = q
        return quotes


class YahooPriceProvider(PriceProvider):
    def __init__(self, cache_ttl: int = CACHE_TTL):
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, Quote] = {}
        self._details_cache: Dict[str, AssetDetails] = {}
        self._lock = threading.Lock()

    def get_quote(self, symbol: str) -> Optional[Quote]:
        symbol = symbol.upper()
        with self._lock:
            cached = self._cache.get(symbol)
        if cached and time.time() - cached.as_of < self.cache_ttl:
            return cached
        quote = self._fetch(symbol)
        if quote:
            with self._lock:
                self._cache[symbol] = quote
            return quote
        return cached  # stale is better than nothing if the fetch failed

    def get_details(self, symbol: str) -> Optional[AssetDetails]:
        symbol = symbol.upper()
        with self._lock:
            cached = self._details_cache.get(symbol)
        if cached and time.time() - cached.as_of < self.cache_ttl:
            return cached
        details = self._fetch_details(symbol)
        if details:
            with self._lock:
                self._details_cache[symbol] = details
            return details
        return cached


    def get_quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        quotes: Dict[str, Quote] = {}
        missing = []
        for s in symbols:
            s = s.upper()
            with self._lock:
                cached = self._cache.get(s)
            if cached and time.time() - cached.as_of < self.cache_ttl:
                quotes[s] = cached
            else:
                missing.append(s)
        if missing:
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = {pool.submit(self.get_quote, s): s for s in missing}
                for fut in as_completed(futures):
                    q = fut.result()
                    if q:
                        quotes[q.symbol] = q
        return quotes

    def _fetch(self, symbol: str) -> Optional[Quote]:
        url = YAHOO_CHART_URL.format(symbol=urllib.parse.quote(symbol))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            meta = data["chart"]["result"][0]["meta"]
            price = meta["regularMarketPrice"]
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            change = round(price - prev, 4) if prev else None
            change_pct = round((price - prev) / prev * 100, 4) if prev else None
            return Quote(
                symbol=meta["symbol"],
                name=meta.get("longName") or meta.get("shortName") or symbol,
                price=price,
                prev_close=prev,
                change=change,
                change_pct=change_pct,
                currency=meta.get("currency", "USD"),
                as_of=time.time(),
            )
        except Exception:
            return None

    def _fetch_details(self, symbol: str) -> Optional[AssetDetails]:
        symbol = symbol.upper()
        headers = {"User-Agent": "Mozilla/5.0"}
        
        # 1. Fetch from chart endpoint
        chart_url = YAHOO_CHART_URL.format(symbol=urllib.parse.quote(symbol))
        req_chart = urllib.request.Request(chart_url, headers=headers)
        
        meta = None
        try:
            with urllib.request.urlopen(req_chart, timeout=10) as resp:
                chart_data = json.loads(resp.read().decode("utf-8"))
                meta = chart_data["chart"]["result"][0]["meta"]
        except Exception:
            return None
            
        # 2. Fetch from search endpoint
        search_url = f"https://query2.finance.yahoo.com/v1/finance/search?q={urllib.parse.quote(symbol)}"
        req_search = urllib.request.Request(search_url, headers=headers)
        
        sector = None
        industry = None
        try:
            with urllib.request.urlopen(req_search, timeout=10) as resp:
                search_data = json.loads(resp.read().decode("utf-8"))
                quotes = search_data.get("quotes", [])
                for q in quotes:
                    if q.get("symbol") == symbol:
                        sector = q.get("sector")
                        industry = q.get("industry")
                        break
        except Exception:
            pass
            
        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        change = round(price - prev, 4) if price is not None and prev is not None else None
        change_pct = round((price - prev) / prev * 100, 4) if price is not None and prev is not None else None
        
        return AssetDetails(
            symbol=symbol,
            name=meta.get("longName") or meta.get("shortName") or symbol,
            price=price,
            prev_close=prev,
            change=change,
            change_pct=change_pct,
            currency=meta.get("currency", "USD"),
            as_of=time.time(),
            fifty_two_week_high=meta.get("fiftyTwoWeekHigh"),
            fifty_two_week_low=meta.get("fiftyTwoWeekLow"),
            day_high=meta.get("regularMarketDayHigh"),
            day_low=meta.get("regularMarketDayLow"),
            volume=meta.get("regularMarketVolume"),
            exchange=meta.get("fullExchangeName") or meta.get("exchangeName"),
            sector=sector,
            industry=industry
        )

    def get_chart_data(self, symbol: str, range_str: str) -> Optional[dict]:
        symbol = symbol.upper()
        intervals = {
            "1d": "5m",
            "5d": "15m",
            "1mo": "1d",
            "1y": "1d"
        }
        interval = intervals.get(range_str, "1d")
        headers = {"User-Agent": "Mozilla/5.0"}
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range={range_str}&interval={interval}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            result = data["chart"]["result"][0]
            timestamps = result.get("timestamp", [])
            quotes = result["indicators"]["quote"][0]
            closes = quotes.get("close", [])
            
            cleaned = []
            for t, c in zip(timestamps, closes):
                if c is not None:
                    cleaned.append({"timestamp": t, "close": round(c, 4)})
            return {
                "symbol": symbol,
                "range": range_str,
                "interval": interval,
                "data": cleaned
            }
        except Exception:
            return None


