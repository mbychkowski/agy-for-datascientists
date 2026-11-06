"""Board service: refreshes Tile states from a catalog, with caching and error tolerance.

Readiness is checked through table metadata only, at most once per
`refresh_interval` seconds. A Tile's chart query runs once when it lands and is
cached until one of its source tables' last-modified stamps changes. Any
catalog error keeps the last good state and is logged; it never reaches the API.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from board import engine
from board.catalog import TableCatalog
from board.manifest import Manifest

log = logging.getLogger("evidence_board")


class Board:
    def __init__(
        self,
        manifest: Manifest,
        catalog: TableCatalog,
        refresh_interval: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._manifest = manifest
        self._catalog = catalog
        self._interval = refresh_interval
        self._clock = clock
        self._lock = threading.Lock()
        self._last_good: list[dict[str, Any]] | None = None
        self._last_refresh = 0.0
        # tile id -> (source tables' modified stamps, chart rows)
        self._charts: dict[str, tuple[tuple[str, ...], list[dict[str, Any]]]] = {}

    def tiles(self) -> list[dict[str, Any]]:
        with self._lock:
            now = self._clock()
            if (
                self._last_good is not None
                and now - self._last_refresh < self._interval
            ):
                return self._last_good
            try:
                states = self._refresh()
            except Exception:
                log.warning(
                    "Evidence Board refresh failed; keeping the last good state",
                    exc_info=True,
                )
                return (
                    self._last_good
                    if self._last_good is not None
                    else engine.locked_states(self._manifest)
                )
            self._last_good, self._last_refresh = states, now
            return states

    def _refresh(self) -> list[dict[str, Any]]:
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
        return engine.tile_states(self._manifest, snapshot, charts)
