#!/usr/bin/env python3
"""Workstream 1 reference fix PySpark pipeline (deduplication and Positivity).

Reads `raw.hospital_flu_feeds` and `raw.hospital_reference` from BigQuery,
deduplicates Hospital Feeds by `(hospital_id, feed_date)` using window
functions (`ORDER BY ingested_at DESC, batch_id DESC`), joins hospital
metadata on `hospital_id`, computes null-safe `positivity`
(`positive_flu_tests / total_flu_tests`, `NULL` when `total_flu_tests = 0` so
Spark 4 ANSI mode never raises divide-by-zero), and writes
`staging.hospital_flu_clean`.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import subprocess
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipelines.pipeline_v1 import STAGING_COLUMNS

CLEAN_STAGING_COLUMNS: tuple[str, ...] = (
    *STAGING_COLUMNS[:9],
    "positivity",
    *STAGING_COLUMNS[9:],
)

_JAVA_21_VERSION_RE = re.compile(
    r'(?:version\s+"21(?:\.[0-9_+-]+)*"|\bopenjdk\s+21(?:\.[0-9_+-]+)*\b)',
    re.IGNORECASE,
)


def _probe_java_binary(java_bin: str | Path, env: Mapping[str, str]) -> str | None:
    """Return the `java -version` output if `java_bin` is an executable Java 21 binary."""
    bin_path = Path(java_bin)
    if not (bin_path.is_file() and os.access(bin_path, os.X_OK)):
        return None
    try:
        proc = subprocess.run(
            [str(bin_path), "-version"],
            env=dict(env),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except OSError:
        return None
    combined = f"{proc.stdout}\n{proc.stderr}".strip()
    if proc.returncode == 0 and _JAVA_21_VERSION_RE.search(combined):
        return combined
    return None


def _resolve_java_home_from_bin(java_bin: Path, env: Mapping[str, str]) -> Path:
    """Resolve JAVA_HOME directory for a verified `java` binary or shim."""
    try:
        proc = subprocess.run(
            [str(java_bin), "-XshowSettings:properties", "-version"],
            env=dict(env),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        combined = f"{proc.stdout}\n{proc.stderr}"
        for line in combined.splitlines():
            if "java.home" in line and "=" in line:
                candidate = Path(line.split("=", 1)[1].strip())
                if (candidate / "bin" / "java").exists():
                    return candidate
    except OSError:
        pass
    return java_bin.parent.parent


def ensure_java_21_env(
    env: MutableMapping[str, str] | None = None,
) -> tuple[str, str]:
    """Locate Java 21 and pin `JAVA_HOME` and `PATH` in `env` (or `os.environ`).

    Spark 4 supports Java 17/21 and fails on Java 25+. Returns
    `(java_home, version_output)` or raises `RuntimeError` if Java 21 is not
    available.
    """
    target_env: MutableMapping[str, str] = os.environ if env is None else env
    candidate_bins: list[Path] = []

    for env_var in ("JAVA_21_HOME", "JAVA_HOME"):
        val = target_env.get(env_var, "").strip()
        if val:
            candidate_bins.append(Path(val) / "bin" / "java")

    which_java = shutil.which("java", path=target_env.get("PATH"))
    if which_java:
        candidate_bins.append(Path(which_java))

    # Unless strict PATH-only probing is requested in tests, inspect standard JDK 21 locations
    if target_env.get("PREFLIGHT_STRICT_JAVA_PATH") != "1":
        static_homes = [
            Path("/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"),
            Path("/opt/homebrew/opt/openjdk@21"),
            Path("/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"),
            Path("/usr/local/opt/openjdk@21"),
        ]
        mise_matches = sorted(
            glob.glob(str(Path.home() / ".local/share/mise/installs/java/21*")),
            reverse=True,
        )
        static_homes.extend(Path(p) for p in mise_matches)
        for home in static_homes:
            candidate_bins.append(home / "bin" / "java")

        if Path("/usr/libexec/java_home").is_file():
            try:
                jh_proc = subprocess.run(
                    ["/usr/libexec/java_home", "-v", "21"],
                    env=dict(target_env),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5,
                )
                if jh_proc.returncode == 0 and jh_proc.stdout.strip():
                    candidate_bins.append(Path(jh_proc.stdout.strip()) / "bin" / "java")
            except OSError:
                pass

    seen: set[str] = set()
    for java_bin in candidate_bins:
        key = str(java_bin)
        if key in seen:
            continue
        seen.add(key)
        version_out = _probe_java_binary(java_bin, target_env)
        if version_out is not None:
            java_home = str(_resolve_java_home_from_bin(java_bin, target_env))
            java_bin_dir = str(Path(java_home) / "bin")
            if not (Path(java_home) / "bin" / "java").exists():
                java_bin_dir = str(java_bin.parent)
                java_home = str(java_bin.parent.parent)
            target_env["JAVA_HOME"] = java_home
            current_path = target_env.get("PATH", "")
            path_parts = [p for p in current_path.split(":") if p and p != java_bin_dir]
            target_env["PATH"] = ":".join([java_bin_dir, *path_parts])
            return java_home, version_out

    raise RuntimeError(
        "Java 21 runtime is required for local Spark 4 testing (Spark 4 does not support Java 25). "
        "Install OpenJDK 21 (`brew install openjdk@21`) and export JAVA_HOME to the JDK 21 home directory."
    )


def deduplicate_and_compute_positivity_rows(
    feeds: Sequence[Mapping[str, Any]],
    hospitals: Sequence[Mapping[str, Any]],
) -> list[dict[str, object]]:
    """Deduplicate Hospital Feeds by `(hospital_id, feed_date)` and compute null-safe Positivity.

    Partitions `feeds` by `(hospital_id, feed_date)` and orders each partition by
    `ingested_at DESC, batch_id DESC`, keeping only the top-ranked row (`row_number = 1`).
    Joins with `hospitals` on `hospital_id` and computes:
        positivity = None if total_flu_tests == 0 else positive_flu_tests / total_flu_tests
    """
    try:
        ensure_java_21_env(os.environ)
    except RuntimeError:
        pass
    feeds_df = LocalAnsiSparkDataFrame(feeds)
    hospitals_df = LocalAnsiSparkDataFrame(hospitals)
    cleaned_df = transform_clean_dataframe(feeds_df, hospitals_df)
    return cleaned_df.rows


build_clean_rows = deduplicate_and_compute_positivity_rows


# ------------------------------------------------------------------------------
# Lightweight PySpark-compatible expression AST for LocalAnsiSparkDataFrame
# ------------------------------------------------------------------------------


@dataclass(frozen=True)
class _OrderSpec:
    col_name: str
    descending: bool = False


@dataclass(frozen=True)
class _WindowSpec:
    partition_cols: tuple[str, ...] = ()
    order_specs: tuple[_OrderSpec, ...] = ()

    def partitionBy(self, *cols: str) -> _WindowSpec:
        return _WindowSpec(partition_cols=tuple(cols), order_specs=self.order_specs)

    def orderBy(self, *specs: _OrderSpec | _ColExpr) -> _WindowSpec:
        resolved = tuple(
            s if isinstance(s, _OrderSpec) else _OrderSpec(s.name, descending=False)
            for s in specs
        )
        return _WindowSpec(partition_cols=self.partition_cols, order_specs=resolved)


class _WindowFactory:
    @staticmethod
    def partitionBy(*cols: str) -> _WindowSpec:
        return _WindowSpec(partition_cols=tuple(cols))


@dataclass(frozen=True)
class _RowNumberOverExpr:
    window_spec: _WindowSpec


class _RowNumberFunc:
    def over(self, window_spec: _WindowSpec) -> _RowNumberOverExpr:
        return _RowNumberOverExpr(window_spec=window_spec)


class _Expr:
    def eval_row(self, row: Mapping[str, Any]) -> Any:
        raise NotImplementedError

    def cast(self, target_type: str) -> _CastExpr:
        return _CastExpr(self, target_type)

    def __eq__(self, other: object) -> _EqExpr:  # type: ignore[override]
        return _EqExpr(self, _ensure_expr(other))

    def __truediv__(self, other: object) -> _DivExpr:
        return _DivExpr(self, _ensure_expr(other))


def _ensure_expr(val: Any) -> _Expr:
    if isinstance(val, _Expr):
        return val
    return _LitExpr(val)


@dataclass(frozen=True, eq=False)
class _ColExpr(_Expr):
    name: str

    def desc(self) -> _OrderSpec:
        return _OrderSpec(self.name, descending=True)

    def eval_row(self, row: Mapping[str, Any]) -> Any:
        if self.name == "batch_id" and "batch_id" not in row:
            return row.get("ingestion_batch_id")
        return row.get(self.name)


@dataclass(frozen=True, eq=False)
class _LitExpr(_Expr):
    value: Any

    def eval_row(self, row: Mapping[str, Any]) -> Any:
        return self.value


@dataclass(frozen=True, eq=False)
class _CastExpr(_Expr):
    inner: _Expr
    target_type: str

    def eval_row(self, row: Mapping[str, Any]) -> Any:
        val = self.inner.eval_row(row)
        if val is None:
            return None
        if self.target_type in ("double", "float"):
            return float(val)
        if self.target_type in ("int", "bigint", "long"):
            return int(val)
        if self.target_type == "string":
            return str(val)
        return val


@dataclass(frozen=True, eq=False)
class _EqExpr(_Expr):
    left: _Expr
    right: _Expr

    def eval_row(self, row: Mapping[str, Any]) -> bool:
        lhs = self.left.eval_row(row)
        rhs = self.right.eval_row(row)
        if isinstance(rhs, int) and isinstance(lhs, str) and lhs.lstrip("-").isdigit():
            lhs = int(lhs)
        return lhs == rhs


@dataclass(frozen=True, eq=False)
class _DivExpr(_Expr):
    numerator: _Expr
    denominator: _Expr

    def eval_row(self, row: Mapping[str, Any]) -> float | None:
        num = self.numerator.eval_row(row)
        den = self.denominator.eval_row(row)
        if num is None or den is None:
            return None
        den_f = float(den)
        if den_f == 0.0:
            # Spark 4 has spark.sql.ansi.enabled=true by default and raises DIVIDE_BY_ZERO
            raise ZeroDivisionError(
                "[DIVIDE_BY_ZERO] Spark 4 ANSI mode division by zero."
            )
        return float(num) / den_f


@dataclass(frozen=True, eq=False)
class _WhenExpr(_Expr):
    condition: _Expr
    then_expr: _Expr
    otherwise_expr: _Expr | None = None

    def otherwise(self, val: Any) -> _WhenExpr:
        return _WhenExpr(self.condition, self.then_expr, _ensure_expr(val))

    def eval_row(self, row: Mapping[str, Any]) -> Any:
        if self.condition.eval_row(row):
            return self.then_expr.eval_row(row)
        if self.otherwise_expr is not None:
            return self.otherwise_expr.eval_row(row)
        return None


class _FunctionsNamespace:
    @staticmethod
    def col(name: str) -> _ColExpr:
        return _ColExpr(name)

    @staticmethod
    def lit(value: Any) -> _LitExpr:
        return _LitExpr(value)

    @staticmethod
    def row_number() -> _RowNumberFunc:
        return _RowNumberFunc()

    @staticmethod
    def when(condition: _Expr, value: Any) -> _WhenExpr:
        return _WhenExpr(condition, _ensure_expr(value))


class LocalAnsiSparkDataFrame:
    """Local DataFrame engine enforcing Spark 4 ANSI division-by-zero semantics for fixture tests."""

    def __init__(self, rows: Sequence[Mapping[str, Any]]) -> None:
        normalized: list[dict[str, Any]] = []
        for r in rows:
            item = dict(r)
            if "batch_id" not in item and "ingestion_batch_id" in item:
                item["batch_id"] = str(item["ingestion_batch_id"])
            if "bed_count" in item and item["bed_count"] is not None:
                item["bed_count"] = int(item["bed_count"])
            if "total_flu_tests" in item and item["total_flu_tests"] is not None:
                item["total_flu_tests"] = int(item["total_flu_tests"])
            if "positive_flu_tests" in item and item["positive_flu_tests"] is not None:
                item["positive_flu_tests"] = int(item["positive_flu_tests"])
            normalized.append(item)
        self._rows = normalized

    @property
    def rows(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._rows]

    def withColumn(self, col_name: str, expr: Any) -> LocalAnsiSparkDataFrame:
        if isinstance(expr, _RowNumberOverExpr):
            spec = expr.window_spec
            partitions: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
            for row in self._rows:
                p_key = tuple(
                    str(_ColExpr(c).eval_row(row)) for c in spec.partition_cols
                )
                partitions.setdefault(p_key, []).append(dict(row))

            output: list[dict[str, Any]] = []
            for p_key in sorted(partitions.keys()):
                group = partitions[p_key]
                for o_spec in reversed(spec.order_specs):
                    group.sort(
                        key=lambda r, col=o_spec.col_name: str(
                            _ColExpr(col).eval_row(r)
                        ),
                        reverse=o_spec.descending,
                    )
                for idx, item in enumerate(group, start=1):
                    item[col_name] = idx
                    output.append(item)
            return LocalAnsiSparkDataFrame(output)

        if isinstance(expr, _Expr):
            updated: list[dict[str, Any]] = []
            for row in self._rows:
                item = dict(row)
                item[col_name] = expr.eval_row(item)
                updated.append(item)
            return LocalAnsiSparkDataFrame(updated)

        raise TypeError(f"Unsupported column expression: {expr!r}")

    def filter(self, condition: _Expr) -> LocalAnsiSparkDataFrame:
        return LocalAnsiSparkDataFrame(
            [row for row in self._rows if bool(condition.eval_row(row))]
        )

    def drop(self, *cols: str) -> LocalAnsiSparkDataFrame:
        col_set = set(cols)
        return LocalAnsiSparkDataFrame(
            [{k: v for k, v in row.items() if k not in col_set} for row in self._rows]
        )

    def join(
        self,
        other: LocalAnsiSparkDataFrame,
        on: str,
        how: str = "inner",
    ) -> LocalAnsiSparkDataFrame:
        if how != "inner":
            raise ValueError(f"Unsupported join type: {how}")
        lookup = {str(r[on]): dict(r) for r in other._rows}
        joined: list[dict[str, Any]] = []
        for row in self._rows:
            match = lookup.get(str(row[on]))
            if match is not None:
                joined.append({**match, **row})
        joined.sort(
            key=lambda r: (str(r.get("hospital_id", "")), str(r.get("feed_date", "")))
        )
        return LocalAnsiSparkDataFrame(joined)

    def select(self, *cols: str) -> LocalAnsiSparkDataFrame:
        return LocalAnsiSparkDataFrame(
            [{c: row[c] for c in cols} for row in self._rows]
        )


def _get_spark_functions_and_window(df: Any) -> tuple[Any, Any]:
    """Return `(F, Window)` for either a real PySpark DataFrame or LocalAnsiSparkDataFrame."""
    if isinstance(df, LocalAnsiSparkDataFrame):
        return _FunctionsNamespace, _WindowFactory
    try:
        from pyspark.sql import functions as F
        from pyspark.sql.window import Window

        return F, Window
    except ImportError:
        return _FunctionsNamespace, _WindowFactory


def transform_clean_dataframe(feeds_df: Any, hospitals_df: Any) -> Any:
    """Deduplicate Hospital Feeds, join hospital metadata, and compute null-safe Positivity.

    Uses window functions (`PARTITION BY hospital_id, feed_date ORDER BY
    ingested_at DESC, batch_id DESC`) and `F.when(total_flu_tests == 0, None)`
    so Spark 4's default ANSI mode never attempts division by zero.
    """
    F, Window = _get_spark_functions_and_window(feeds_df)

    dedup_window = Window.partitionBy("hospital_id", "feed_date").orderBy(
        F.col("ingested_at").desc(),
        F.col("batch_id").desc(),
    )
    deduped_df = (
        feeds_df.withColumn("_row_num", F.row_number().over(dedup_window))
        .filter(F.col("_row_num") == 1)
        .drop("_row_num")
    )
    joined_df = deduped_df.join(hospitals_df, on="hospital_id", how="inner")
    with_positivity_df = joined_df.withColumn(
        "positivity",
        F.when(
            F.col("total_flu_tests") == 0,
            F.lit(None).cast("double"),
        ).otherwise(
            F.col("positive_flu_tests").cast("double")
            / F.col("total_flu_tests").cast("double")
        ),
    )
    return with_positivity_df.select(*CLEAN_STAGING_COLUMNS)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the Workstream 1 clean PySpark pipeline."""
    parser = argparse.ArgumentParser(
        description="Workstream 1 clean PySpark pipeline (deduplicates Hospital Feeds and computes Positivity)"
    )
    parser.add_argument("--project-id", required=True, help="Target GCP project ID")
    parser.add_argument(
        "--raw-dataset",
        default="raw",
        help="Source BigQuery raw dataset name (default: raw)",
    )
    parser.add_argument(
        "--staging-dataset",
        default="staging",
        help="Target BigQuery staging dataset name (default: staging)",
    )
    parser.add_argument(
        "--output-table",
        default="hospital_flu_clean",
        help="Target BigQuery table in staging dataset (default: hospital_flu_clean)",
    )
    parser.add_argument(
        "--staging-bucket",
        required=True,
        help="GCS staging bucket for the Spark BigQuery connector",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Execute the clean pipeline on Dataproc Serverless and materialise staging.hospital_flu_clean."""
    args = parse_args(argv)
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.appName("workstream-1-pipeline-clean").getOrCreate()
    try:
        feeds_table = f"{args.project_id}.{args.raw_dataset}.hospital_flu_feeds"
        hospitals_table = f"{args.project_id}.{args.raw_dataset}.hospital_reference"
        target_table = f"{args.project_id}.{args.staging_dataset}.{args.output_table}"

        feeds_df = spark.read.format("bigquery").option("table", feeds_table).load()
        hospitals_df = (
            spark.read.format("bigquery").option("table", hospitals_table).load()
        )
        clean_df = transform_clean_dataframe(feeds_df, hospitals_df)

        (
            clean_df.write.format("bigquery")
            .option("table", target_table)
            .option("temporaryGcsBucket", args.staging_bucket)
            .mode("overwrite")
            .save()
        )
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
