"""FastAPI app exposing the Evidence Board's JSON API."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from board.service import Board


def create_app(board: Board) -> FastAPI:
    app = FastAPI(
        title="Evidence Board", docs_url=None, redoc_url=None, openapi_url=None
    )

    @app.get("/api/tiles")
    def tiles() -> dict[str, Any]:
        return {"tiles": board.tiles()}

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
