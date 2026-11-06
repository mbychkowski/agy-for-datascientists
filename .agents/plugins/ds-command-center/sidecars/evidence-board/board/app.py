"""FastAPI app exposing the Evidence Board's JSON API and its built frontend bundle.

Ask routes (#97), both POST with a JSON body and no effect without a sender
(the standalone board has none, so the frontend falls back to the clipboard):

- `POST /api/ask` `{tile, prompt, conversationId?}`: sends a landed Tile's Ask
  prompt into the Command Center conversation, either the one in the body or
  the latest one in the event log. The prompt must equal the one `GET
  /api/tiles` serves for that Tile, so the route can't relay arbitrary text.
- `POST /_sidecar/send-message` `{conversationId?, message}`: the route the
  reference sidecar preload's `window.sidecar.agent.sendMessage` posts to.
  It relays any text, so it requires the sidecar UI token.

When a UI token is configured (Antigravity's `ANTIGRAVITY_SIDECAR_UI_TOKEN`),
both routes need it in the `X-Sidecar-Token` header or the `token` query
parameter, as in the reference backend. A JSON content type is required, so a
cross-site form post can't trigger a send.
"""

from __future__ import annotations

import hmac
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from board.agentapi import Sender, SendError, valid_conversation_id
from board.service import Board

log = logging.getLogger("evidence_board")

NOT_BUILT = (
    "Evidence Board frontend is not built. From the repo root run "
    "`make build-frontend`, then reload this page."
)


def create_app(
    board: Board,
    static_dir: Path | None = None,
    sender: Sender | None = None,
    token: str | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Evidence Board", docs_url=None, redoc_url=None, openapi_url=None
    )

    @app.get("/api/tiles")
    def tiles() -> dict[str, Any]:
        return {"tiles": board.tiles()}

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/ask")
    async def ask(request: Request) -> JSONResponse:
        body = await _json_body(request, token, token_required=False)
        if isinstance(body, JSONResponse):
            return body
        tile_id, text = body.get("tile"), body.get("prompt")
        tile = next((t for t in board.tiles() if t["id"] == tile_id), None)
        if tile is None or tile.get("ask", {}).get("prompt") != text:
            return _refuse(409, "not the current Ask prompt of a landed Tile")
        return _send(board, sender, body.get("conversationId"), text)

    @app.post("/_sidecar/send-message")
    async def send_message(request: Request) -> JSONResponse:
        body = await _json_body(request, token, token_required=True)
        if isinstance(body, JSONResponse):
            return body
        message = body.get("message")
        if not isinstance(message, str) or not message.strip():
            return _refuse(400, "message required")
        board.tiles()  # tail the event log for the latest conversation
        return _send(board, sender, body.get("conversationId"), message)

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


def _refuse(status: int, reason: str) -> JSONResponse:
    return JSONResponse({"sent": False, "reason": reason}, status_code=status)


async def _json_body(
    request: Request, token: str | None, token_required: bool
) -> dict[str, Any] | JSONResponse:
    """The request's JSON object body, or the refusal to return instead."""
    if token_required and not token:
        return _refuse(401, "unauthorized")
    if token:
        given = request.headers.get("x-sidecar-token") or request.query_params.get(
            "token", ""
        )
        if not hmac.compare_digest(given.encode(), token.encode()):
            return _refuse(401, "unauthorized")
    content_type = request.headers.get("content-type", "")
    if content_type.split(";")[0].strip().lower() != "application/json":
        return _refuse(415, "JSON body required")
    try:
        body = await request.json()
    except ValueError:
        return _refuse(400, "JSON body required")
    if not isinstance(body, dict):
        return _refuse(400, "JSON object required")
    return body


def _send(
    board: Board, sender: Sender | None, requested: Any, message: str
) -> JSONResponse:
    if sender is None:
        return _refuse(503, "no agentapi sender outside the Antigravity sidecar")
    conversation = (
        requested if valid_conversation_id(requested) else board.conversation_id()
    )
    if conversation is None:
        return _refuse(503, "no Command Center conversation recorded yet")
    try:
        sender.send(conversation, message)
    except SendError as exc:
        log.warning("Evidence Board Ask send failed: %s", exc)
        return _refuse(503, "send failed")
    return JSONResponse({"sent": True, "via": "agentapi"})
