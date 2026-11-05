"""Tile manifest loading and validation.

The manifest (`tiles.json`) is the single source of truth for every Tile: id,
step, title, source tables, readiness rule, chart type and query, "what this
proves" text and event matchers. Loading rejects anything that would make the
board read outside the working datasets (`staging`, `features`, `ml`) or run
anything but a read-only query.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WORKING_DATASETS = frozenset({"staging", "features", "ml"})
READINESS_RULES = frozenset({"non_empty", "deferred"})

_TABLE_NAME = re.compile(r"^([a-z_]+)\.([A-Za-z0-9_]+)$")
# Any `<dataset>.` prefix naming a dataset the board must never read, quoted or not.
_FORBIDDEN_DATASET_REF = re.compile(r"(?i)(?<![\w.])`?(raw|ops|checkpoint)`?\s*\.")
# Table references after FROM/JOIN, with or without backticks.
_FROM_REF = re.compile(r"(?i)\b(?:FROM|JOIN)\s+`?([\w.-]+)`?")
_MUTATING_KEYWORD = re.compile(
    r"(?i)\b(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE"
    r"|EXPORT|LOAD|CALL|EXECUTE|DECLARE|SET|BEGIN)\b"
)
_STRING_LITERAL = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")


class ManifestError(ValueError):
    """The Tile manifest is malformed or reaches outside the working datasets."""


@dataclass(frozen=True)
class Tile:
    id: str
    step: str
    title: str
    tables: tuple[str, ...]
    readiness: str
    chart_type: str
    chart_query: str
    proves: str
    proves_fallback: str
    matchers: tuple[Any, ...]


@dataclass(frozen=True)
class Manifest:
    tiles: tuple[Tile, ...]

    @property
    def tables(self) -> tuple[str, ...]:
        """Every source table, once, in first-mention order."""
        return tuple(dict.fromkeys(t for tile in self.tiles for t in tile.tables))


def load_manifest(path: str | Path) -> Manifest:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read Tile manifest {path}: {exc}") from exc
    return parse_manifest(raw)


def parse_manifest(raw: Any) -> Manifest:
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("tiles"), list)
        or not raw["tiles"]
    ):
        raise ManifestError("Tile manifest needs a non-empty 'tiles' list")
    tiles = tuple(_parse_tile(entry) for entry in raw["tiles"])
    ids = [tile.id for tile in tiles]
    if len(set(ids)) != len(ids):
        raise ManifestError(f"duplicate Tile ids in manifest: {ids}")
    return Manifest(tiles)


def _parse_tile(entry: Any) -> Tile:
    if not isinstance(entry, dict):
        raise ManifestError(f"Tile entry must be an object, got {entry!r}")
    tile_id = _text(entry, "id", "?")
    tables = entry.get("tables")
    if not isinstance(tables, list) or not tables:
        raise ManifestError(f"Tile {tile_id}: 'tables' must be a non-empty list")
    for table in tables:
        _check_table(tile_id, table)

    readiness = entry.get("readiness")
    rule = readiness.get("rule") if isinstance(readiness, dict) else None
    if rule not in READINESS_RULES:
        raise ManifestError(
            f"Tile {tile_id}: readiness rule must be one of {sorted(READINESS_RULES)}"
        )

    chart = entry.get("chart")
    if not isinstance(chart, dict):
        raise ManifestError(f"Tile {tile_id}: 'chart' must be an object")
    query = chart.get("query")
    if isinstance(query, list) and all(isinstance(line, str) for line in query):
        query = "\n".join(query)
    if not isinstance(query, str) or not query.strip():
        raise ManifestError(
            f"Tile {tile_id}: chart query must be a string or list of lines"
        )
    _check_query(tile_id, query, tables)

    proves = _text(entry, "proves", tile_id)
    fallback = entry.get("proves_fallback", proves)
    if not isinstance(fallback, str) or "{" in fallback:
        raise ManifestError(f"Tile {tile_id}: 'proves_fallback' must be plain text")
    if "{" in proves and "proves_fallback" not in entry:
        raise ManifestError(
            f"Tile {tile_id}: a templated 'proves' needs a 'proves_fallback'"
        )

    matchers = entry.get("matchers", [])
    if not isinstance(matchers, list):
        raise ManifestError(f"Tile {tile_id}: 'matchers' must be a list")

    return Tile(
        id=tile_id,
        step=_text(entry, "step", tile_id),
        title=_text(entry, "title", tile_id),
        tables=tuple(tables),
        readiness=rule,
        chart_type=_text(chart, "type", tile_id),
        chart_query=query,
        proves=proves,
        proves_fallback=fallback,
        matchers=tuple(matchers),
    )


def _text(obj: dict, key: str, tile_id: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"Tile {tile_id}: '{key}' must be a non-empty string")
    return value


def _check_table(tile_id: str, table: Any) -> None:
    match = _TABLE_NAME.match(table) if isinstance(table, str) else None
    if not match or match.group(1) not in WORKING_DATASETS:
        raise ManifestError(
            f"Tile {tile_id}: table {table!r} must be <dataset>.<table> in {sorted(WORKING_DATASETS)}"
        )


def _check_query(tile_id: str, query: str, tables: list[str]) -> None:
    if _FORBIDDEN_DATASET_REF.search(query):
        raise ManifestError(
            f"Tile {tile_id}: chart query references a dataset outside the working datasets"
        )
    if not re.match(r"(?is)^\s*(SELECT|WITH)\b", query):
        raise ManifestError(f"Tile {tile_id}: chart query must be a SELECT")
    keyword = _MUTATING_KEYWORD.search(_STRING_LITERAL.sub("''", query))
    if keyword:
        raise ManifestError(
            f"Tile {tile_id}: chart query must be read-only, found {keyword.group(1)}"
        )
    for ref in _FROM_REF.findall(query):
        parts = ref.split(".")
        if len(parts) == 1:
            continue  # a CTE name or UNNEST
        if len(parts) != 2 or ref not in tables:
            raise ManifestError(
                f"Tile {tile_id}: chart query reads {ref!r}; it may only read the Tile's own tables {tables}"
            )
