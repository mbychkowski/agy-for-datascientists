"""Board state engine: (Tile manifest, table catalog snapshot, chart rows, events) -> Tile states.

Pure functions, no I/O. Tile state machine (spec #88):

- `locked`: readiness not met and no matching events since the last `reset`.
- `in_progress`: readiness not met, but matching events since the last
  `reset`; carries the `activity` to display (lanes, blocked calls).
- `landed`: readiness met, with its chart and "what this proves" line. This
  wins regardless of events, so a Checkpoint swap goes `locked` -> `landed`.
  A landed Tile still carries any `activity`, so the Opening (whose table is
  loaded before the session) can show the guardrail's blocked call.
"""

from __future__ import annotations

import string
from collections.abc import Mapping, Sequence
from typing import Any

from board.catalog import TableInfo
from board.events import Event, since_last_reset
from board.manifest import Manifest, Tile

Snapshot = Mapping[str, TableInfo | None]
# Blocked calls shown per Tile, newest last.
MAX_BLOCKED = 3


def awaiting(tile: Tile, snapshot: Snapshot) -> list[str]:
    """The Tile's source tables that do not yet meet its readiness rule."""
    if tile.readiness == "deferred":
        return list(tile.tables)
    return [t for t in tile.tables if not _non_empty(snapshot.get(t))]


def is_ready(tile: Tile, snapshot: Snapshot) -> bool:
    return not awaiting(tile, snapshot)


def activity(tile: Tile, events: Sequence[Event]) -> dict[str, Any] | None:
    """What the Tile's matchers make of the events, or None if nothing matched."""
    lanes: dict[str, dict[str, Any]] = {}
    blocked: list[dict[str, Any]] = []
    for event in since_last_reset(list(events)):
        for matcher in tile.matchers:
            if not matcher.matches(event):
                continue
            if matcher.kind == "lane" and matcher.label not in lanes:
                lanes[matcher.label] = {"label": matcher.label, "since": event.ts}
            elif matcher.kind == "blocked":
                blocked.append(
                    {
                        "ts": event.ts,
                        "tool": event.tool,
                        "summary": event.summary,
                        "reason": event.reason or "",
                    }
                )
            break
    found: dict[str, Any] = {}
    if lanes:
        found["lanes"] = list(lanes.values())
    if blocked:
        found["blocked"] = blocked[-MAX_BLOCKED:]
    return found or None


def tile_states(
    manifest: Manifest,
    snapshot: Snapshot,
    charts: Mapping[str, list[dict[str, Any]]],
    events: Sequence[Event] = (),
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
        found = activity(tile, events)
        if pending or tile.id not in charts:
            state.update(
                state="in_progress" if found else "locked",
                awaiting=pending or list(tile.tables),
            )
        else:
            rows = charts[tile.id]
            state.update(
                state="landed",
                chart={"type": tile.chart_type, "rows": rows},
                proves=_proves(tile, rows),
            )
        if found:
            state["activity"] = found
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
