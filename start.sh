#!/usr/bin/env bash
# Start the Beacon Trading stack:
#   - trading app API      -> http://127.0.0.1:8321
#   - MCP server (HTTP)     -> http://127.0.0.1:8765/mcp
# Output from each is prefixed with [app] / [mcp]. Run from anywhere;
# Ctrl+C stops both.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UV="${UV:-$HOME/.local/bin/uv}"

if [ ! -x "$UV" ]; then
  echo "uv not found at $UV — install it or set UV=/path/to/uv" >&2
  exit 1
fi

# Read a stream line by line and echo it back with a tag, so the two servers'
# logs stay distinguishable when interleaved on the same terminal.
prefix() { while IFS= read -r line; do printf '[%s] %s\n' "$1" "$line"; done; }

pids=()
cleanup() {
  trap - INT TERM EXIT
  echo
  echo "Stopping Beacon Trading stack…"
  [ ${#pids[@]} -gt 0 ] && kill "${pids[@]}" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "▶ trading app  → http://127.0.0.1:8321"
PYTHONUNBUFFERED=1 "$ROOT/trading_app/run.sh" > >(prefix app) 2>&1 &
pids+=($!)

echo "▶ MCP server   → http://127.0.0.1:8765/mcp  (Streamable HTTP)"
PYTHONUNBUFFERED=1 TRADING_MCP_TRANSPORT=http \
  "$UV" run --directory "$ROOT/mcp_server" beacon-trading-mcp-server > >(prefix mcp) 2>&1 &
pids+=($!)

echo
echo "Both starting. Register the MCP server once (if you haven't):"
echo "  claude mcp add --transport http beacon-trading http://127.0.0.1:8765/mcp"
echo "Press Ctrl+C to stop both."
wait
