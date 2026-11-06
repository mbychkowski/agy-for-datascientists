"""FastAPI app exposing the Evidence Board's JSON API and its built frontend bundle."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from board.service import Board

NOT_BUILT = (
    "Evidence Board frontend is not built. From the repo root run "
    "`make build-frontend`, then reload this page."
)


def create_app(board: Board, static_dir: Path | None = None) -> FastAPI:
    app = FastAPI(
        title="Evidence Board", docs_url=None, redoc_url=None, openapi_url=None
    )

    @app.get("/api/tiles")
    def tiles() -> dict[str, Any]:
        return {"tiles": board.tiles()}

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    index = static_dir / "index.html" if static_dir else None

    @app.get("/", response_model=None)
    def page() -> FileResponse | PlainTextResponse:
        if index is None or not index.is_file():
            return PlainTextResponse(NOT_BUILT, status_code=503)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    if static_dir is not None:
        # Hashed Vite assets; check_dir=False so a later build is picked up live.
        app.mount(
            "/assets",
            StaticFiles(directory=static_dir / "assets", check_dir=False),
            name="assets",
        )

    return app
