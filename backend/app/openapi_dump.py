"""Write the OpenAPI document the frontend generates its client from.

Committed to the repository rather than fetched from a running server, so
`npm run generate:api` works offline and any change to the API shows up in
the diff.

    python -m app.openapi_dump
"""

from __future__ import annotations

import json
from pathlib import Path

from app.main import app

_TARGET = Path(__file__).resolve().parent.parent.parent / "openapi.json"


def dump() -> Path:
    _TARGET.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return _TARGET


if __name__ == "__main__":
    print(dump())
