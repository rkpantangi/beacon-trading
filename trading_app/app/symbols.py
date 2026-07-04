"""US stock symbol catalog.

Sourced from the official NASDAQ Trader symbol directory (updated nightly,
free, no API key): nasdaqlisted.txt (NASDAQ) + otherlisted.txt (NYSE/AMEX/
etc.), ~12,900 symbols with company names. Cached in data/symbols.json and
refreshed when older than REFRESH_DAYS. Symbols are normalized to Yahoo
Finance style ("." -> "-", e.g. BRK.B -> BRK-B).
"""
from __future__ import annotations

import json
import re
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
OTHER_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"
REFRESH_DAYS = 7

EXCHANGE_NAMES = {
    "A": "NYSE American", "N": "NYSE", "P": "NYSE Arca",
    "Z": "Cboe BZX", "V": "IEX", "Q": "NASDAQ",
}


def _fetch(url: str) -> List[str]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace").splitlines()


def _clean_name(name: str) -> str:
    """Drop boilerplate share-type suffixes ("... - Common Stock") while
    keeping meaningful parts like share class."""
    name = re.sub(r"\s*-?\s*(Common Stock|Common Shares|Ordinary Shares|"
                  r"American Depositary Shares|Class [A-Z] Common Stock)$",
                  lambda m: f" - Class {m.group(1)[6]}" if m.group(1).startswith("Class") else "",
                  name).strip()
    return name.rstrip("-").strip()


def _parse(lines: List[str], symbol_col: int, name_col: int, test_col: int,
           etf_col: int, exchange: Optional[str], exchange_col: Optional[int]) -> List[dict]:
    out = []
    for line in lines[1:]:  # skip header
        parts = line.split("|")
        if len(parts) <= max(symbol_col, name_col, test_col, etf_col):
            continue  # footer ("File Creation Time...") or malformed line
        symbol, name = parts[symbol_col].strip(), _clean_name(parts[name_col].strip())
        if not symbol or parts[test_col].strip() == "Y":
            continue
        if "$" in symbol:  # preferred-share suffixes Yahoo doesn't map cleanly
            continue
        exch = exchange or EXCHANGE_NAMES.get(parts[exchange_col].strip(), "US")
        out.append({
            "symbol": symbol.replace(".", "-"),
            "name": name,
            "exchange": exch,
            "etf": parts[etf_col].strip() == "Y",
        })
    return out


class SymbolCatalog:
    def __init__(self, data_dir: str):
        self.path = Path(data_dir) / "symbols.json"
        self._lock = threading.Lock()
        self._symbols: List[dict] = []
        self._by_symbol: Dict[str, dict] = {}

    def load(self) -> None:
        """Load from cache, downloading a fresh copy if missing or stale."""
        with self._lock:
            cached = self._read_cache()
            if cached is not None:
                self._index(cached)
            if self._needs_refresh():
                try:
                    self._download()
                except Exception:
                    if not self._symbols:
                        raise  # no cache and no network — can't run without a catalog

    def _read_cache(self) -> Optional[List[dict]]:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))["symbols"]
        except Exception:
            return None

    def _needs_refresh(self) -> bool:
        if not self.path.exists() or not self._symbols:
            return True
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            updated = datetime.fromisoformat(data["updated_at"])
            return datetime.now(timezone.utc) - updated > timedelta(days=REFRESH_DAYS)
        except Exception:
            return True

    def _download(self) -> None:
        nasdaq = _parse(_fetch(NASDAQ_URL), symbol_col=0, name_col=1,
                        test_col=3, etf_col=6, exchange="NASDAQ", exchange_col=None)
        other = _parse(_fetch(OTHER_URL), symbol_col=0, name_col=1,
                       test_col=6, etf_col=4, exchange=None, exchange_col=2)
        symbols = sorted(nasdaq + other, key=lambda s: s["symbol"])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"updated_at": datetime.now(timezone.utc).isoformat(),
                   "symbols": symbols}
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        self._index(symbols)

    def _index(self, symbols: List[dict]) -> None:
        self._symbols = symbols
        self._by_symbol = {s["symbol"]: s for s in symbols}

    def get(self, symbol: str) -> Optional[dict]:
        return self._by_symbol.get(symbol.upper().replace(".", "-"))

    def search(self, query: str, limit: int = 20) -> List[dict]:
        """Ticker prefix matches first, then company-name substring matches."""
        q = query.strip().upper()
        if not q:
            return []
        exact, prefix, name_match = [], [], []
        for s in self._symbols:
            if s["symbol"] == q:
                exact.append(s)
            elif s["symbol"].startswith(q):
                prefix.append(s)
            elif q in s["name"].upper():
                name_match.append(s)
        return (exact + prefix + name_match)[:limit]

    def __len__(self) -> int:
        return len(self._symbols)
