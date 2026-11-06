"""Table catalogs: where the board learns which working tables exist.

A catalog answers two questions: `table_info(table)` (metadata only, no scan)
and `run_query(sql)` (a chart query, run once per landing). `BigQueryCatalog`
reads BigQuery under the presenter's user ADC with project and location pinned
from `demo.env`; `FakeCatalog` is the offline stand-in for tests and the
standalone launcher.
"""

from __future__ import annotations

import datetime as _dt
import decimal
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class TableInfo:
    num_rows: int
    modified: str


class TableCatalog(Protocol):
    def table_info(self, table: str) -> TableInfo | None:
        """Metadata for `dataset.table`, or None if it does not exist."""

    def run_query(self, sql: str) -> list[dict[str, Any]]:
        """Run a read-only chart query and return JSON-safe rows."""


class FakeCatalog:
    """In-memory catalog: tables with row counts, modified stamps and chart rows.

    Built `from_json`, it re-reads its file whenever the file's mtime changes,
    so a rehearsal can land a Tile by editing the file while the board runs.
    """

    def __init__(self, tables: dict[str, dict[str, Any]] | None = None) -> None:
        self._lock = threading.Lock()
        self._tables: dict[str, dict[str, Any]] = {}
        self._source: Path | None = None
        self._source_mtime: int | None = None
        self.queries_run = 0
        self.failing = False
        for name, spec in (tables or {}).items():
            self.put_table(name, **spec)

    @classmethod
    def from_json(cls, path: str | Path) -> FakeCatalog:
        catalog = cls()
        catalog._source = Path(path)
        catalog._reload_if_changed()
        return catalog

    def _reload_if_changed(self) -> None:
        """Replace the tables from the source file if its mtime changed.

        A table without its own `modified` stamp takes the file's mtime, so an
        edit re-runs the chart query of a Tile that has already landed.
        """
        if self._source is None:
            return
        mtime = self._source.stat().st_mtime_ns
        with self._lock:
            if mtime == self._source_mtime:
                return
        tables = json.loads(self._source.read_text(encoding="utf-8")).get("tables", {})
        fresh = FakeCatalog()
        for name, spec in tables.items():
            fresh.put_table(name, **{"modified": str(mtime), **spec})
        # Swap in one step so a concurrent reader never sees an empty catalog.
        with self._lock:
            self._tables = fresh._tables
            self._source_mtime = mtime

    def put_table(
        self,
        table: str,
        num_rows: int = 1,
        modified: str = "1",
        rows: list[dict[str, Any]] | None = None,
    ) -> None:
        with self._lock:
            self._tables[table] = {
                "num_rows": num_rows,
                "modified": modified,
                "rows": list(rows or []),
            }

    def table_info(self, table: str) -> TableInfo | None:
        self._reload_if_changed()
        with self._lock:
            if self.failing:
                raise ConnectionError("fake catalog: transient failure")
            spec = self._tables.get(table)
            return TableInfo(spec["num_rows"], spec["modified"]) if spec else None

    def run_query(self, sql: str) -> list[dict[str, Any]]:
        """The rows of the known table named earliest in `sql`."""
        self._reload_if_changed()
        with self._lock:
            if self.failing:
                raise ConnectionError("fake catalog: transient failure")
            self.queries_run += 1
            named = []
            for name, spec in self._tables.items():
                found = re.search(rf"`?{re.escape(name)}`?(?![\w])", sql)
                if found:
                    named.append((found.start(), spec))
            if named:
                _, spec = min(named, key=lambda pair: pair[0])
                return [dict(row) for row in spec["rows"]]
            raise LookupError(f"fake catalog: query reads no known table: {sql[:80]}")


class BigQueryCatalog:
    """BigQuery under user ADC; every call pinned to the demo.env project and location."""

    def __init__(self, project: str, location: str, client: Any) -> None:
        self._project = project
        self._location = location
        self._client = client

    @classmethod
    def from_user_adc(cls, project: str, location: str) -> BigQueryCatalog:
        import google.auth
        from google.cloud import bigquery
        from google.oauth2.credentials import Credentials as UserCredentials

        credentials, _ = google.auth.default(quota_project_id=project)
        is_user_adc = isinstance(credentials, UserCredentials)
        if not is_user_adc:
            raise RuntimeError(
                "The Evidence Board reads BigQuery as the presenter only: "
                "run `gcloud auth application-default login` for user ADC."
            )
        return cls(
            project,
            location,
            bigquery.Client(
                project=project, credentials=credentials, location=location
            ),
        )

    def table_info(self, table: str) -> TableInfo | None:
        try:
            meta = self._client.get_table(f"{self._project}.{table}")
        except Exception as exc:
            if getattr(exc, "code", None) == 404:
                return None
            raise
        modified = meta.modified.isoformat() if meta.modified else ""
        return TableInfo(int(meta.num_rows or 0), modified)

    def run_query(self, sql: str) -> list[dict[str, Any]]:
        job = self._client.query(sql, project=self._project, location=self._location)
        return [
            {key: _json_safe(value) for key, value in row.items()}
            for row in job.result()
        ]


def _json_safe(value: Any) -> Any:
    if isinstance(value, (_dt.date, _dt.datetime, _dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return value


class PinningError(RuntimeError):
    """demo.env is missing or still holds placeholder project/region values."""


_ENV_LINE = re.compile(r"^\s*(?:export\s+)?(PROJECT_ID|REGION)=(.*)$")


def load_pinning(workspace: str | Path) -> tuple[str, str]:
    """Read PROJECT_ID and REGION from `<workspace>/demo.env` (Pinning rule)."""
    env_file = Path(workspace) / "demo.env"
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise PinningError(
            f"cannot read {env_file}: copy demo.env.example to demo.env"
        ) from exc
    values: dict[str, str] = {}
    for line in lines:
        match = _ENV_LINE.match(line)
        if match:
            values[match.group(1)] = (
                match.group(2).split(" #", 1)[0].strip().strip("'\"")
            )
    for key in ("PROJECT_ID", "REGION"):
        value = values.get(key, "")
        if not value or value.startswith("your-") or "$" in value:
            raise PinningError(
                f"{env_file}: set {key} to your own value (found {value!r})"
            )
    return values["PROJECT_ID"], values["REGION"]
