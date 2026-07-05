"""FastAPI app: REST API + server-rendered pages + background order filler."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .api import DEFAULT_ACCOUNT_ID, router as api_router
from .prices import YahooPriceProvider
from .storage.file_store import FileDataStore
from .symbols import SymbolCatalog
from .trading import TradingService

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = str(ROOT / "data")
FILL_CHECK_SECONDS = 60

log = logging.getLogger("trading")
templates = Jinja2Templates(directory=str(ROOT / "templates"))


async def _limit_order_filler(app: FastAPI):
    while True:
        await asyncio.sleep(FILL_CHECK_SECONDS)
        try:
            filled = await asyncio.get_event_loop().run_in_executor(
                None, app.state.service.process_open_orders)
            for order in filled:
                log.info("Filled open order %s: %s %g %s @ %s", order.id,
                         order.side, order.qty, order.symbol, order.fill_price)
        except Exception:
            log.exception("Limit-order fill check failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = FileDataStore(DATA_DIR)
    store.seed_default_account(DEFAULT_ACCOUNT_ID, "Ram")
    catalog = SymbolCatalog(DATA_DIR)
    await asyncio.get_event_loop().run_in_executor(None, catalog.load)
    log.info("Symbol catalog ready: %d symbols", len(catalog))

    app.state.store = store
    app.state.catalog = catalog
    app.state.prices = YahooPriceProvider()
    app.state.service = TradingService(store, app.state.prices, catalog)

    filler = asyncio.create_task(_limit_order_filler(app))
    yield
    filler.cancel()


app = FastAPI(title="Beacon Trading — paper trading", version="0.1.0", lifespan=lifespan)
app.include_router(api_router)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

PAGES = {
    "/": ("browse.html", "Browse"),
    "/positions": ("positions.html", "Positions"),
    "/orders": ("orders.html", "Orders"),
    "/history": ("history.html", "History"),
    "/balances": ("balances.html", "Balances"),
    "/agentic": ("agentic.html", "Agentic Trading"),
}


def _page(request: Request, path: str) -> HTMLResponse:
    template, title = PAGES[path]
    return templates.TemplateResponse(
        request, template, {"title": title, "active": path})


@app.get("/", response_class=HTMLResponse)
def page_browse(request: Request):
    return _page(request, "/")


@app.get("/positions", response_class=HTMLResponse)
def page_positions(request: Request):
    return _page(request, "/positions")


@app.get("/orders", response_class=HTMLResponse)
def page_orders(request: Request):
    return _page(request, "/orders")


@app.get("/history", response_class=HTMLResponse)
def page_history(request: Request):
    return _page(request, "/history")


@app.get("/balances", response_class=HTMLResponse)
def page_balances(request: Request):
    return _page(request, "/balances")


@app.get("/agentic", response_class=HTMLResponse)
def page_agentic(request: Request):
    return _page(request, "/agentic")


@app.get("/stock/{symbol}", response_class=HTMLResponse)
def page_stock_details(request: Request, symbol: str):
    return templates.TemplateResponse(
        request, "stock.html", {"title": f"{symbol.upper()} Details", "active": "/", "symbol": symbol.upper()})


