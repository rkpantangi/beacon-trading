#!/bin/bash
# Start the trading app. Creates the venv and installs deps on first run.
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    python3 -m venv .venv
    .venv/bin/pip install --quiet --upgrade pip
    .venv/bin/pip install --quiet -r requirements.txt
fi

exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8321 "$@"
