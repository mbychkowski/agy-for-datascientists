"""Board state engine: (Tile manifest, table catalog snapshot, chart rows) -> Tile states.

Pure functions, no I/O. In this slice a Tile is `locked` until its readiness
rule is met, then `landed` with its chart and "what this proves" line.
"""

from __future__ import annotations

import string
from collections.abc import Mapping
from typing import Any

from board.catalog import TableInfo
from board.manifest import Manifest, Tile

Snapshot = Mapping[str, TableInfo | None]


def awaiting(tile: Tile, snapshot: Snapshot) -> list[str]:
    """The Tile's source tables that do not yet meet its readiness rule."""
    if tile.readiness == "deferred":
        return list(tile.tables)
    return [t for t in tile.tables if not _non_empty(snapshot.get(t))]


def is_ready(tile: Tile, snapshot: Snapshot) -> bool:
    return not awaiting(tile, snapshot)


def tile_states(
    manifest: Manifest, snapshot: Snapshot, charts: Mapping[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """Ordered Tile states. `charts` holds chart rows for every ready Tile."""
    states = []
    for tile in manifest.tiles:
        state: dict[str, Any] = {
            "id": tile.id,
            "step": tile.step,
            "title": tile.title,
            "tables": list(tile.tables),
        }
        pending = awaiting(tile, snapshot)
        if pending or tile.id not in charts:
            state.update(state="locked", awaiting=pending or list(tile.tables))
        else:
            rows = charts[tile.id]
            state.update(
                state="landed",
                chart={"type": tile.chart_type, "rows": rows},
                proves=_proves(tile, rows),
            )
        states.append(state)
    return states


def locked_states(manifest: Manifest) -> list[dict[str, Any]]:
    return tile_states(manifest, {}, {})


def _non_empty(info: TableInfo | None) -> bool:
    return info is not None and info.num_rows > 0


def _proves(tile: Tile, rows: list[dict[str, Any]]) -> str:
    """Fill `proves` placeholders from the chart's last row; fall back to plain text."""
    if not any(field for _, field, _, _ in string.Formatter().parse(tile.proves)):
        return tile.proves
    if not rows:
        return tile.proves_fallback
    try:
        return tile.proves.format_map(rows[-1])
    except (KeyError, IndexError, TypeError, ValueError):
        return tile.proves_fallback
