"""Dataset boundary guard: repo code must not write raw/ops or touch checkpoint.

Rule 3 of `.agents/plugins/ds-command-center/rules/AGENTS.md` makes the `raw`
and `ops` datasets read-only, and rule 4 puts `checkpoint` off-limits. This
module scans repo code (`bin/*`, `bin/lib/*`, `sql/**`, `lib/**`, `jobs/**`,
the `ds-command-center` sidecars) and fails on mutating SQL or bq invocations that target `raw`/`ops`, and on
any reference to the `checkpoint` dataset. Presenter-owned provisioning scripts
are exempt through `_PROVISIONING_ALLOWLIST`; data-only lines (such as
preflight's guardrail-hook probe payloads) are exempt only through a per-line
marker with a stated reason.

Cloud Storage invocations (`pinned_storage`, `gcloud storage`) address
`gs://` objects, never BigQuery datasets, so a `raw/` or `ops/` object prefix
is not a dataset reference and is not flagged; storage writes into a dataset
only happen through `bq load`, which is covered. The scan is line-oriented:
backslash continuations are joined, but a Python argv list split over several
lines is only caught through its `--dataset`/`--destination_table` value.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from typing import NamedTuple

from tests.helpers import WORKTREE_ROOT

# Top-level files in these directories are scanned.
_SCAN_FILE_DIRS: tuple[str, ...] = ("bin", "bin/lib")
# Every file under these directories is scanned recursively.
_SCAN_TREE_DIRS: tuple[str, ...] = (
    "sql",
    "lib",
    "jobs",
    ".agents/plugins/ds-command-center/sidecars",
)

_READ_ONLY_DATASETS = ("raw", "ops")
_OFF_LIMITS_DATASET = "checkpoint"


class _Allowance(NamedTuple):
    datasets: frozenset[str]
    reason: str


# Presenter-owned provisioning scripts that legitimately write (or, for
# checkpoint, read) these datasets, each with the datasets it may touch and a
# one-line reason. Runtime and runner scripts (bin/run-*, bin/verify-*,
# bin/preflight, lib/*, sql/*) must never be added here.
_PROVISIONING_ALLOWLIST: dict[str, _Allowance] = {
    "bin/load-raw-ops": _Allowance(
        frozenset({"raw", "ops"}),
        "loads the raw and ops Start Point tables from the Data Generator output",
    ),
    "bin/load-reveal": _Allowance(
        frozenset({"raw"}),
        "loads raw.hospital_flu_feeds_reveal from the runtime Reveal source",
    ),
    "bin/checkpoint": _Allowance(
        frozenset({"checkpoint"}),
        "builds Checkpoint tables into checkpoint and swaps them into live targets",
    ),
    "bin/reset": _Allowance(
        frozenset({"checkpoint"}),
        "probes checkpoint before restoring a Start Point through bin/checkpoint",
    ),
}
_NO_ALLOWANCE = _Allowance(frozenset(), "")

# Per-line escape hatch for lines that hold forbidden SQL or a checkpoint table
# name as data, not as an action (preflight's guardrail-hook probe payloads).
# The existing Pinning marker or this sibling marker is accepted; either one
# needs a non-blank reason. Neither exempts a mutating bq invocation or a line
# that runs a query (a pinned_* wrapper, a client `.query(`/`.execute(` call,
# or a subprocess/os call).
_ALLOW_MARKER = re.compile(r"# (?:pinning-guard|dataset-guard): allow \(\s*\S[^)]*\)")
_QUERY_CALL = re.compile(
    r"(?<![\w-])pinned_\w+"
    r"|\.(?:query|execute\w*)\s*\("
    r"|\b(?:subprocess|os)\.\w+\s*\("
)

_READ_ONLY = "(?:" + "|".join(_READ_ONLY_DATASETS) + ")"
_QUOTE = r"(?:\\?[`'\"])"
# Optional quote and optional `project:` / `project.` / `` `project`. ``
# prefix in front of a dataset name.
_PROJECT_PREFIX = rf"{_QUOTE}?(?:[\w${{}}-]+{_QUOTE}?[:.]{_QUOTE}?)?"
# Characters that may not precede a dataset reference (so `/raw/feeds.csv`,
# `self.raw` and `${raw}` don't count).
_NOT_AFTER = r"(?<![\w/.${}-])"


def _ref(ds: str) -> str:
    """Regex for a reference to dataset `ds`, captured in group `ds`.

    The name must not be followed by a word char, `/` or `-`, so
    `raw_dataset`, `raw/` and `ops-log` don't count.
    """
    return rf"{_NOT_AFTER}{_PROJECT_PREFIX}(?P<ds>{ds})(?![\w/-])"


# Statement keyword(s) that put the next identifier in the written-to position.
# Matched in upper or lower case only, so prose such as "Update raw tables"
# isn't mistaken for SQL.
_SQL_OBJECT = r"(?:TABLE\s+FUNCTION|TABLE|VIEW|SCHEMA|FUNCTION|PROCEDURE|MODEL)"
_SQL_TARGET_PREFIX = (
    r"\b(?:"
    r"INSERT\s+(?:INTO\s+)?"
    r"|UPDATE\s+"
    r"|DELETE\s+(?:FROM\s+)?"
    r"|MERGE\s+(?:INTO\s+)?"
    r"|TRUNCATE\s+TABLE\s+"
    r"|LOAD\s+DATA\s+(?:INTO|OVERWRITE)\s+(?:TEMP\s+TABLE\s+)?"
    r"|DROP\s+(?:EXTERNAL\s+|MATERIALIZED\s+|SNAPSHOT\s+)?"
    rf"{_SQL_OBJECT}\s+(?:IF\s+EXISTS\s+)?"
    r"|ALTER\s+(?:MATERIALIZED\s+)?(?:TABLE|VIEW|SCHEMA|MODEL)\s+(?:IF\s+EXISTS\s+)?"
    r"|CREATE\s+(?:OR\s+REPLACE\s+)?"
    r"(?:TEMP(?:ORARY)?\s+|EXTERNAL\s+|SNAPSHOT\s+|MATERIALIZED\s+)?"
    rf"{_SQL_OBJECT}\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"|(?:CREATE\s+(?:OR\s+REPLACE\s+)?|DROP\s+)"
    r"(?:ROW\s+ACCESS\s+POLICY|(?:SEARCH\s+|VECTOR\s+)?INDEX)\s+"
    r"(?:IF\s+(?:NOT\s+)?EXISTS\s+)?\S+\s+ON\s+"
    r")"
)
# Lower-case the keywords only, leaving escapes such as `\S` intact.
_SQL_TARGET_PREFIX_LOWER = re.sub(
    r"(?<!\\)[A-Z]+", lambda m: m.group(0).lower(), _SQL_TARGET_PREFIX
)

_MUTATING_SUBCOMMAND = r"(?:mk|rm|load|cp|update|insert)"
_BQ_SUBCOMMAND = rf"{_MUTATING_SUBCOMMAND}|ls|show|head|query|extract"
# A bq global flag, with an `=value` or a space-separated value that is not
# itself a flag or subcommand.
_BQ_FLAG = rf"\s+--?[\w-]+(?:=\S+|\s+(?!-|{_MUTATING_SUBCOMMAND}\b)[^\s-]\S*)?"
# A mutating bq call (wrapped or not, shell or Python argv list) or a
# pinned_label call, then anything on the same logical line before the target.
_BQ_MUTATION = (
    rf"(?:(?<![\w-])(?:pinned_)?bq(?:{_BQ_FLAG})*\s+{_MUTATING_SUBCOMMAND}\b"
    rf"|[\"']bq[\"']\s*,\s*(?:[\"']--?[\w-]+(?:=[^\"']*)?[\"']\s*,\s*)*"
    rf"[\"']{_MUTATING_SUBCOMMAND}[\"']"
    r"|(?<![\w-])pinned_label\b)"
    r"[^\n]*?"
)
# A destination or dataset flag immediately followed by its value (including
# an argparse definition such as `"--dataset", default="ops"`, or an argv
# list element pair such as `"--dataset", "ops"`).
_DATASET_FLAG = (
    r"(?<![\w-])--(?:destination_table|dataset_id|dataset)(?![\w-])"
    r"(?:=|\s+|[\"']\s*,\s*(?=[\"'])|[\"']\s*,[^)]*?\bdefault\s*=\s*)"
)


class _Rule(NamedTuple):
    label: str
    patterns: tuple[re.Pattern[str], ...]  # each captures the dataset in group `ds`
    marker_exempts: bool  # may the per-line allow marker exempt a match?


_RULES: tuple[_Rule, ...] = (
    _Rule(
        "mutating SQL targeting a read-only dataset",
        (
            re.compile(_SQL_TARGET_PREFIX + _ref(_READ_ONLY)),
            re.compile(_SQL_TARGET_PREFIX_LOWER + _ref(_READ_ONLY)),
        ),
        True,
    ),
    _Rule(
        "mutating bq invocation targeting a read-only dataset",
        (
            re.compile(_BQ_MUTATION + _ref(_READ_ONLY)),
            re.compile(_DATASET_FLAG + _ref(_READ_ONLY)),
        ),
        False,
    ),
    _Rule(
        "reference to the off-limits checkpoint dataset",
        (
            # checkpoint.<table>, `project.checkpoint.<table>`, project:checkpoint.<table>
            re.compile(
                rf"{_NOT_AFTER}{_PROJECT_PREFIX}(?P<ds>{_OFF_LIMITS_DATASET})(?=\.[A-Za-z_])"
            ),
            # "checkpoint" as a quoted token, an assigned value, or project:checkpoint
            re.compile(
                rf"(?<=[`'\"=:])(?P<ds>{_OFF_LIMITS_DATASET})(?=\\?[`'\"]|[^\w/.-]|$)",
                re.MULTILINE,
            ),
            # a bare argument to a bq subcommand, e.g. `pinned_bq ls checkpoint`
            re.compile(
                rf"(?<![\w-])(?:pinned_)?bq(?:{_BQ_FLAG})*\s+(?:{_BQ_SUBCOMMAND})\b"
                rf"[^\n]*?\s(?P<ds>{_OFF_LIMITS_DATASET})(?![\w/.-])"
            ),
            # --dataset checkpoint / --destination_table=checkpoint.x
            re.compile(_DATASET_FLAG + _ref(_OFF_LIMITS_DATASET)),
        ),
        True,
    ),
)

# Full-line shell/Python (`#`) and SQL (`-- `) comments; `--flag` lines are code.
_COMMENT_LINE = re.compile(r"^\s*(?:#|--(?=\s|$))")


class _Violation(NamedTuple):
    line: int
    dataset: str
    rule: str
    text: str


def _prepare_text(text: str) -> str:
    """Blank full-line comments and join backslash continuations, keeping offsets."""
    lines = [
        re.sub(r".", " ", line) if _COMMENT_LINE.match(line) else line
        for line in text.split("\n")
    ]
    return "\n".join(lines).replace("\\\n", "  ")


def _scan_violations(path: Path) -> list[_Violation]:
    """Return one boundary violation per offending line, in line order."""
    original = path.read_text(encoding="utf-8")
    lines = original.split("\n")
    prepared = _prepare_text(original)
    found: dict[int, _Violation] = {}
    for rule in _RULES:
        for pattern in rule.patterns:
            for match in pattern.finditer(prepared):
                lineno = original.count("\n", 0, match.start("ds")) + 1
                line = lines[lineno - 1].strip()
                first_line = lines[original.count("\n", 0, match.start())]
                if (
                    rule.marker_exempts
                    and _ALLOW_MARKER.search(first_line)
                    and _ALLOW_MARKER.search(line)
                    and not _QUERY_CALL.search(line)
                ):
                    continue
                found.setdefault(
                    lineno, _Violation(lineno, match.group("ds"), rule.label, line)
                )
    return [found[k] for k in sorted(found)]


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    for rel in _SCAN_FILE_DIRS:
        directory = WORKTREE_ROOT / rel
        if directory.is_dir():
            files.extend(p for p in sorted(directory.iterdir()) if p.is_file())
    for rel in _SCAN_TREE_DIRS:
        directory = WORKTREE_ROOT / rel
        if directory.is_dir():
            files.extend(
                p
                for p in sorted(directory.rglob("*"))
                if p.is_file() and not {"__pycache__", "node_modules"} & set(p.parts)
            )
    return files


class TestDatasetBoundaryScanner(unittest.TestCase):
    def _flagged_lines(self, lines: tuple[str, ...]) -> set[int]:
        with tempfile.TemporaryDirectory() as tmpdir:
            script = Path(tmpdir) / "script"
            script.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return {v.line for v in _scan_violations(script)}

    def test_flags_writes_to_raw_and_ops_and_any_checkpoint_reference(self) -> None:
        """Mutating SQL or bq invocations on raw/ops and checkpoint table references are flagged."""
        flagged = (
            'pinned_bq rm -f -t "${PROJECT_ID}:ops.${temp_table}"',
            '    --dataset "ops" \\',
            '    "--dataset", default="ops", help="Target BigQuery dataset"',
            'pinned_bq load --replace "${PROJECT_ID}:raw.hospital_flu_feeds" x.csv',
            "pinned_bq --format=json mk -t raw.new_table",
            "pinned_bq query --destination_table=raw.copy 'SELECT 1'",
            'pinned_label "${PROJECT_ID}:ops.pipeline_run_log"',
            'subprocess.run(["bq", "rm", "-f", "ops.pipeline_run_log"])',
            "INSERT INTO `raw.hospital_flu_feeds` SELECT 1",
            "delete from ops.pipeline_run_log where true",
            "UPDATE `{project_id}.raw.hospital_reference` SET x = 1",
            "MERGE ops.pipeline_run_log AS t USING staging.x AS s ON TRUE",
            "TRUNCATE TABLE raw.hospital_flu_feeds",
            "DROP TABLE IF EXISTS \\`${PROJECT_ID}.ops.pipeline_run_log\\`",
            "ALTER TABLE raw.hospital_reference ADD COLUMN y INT64",
            "CREATE OR REPLACE TABLE ops.shadow AS SELECT 1",
            "DROP SCHEMA raw",
            'pinned_bq show "${PROJECT_ID}:checkpoint.ws1_staging_hospital_flu"',
            "SELECT * FROM `checkpoint.ws1_attribution`",
            "pinned_bq ls --dataset checkpoint",
            "pinned_bq ls checkpoint",
            "pinned_bq ls --project_id=p checkpoint",
            "DATASET=checkpoint",
            "pinned_bq --format json rm -f -t ops.pipeline_run_log",
            "pinned_bq query --dataset_id=ops 'SELECT 1'",
            '["bq", "query", "--dataset", "raw"]',
            "INSERT INTO `my-proj`.raw.hospital_flu_feeds SELECT 1",
            "CREATE OR REPLACE MODEL ops.m OPTIONS(model_type='linear_reg') AS SELECT 1",
            "LOAD DATA OVERWRITE raw.hospital_flu_feeds FROM FILES(uris=['x'])",
            "DROP TABLE FUNCTION raw.f",
            "CREATE ROW ACCESS POLICY p ON raw.hospital_reference FILTER USING (TRUE)",
            # The marker never exempts a mutating bq invocation or a query call.
            'pinned_bq rm -f -t "ops.x"  # dataset-guard: allow (not really data)',
            'pinned_bq query "DELETE FROM ops.x"  # dataset-guard: allow (sneaky)',
            'client.query("DELETE FROM ops.x")  # dataset-guard: allow (sneaky)',
            # A marker without a (non-blank) reason exempts nothing.
            "{'sql': 'SELECT * FROM checkpoint.clean_feeds'},  # dataset-guard: allow",
            "{'sql': 'SELECT * FROM checkpoint.clean_feeds'},  # dataset-guard: allow ( )",
        )
        clean = (
            "SELECT COUNT(*) FROM `raw.hospital_flu_feeds`",
            'pinned_bq show "${PROJECT_ID}:ops.pipeline_run_log"',
            "CREATE OR REPLACE TABLE staging.clean AS SELECT * FROM raw.hospital_flu_feeds",
            'pinned_bq rm -f -t "${PROJECT_ID}:staging.${temp_table}"',
            '    --dataset "staging" \\',
            '    --raw-dataset "raw" \\',
            '    --dataset-dir "${DATASET_DIR}/raw" \\',
            'pinned_bq load --replace "${PROJECT_ID}:staging.x" "${DATASET_ROOT}/raw/feeds.csv"',
            'MANIFEST_DIR="${REPO_ROOT}/checkpoints/manifest.d"',
            '    "checkpoint_id": "ws2_experiment_trials",',
            'echo "Build/materialise Checkpoint table(s) into checkpoint dataset"',
            "# DELETE FROM ops.pipeline_run_log is forbidden (comment)",
            "-- DROP TABLE raw.hospital_flu_feeds (comment)",
            "echo 'Update the raw tables first'",
            "echo 'Update raw tables, then Insert ops data'",
            "pinned_bq --quiet ls staging",
            "{'sql': 'DELETE FROM ops.pipeline_run_log'},  # dataset-guard: allow (hook probe payload)",
            "{'sql': 'SELECT * FROM checkpoint.clean_feeds'},  # pinning-guard: allow (hook probe payload)",
        )
        flagged_lines = self._flagged_lines(flagged + clean)
        self.assertEqual(flagged_lines, set(range(1, len(flagged) + 1)))

    def test_multi_line_sql_target_is_flagged_on_the_dataset_line(self) -> None:
        """A mutating statement whose target sits on the next line is still caught."""
        lines = (
            "CREATE OR REPLACE TABLE",
            "  `raw.hospital_flu_feeds` AS",
            "SELECT 1;",
        )
        self.assertEqual(self._flagged_lines(lines), {2})

    def test_multi_line_argparse_dataset_default_is_flagged(self) -> None:
        """An argparse `--dataset` default of ops split across lines (ruff style) is caught."""
        lines = (
            "parser.add_argument(",
            '    "--dataset",',
            '    default="ops",',
            '    help="Target BigQuery dataset",',
            ")",
            'parser.add_argument("--dataset", default="staging")',
        )
        self.assertEqual(self._flagged_lines(lines), {3})


class TestDatasetBoundaryAllowlist(unittest.TestCase):
    def test_allowlist_holds_only_existing_provisioning_scripts_with_reasons(
        self,
    ) -> None:
        """Every allowlist entry is an existing bin/ provisioning script with datasets and a reason."""
        allowed_datasets = {*_READ_ONLY_DATASETS, _OFF_LIMITS_DATASET}
        runtime_script = re.compile(r"^bin/(?:run-|verify-|preflight$|lib/)")
        for rel, (datasets, reason) in _PROVISIONING_ALLOWLIST.items():
            with self.subTest(script=rel):
                self.assertTrue((WORKTREE_ROOT / rel).is_file(), f"{rel} is missing")
                self.assertTrue(rel.startswith("bin/"), rel)
                self.assertIsNone(runtime_script.match(rel), rel)
                self.assertLessEqual(set(datasets), allowed_datasets, rel)
                self.assertTrue(datasets and reason.strip(), rel)


class TestRepoCodeRespectsDatasetBoundaries(unittest.TestCase):
    def test_repo_code_never_writes_raw_or_ops_or_touches_checkpoint(self) -> None:
        """bin/*, bin/lib/*, sql/**, lib/** and jobs/** stay inside the dataset boundaries."""
        unexpected: dict[str, list[str]] = {}
        for path in _scanned_files():
            rel = path.relative_to(WORKTREE_ROOT).as_posix()
            allowed = _PROVISIONING_ALLOWLIST.get(rel, _NO_ALLOWANCE).datasets
            violations = [
                f"L{v.line} ({v.rule}): {v.text}"
                for v in _scan_violations(path)
                if v.dataset not in allowed
            ]
            if violations:
                unexpected[rel] = violations
        self.assertEqual(unexpected, {}, f"Dataset boundary violations: {unexpected}")


if __name__ == "__main__":
    unittest.main()
