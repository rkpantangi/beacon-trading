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


class PriceProvider(ABC):
    @abstractmethod
    def get_quote(self, symbol: str) -> Optional[Quote]:
        """Latest quote, or None if the symbol can't be priced."""

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
