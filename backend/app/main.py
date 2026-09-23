"""The FastAPI application.

Endpoints arrive with the modules behind them: data and jobs in ticket 02,
signals in 03, accounts in 04. For now the app exists so the container has
something to serve and the frontend has an OpenAPI document to generate a
client from.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.config import Settings
from app.log import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    settings = Settings()
    app = FastAPI(title="invest-assistant", version="0.1.0")
    app.state.settings = settings
    return app


app = create_app()
