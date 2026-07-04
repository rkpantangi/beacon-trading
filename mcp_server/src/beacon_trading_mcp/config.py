"""Environment-driven configuration.

Backend selection: TRADING_API_MODE=http (default) talks to the Beacon Trading
app at TRADING_API_BASE_URL; TRADING_API_MODE=fake runs against the in-memory
client — useful for tests and for demos when the app isn't running.

MCP transport: TRADING_MCP_TRANSPORT=stdio (default) runs over stdio, spawned
per-client by the MCP host. TRADING_MCP_TRANSPORT=http (alias for
streamable-http) serves Streamable HTTP on TRADING_MCP_HOST:TRADING_MCP_PORT so
the server can run as a shared service and be added with
`claude mcp add --transport http`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    api_mode: str = "http"  # "http" | "fake"
    api_base_url: str = "http://127.0.0.1:8321"
    account_id: str = "acct-1"
    mcp_transport: str = "stdio"  # "stdio" | "streamable-http"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8765


def load_settings() -> Settings:
    transport = os.environ.get("TRADING_MCP_TRANSPORT", "stdio").strip().lower()
    if transport == "http":  # friendly alias
        transport = "streamable-http"
    return Settings(
        api_mode=os.environ.get("TRADING_API_MODE", "http"),
        api_base_url=os.environ.get(
            "TRADING_API_BASE_URL", "http://127.0.0.1:8321"
        ),
        account_id=os.environ.get("TRADING_ACCOUNT_ID", "acct-1"),
        mcp_transport=transport,
        mcp_host=os.environ.get("TRADING_MCP_HOST", "127.0.0.1"),
        mcp_port=int(os.environ.get("TRADING_MCP_PORT", "8765")),
    )
