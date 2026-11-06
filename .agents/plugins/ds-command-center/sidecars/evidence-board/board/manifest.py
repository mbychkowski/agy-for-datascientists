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
# Matcher kind -> the event phases it matches by default.
MATCHER_KINDS = {
    "lane": frozenset({"pre", "post"}),
    "blocked": frozenset({"blocked"}),
}
EVENT_PHASES = frozenset({"pre", "post", "blocked"})

_TABLE_NAME = re.compile(r"^([a-z_]+)\.([A-Za-z0-9_]+)$")
# Any `<dataset>.` prefix naming a dataset the board must never read, quoted or not.
_FORBIDDEN_DATASET_REF = re.compile(r"(?i)(?<![\w.])`?(raw|ops|checkpoint)`?\s*\.")
# Table references after FROM/JOIN, with or without backticks.
_FROM_REF = re.compile(r"(?i)\b(?:FROM|JOIN)\s+`?([\w.-]+)`?")
# A second table in a comma cross-join: FROM `a.b` [AS x], other.t
_COMMA_JOIN_REF = re.compile(
    r"(?i)\b(?:FROM|JOIN)\s+`?[\w.-]+`?(?:\s+(?:AS\s+)?\w+)?\s*,\s*`?([\w.-]+)`?"
)
# Every backtick-quoted dotted identifier, wherever it appears.
_QUOTED_REF = re.compile(r"`([^`]*\.[^`]*)`")
_MUTATING_KEYWORD = re.compile(
    r"(?i)\b(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE"
    r"|EXPORT|LOAD|CALL|EXECUTE|DECLARE|SET|BEGIN)\b"
)
_STRING_LITERAL = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")


class ManifestError(ValueError):
    """The Tile manifest is malformed or reaches outside the working datasets."""


@dataclass(frozen=True)
class Matcher:
    """Maps recorded events to a Tile's activity.

    `kind` is `lane` (one lane per `label`, e.g. a triage subagent) or
    `blocked` (a guardrail deny). `tool` must match the whole tool name;
    `summary`, if set, must match somewhere in the event summary.
    """

    kind: str
    tool: re.Pattern[str]
    summary: re.Pattern[str] | None
    phases: frozenset[str]
    label: str | None

    def matches(self, event: Any) -> bool:
        return (
            event.phase in self.phases
            and self.tool.fullmatch(event.tool) is not None
            and (self.summary is None or self.summary.search(event.summary) is not None)
        )


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
    matchers: tuple[Matcher, ...]


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
    parsed_matchers = tuple(_parse_matcher(tile_id, m) for m in matchers)

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
        matchers=parsed_matchers,
    )


def _parse_matcher(tile_id: str, entry: Any) -> Matcher:
    if not isinstance(entry, dict) or entry.get("kind") not in MATCHER_KINDS:
        raise ManifestError(
            f"Tile {tile_id}: each matcher needs a 'kind' in {sorted(MATCHER_KINDS)}"
        )
    kind = entry["kind"]
    tool = _pattern(tile_id, entry, "tool")
    if tool is None:
        raise ManifestError(f"Tile {tile_id}: each matcher needs a 'tool' regex")
    phases = entry.get("phases", sorted(MATCHER_KINDS[kind]))
    if not isinstance(phases, list) or not phases or not set(phases) <= EVENT_PHASES:
        raise ManifestError(
            f"Tile {tile_id}: matcher 'phases' must be a non-empty subset of {sorted(EVENT_PHASES)}"
        )
    label = entry.get("label")
    if kind == "lane" and (not isinstance(label, str) or not label.strip()):
        raise ManifestError(f"Tile {tile_id}: a lane matcher needs a 'label'")
    return Matcher(
        kind=kind,
        tool=tool,
        summary=_pattern(tile_id, entry, "summary"),
        phases=frozenset(phases),
        label=label if isinstance(label, str) else None,
    )


def _pattern(tile_id: str, entry: dict, key: str) -> re.Pattern[str] | None:
    value = entry.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ManifestError(f"Tile {tile_id}: matcher '{key}' must be a regex string")
    try:
        return re.compile(value)
    except re.error as exc:
        raise ManifestError(
            f"Tile {tile_id}: matcher '{key}' is not a valid regex: {exc}"
        ) from exc


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
    refs = (
        _FROM_REF.findall(query)
        + _COMMA_JOIN_REF.findall(query)
        + _QUOTED_REF.findall(query)
    )
    for ref in refs:
        parts = ref.split(".")
        if len(parts) == 1:
            continue  # a CTE name or UNNEST
        if len(parts) != 2 or ref not in tables:
            raise ManifestError(
                f"Tile {tile_id}: chart query reads {ref!r}; it may only read the Tile's own tables {tables}"
            )
