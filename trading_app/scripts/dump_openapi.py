"""Regenerate docs/openapi.json from the FastAPI app.

Usage: .venv/bin/python -m scripts.dump_openapi
"""
import json
from pathlib import Path

from app.main import app

out = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"
out.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
print(f"Wrote {out}")
