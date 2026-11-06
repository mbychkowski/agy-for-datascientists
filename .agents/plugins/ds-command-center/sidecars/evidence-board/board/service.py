"""Board service: refreshes Tile states from a catalog and the event log, with caching and error tolerance.

Readiness is checked through table metadata only, at most once per
`refresh_interval` seconds. A Tile's chart query runs once when it lands and is
cached until one of its source tables' last-modified stamps changes. The
workspace event log is tailed at most once per `event_interval` seconds, so
in-progress activity shows up faster than readiness. Any catalog or event log
error keeps the last good state and is logged; it never reaches the API.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from board import engine
from board.catalog import TableCatalog
from board.events import Event
from board.manifest import Manifest

log = logging.getLogger("evidence_board")


class EventSource(Protocol):
    def read(self) -> list[Event]: ...


class Board:
    def __init__(
        self,
        manifest: Manifest,
        catalog: TableCatalog,
        refresh_interval: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
        events: EventSource | None = None,
        event_interval: float = 1.0,
    ) -> None:
        self._manifest = manifest
        self._catalog = catalog
        self._interval = refresh_interval
        self._clock = clock
        self._event_source = events
        self._event_interval = event_interval
        self._lock = threading.Lock()
        # Last good catalog view: (snapshot, chart rows per ready Tile).
        self._tables: tuple[engine.Snapshot, dict[str, list[dict[str, Any]]]] | None = (
            None
        )
        self._last_refresh = 0.0
        self._events: list[Event] = []
        self._last_event_read: float | None = None
        # tile id -> (source tables' modified stamps, chart rows)
        self._charts: dict[str, tuple[tuple[str, ...], list[dict[str, Any]]]] = {}

    def tiles(self) -> list[dict[str, Any]]:
        with self._lock:
            now = self._clock()
            if self._tables is None or now - self._last_refresh >= self._interval:
                try:
                    self._tables = self._refresh()
                    self._last_refresh = now
                except Exception:
                    log.warning(
                        "Evidence Board refresh failed; keeping the last good state",
                        exc_info=True,
                    )
            self._tail_events(now)
            snapshot, charts = self._tables if self._tables is not None else ({}, {})
            return engine.tile_states(self._manifest, snapshot, charts, self._events)

    def _tail_events(self, now: float) -> None:
        if self._event_source is None or (
            self._last_event_read is not None
            and now - self._last_event_read < self._event_interval
        ):
            return
        self._last_event_read = now
        try:
            self._events = self._event_source.read()
        except Exception:
            log.warning(
                "Evidence Board event log read failed; keeping the last events",
                exc_info=True,
            )

    def _refresh(
        self,
    ) -> tuple[engine.Snapshot, dict[str, list[dict[str, Any]]]]:
        snapshot = {
            table: self._catalog.table_info(table) for table in self._manifest.tables
        }
        charts: dict[str, list[dict[str, Any]]] = {}
        for tile in self._manifest.tiles:
            if not engine.is_ready(tile, snapshot):
                continue
            stamps = tuple(snapshot[t].modified for t in tile.tables)
            cached = self._charts.get(tile.id)
            if cached is None or cached[0] != stamps:
                cached = (stamps, self._catalog.run_query(tile.chart_query))
                self._charts[tile.id] = cached
            charts[tile.id] = cached[1]
        return snapshot, charts
