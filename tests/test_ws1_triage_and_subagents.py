"""Tests for Issue #12: Workstream 1 triage subagents, stats-reviewer, rehearsal Attribution, and Checkpoints."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from typing import Any

from lib.ws1_triage import (
    ATTRIBUTION_TOLERANCE_POINTS,
    build_eda_heatmap,
    compare_attribution_to_answer_key,
    load_dataset_tables,
    load_ws1_checkpoint_manifests,
    reconcile_attribution,
    run_stats_reviewer_checks,
    triage_outbreak_and_seasonal_ramp,
    triage_pipeline_defect,
    triage_sampling_artifact,
)
from tests.helpers import (
    VERIFY_START_POINT_BIN,
    WORKTREE_ROOT,
    setup_preflight_test_env,
)

PLUGIN_DIR = WORKTREE_ROOT / ".agents" / "plugins" / "ds-command-center"
AGENTS_DIR = PLUGIN_DIR / "agents"
MOCK_DATASET_DIR = WORKTREE_ROOT / "fixtures" / "mock_dataset"
MOCK_ANSWER_KEY_PATH = WORKTREE_ROOT / "fixtures" / "mock_withheld" / "answer_key.json"
MAX_SUBAGENT_LINES = 60

EXPECTED_SUBAGENTS: tuple[str, ...] = (
    "distribution-triage",
    "sampling-triage",
    "pipeline-triage",
    "stats-reviewer",
)


def _parse_frontmatter(markdown_text: str) -> tuple[dict[str, str], str]:
    """Parse simple YAML frontmatter (`--- ... ---`) from a subagent markdown file."""
    lines = markdown_text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("Missing opening YAML frontmatter delimiter '---'")
    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        raise ValueError("Missing closing YAML frontmatter delimiter '---'")

    meta: dict[str, str] = {}
    for line in lines[1:end_idx]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, val = stripped.partition(":")
        if not sep:
            raise ValueError(f"Invalid frontmatter line: {line!r}")
        meta[key.strip()] = val.strip()

    body = "\n".join(lines[end_idx + 1 :]).strip()
    return meta, body


class TestWorkstream1SubagentsAndTriage(unittest.TestCase):
    def test_four_subagents_live_in_ds_command_center_and_fit_on_screen(self) -> None:
        """All 4 subagents must live in .agents/plugins/ds-command-center/agents/, be <= 60 lines, and have valid frontmatter."""
        self.assertTrue(AGENTS_DIR.is_dir(), f"Expected directory {AGENTS_DIR}")

        plugin_manifest = json.loads(
            (PLUGIN_DIR / "plugin.json").read_text(encoding="utf-8")
        )
        registered_agents = plugin_manifest.get("agents", [])

        rules_text = (PLUGIN_DIR / "rules" / "AGENTS.md").read_text(encoding="utf-8")

        for agent_name in EXPECTED_SUBAGENTS:
            agent_file = AGENTS_DIR / f"{agent_name}.md"
            self.assertTrue(agent_file.is_file(), f"Missing subagent file {agent_file}")

            raw_text = agent_file.read_text(encoding="utf-8")
            line_count = len(raw_text.splitlines())
            self.assertLessEqual(
                line_count,
                MAX_SUBAGENT_LINES,
                f"{agent_file.name} has {line_count} lines (must be <= {MAX_SUBAGENT_LINES} lines to fit on screen)",
            )
            self.assertGreaterEqual(
                line_count,
                15,
                f"{agent_file.name} must contain substantive instructions",
            )

            frontmatter, body = _parse_frontmatter(raw_text)
            self.assertEqual(frontmatter.get("name"), agent_name)
            self.assertTrue(
                frontmatter.get("description"),
                f"{agent_file.name} must define a non-empty description",
            )
            self.assertTrue(
                frontmatter.get("model"),
                f"{agent_file.name} must define a model field",
            )
            self.assertTrue(body, f"{agent_file.name} must have a markdown body")

            self.assertIn(
                f"agents/{agent_name}.md",
                registered_agents,
                f"plugin.json must register agents/{agent_name}.md",
            )
            self.assertIn(
                agent_name,
                rules_text,
                f"rules/AGENTS.md must reference {agent_name}",
            )

    def test_pipeline_subagent_correlates_anomalies_with_pipeline_run_log(self) -> None:
        """pipeline-triage.md and triage_pipeline_defect must correlate duplicate Hospital Feeds with ops.pipeline_run_log."""
        pipeline_md = (AGENTS_DIR / "pipeline-triage.md").read_text(encoding="utf-8")
        self.assertIn("ops.pipeline_run_log", pipeline_md)
        self.assertIn("staging.hospital_flu", pipeline_md)
        self.assertIn("backfill", pipeline_md.lower())
        self.assertIn("Hospital Feed", pipeline_md)
        self.assertIn("Pipeline Defect", pipeline_md)

        staging_rows, run_log_rows = load_dataset_tables(MOCK_DATASET_DIR)
        result = triage_pipeline_defect(staging_rows, run_log_rows)

        self.assertEqual(result["cause"], "pipeline_defect")
        self.assertEqual(result["correlated_run_id"], "RUN-20261031-BF01")
        self.assertEqual(result["duplicate_row_count"], 20)
        self.assertEqual(
            result["affected_hospitals"],
            ["HOSP_NE_003", "HOSP_NE_007", "HOSP_NE_011", "HOSP_NE_014"],
        )
        self.assertEqual(result["start_date"], "2026-10-26")
        self.assertEqual(result["end_date"], "2026-10-30")
        self.assertAlmostEqual(result["contributed_points"], 15.0, places=1)
        self.assertEqual(len(result["correlated_runs"]), 1)
        self.assertEqual(
            int(result["correlated_runs"][0]["rows_written"]),
            result["duplicate_row_count"],
        )

    def test_stats_reviewer_challenges_counts_vs_rates_small_samples_and_simpsons_paradox(
        self,
    ) -> None:
        """stats-reviewer.md and run_stats_reviewer_checks must challenge counts vs Positivity, small-sample hospitals, and Simpson's paradox."""
        reviewer_md = (AGENTS_DIR / "stats-reviewer.md").read_text(encoding="utf-8")
        self.assertIn("Positivity", reviewer_md)
        self.assertIn("raw", reviewer_md.lower())
        self.assertIn("count", reviewer_md.lower())
        self.assertIn("small-sample", reviewer_md.lower())
        self.assertIn("Simpson's Paradox", reviewer_md)
        self.assertIn("region", reviewer_md.lower())

        staging_rows, _ = load_dataset_tables(MOCK_DATASET_DIR)
        checks = run_stats_reviewer_checks(staging_rows)

        self.assertTrue(checks["counts_vs_positivity"]["passed"])
        self.assertAlmostEqual(
            checks["counts_vs_positivity"]["raw_spike_pct"], 35.0, places=2
        )

        self.assertTrue(checks["small_sample_hospitals"]["passed"])
        self.assertGreater(
            checks["small_sample_hospitals"]["zero_test_rows_guarded"], 0
        )

        simpson = checks["simpsons_paradox"]
        self.assertTrue(simpson["passed"])
        self.assertTrue(simpson["every_non_outbreak_hospital_rose"])
        self.assertGreater(
            simpson["urban_cutoff_positivity"], simpson["urban_prior_positivity"]
        )
        self.assertGreater(
            simpson["nonurban_cutoff_positivity"], simpson["nonurban_prior_positivity"]
        )
        self.assertLess(
            simpson["pooled_cutoff_positivity"], simpson["pooled_prior_positivity"]
        )

    def test_rehearsal_on_mock_dataset_produces_eda_heatmap_and_attribution_matching_answer_key(
        self,
    ) -> None:
        """Rehearsal on fixtures/mock_dataset must produce an EDA heatmap and Attribution table matching the mock Answer Key within tolerance."""
        # Verify production module never hardcodes mock_withheld or answer_key.json paths
        triage_src = (WORKTREE_ROOT / "lib" / "ws1_triage.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("mock_withheld", triage_src)
        self.assertNotIn("answer_key.json", triage_src)

        staging_rows, run_log_rows = load_dataset_tables(MOCK_DATASET_DIR)

        heatmap = build_eda_heatmap(staging_rows)
        self.assertEqual(heatmap["target_region"], "Northeast")
        self.assertEqual(heatmap["ne_prior_positives"], 1000)
        self.assertEqual(heatmap["ne_cutoff_positives"], 1350)
        self.assertAlmostEqual(heatmap["headline_spike_pct"], 35.0, places=2)
        self.assertEqual(len(heatmap["hospital_summaries"]), 20)

        # Verify individual triage functions
        sampling_res = triage_sampling_artifact(staging_rows)
        self.assertEqual(
            sampling_res["affected_hospitals"],
            ["HOSP_NE_002", "HOSP_NE_005", "HOSP_NE_009"],
        )
        self.assertGreater(sampling_res["volume_growth_pct"], 45.0)
        self.assertAlmostEqual(sampling_res["contributed_points"], 8.0, places=1)

        dist_res = triage_outbreak_and_seasonal_ramp(staging_rows)
        self.assertEqual(
            dist_res["outbreak"]["affected_hospitals"],
            ["HOSP_NE_001", "HOSP_NE_004", "HOSP_NE_006"],
        )
        self.assertAlmostEqual(
            dist_res["outbreak"]["contributed_points"], 7.0, places=1
        )
        self.assertAlmostEqual(
            dist_res["seasonal_ramp"]["contributed_points"], 5.0, places=1
        )

        # Reconcile all 4 causes and compare to Answer Key within recorded tolerance
        attribution_rows = reconcile_attribution(
            staging_rows=staging_rows, run_log_rows=run_log_rows
        )
        self.assertEqual(len(attribution_rows), 4)

        answer_key = json.loads(MOCK_ANSWER_KEY_PATH.read_text(encoding="utf-8"))
        comparison = compare_attribution_to_answer_key(
            attribution_rows,
            answer_key,
            tolerance_points=ATTRIBUTION_TOLERANCE_POINTS,
        )
        self.assertTrue(
            comparison["passed"],
            f"Attribution table did not match Answer Key within tolerance: {json.dumps(comparison, indent=2)}",
        )
        for cause_name, cause_detail in comparison["causes"].items():
            self.assertTrue(
                cause_detail["passed"],
                f"Cause {cause_name} failed comparison: {cause_detail}",
            )
            self.assertLessEqual(
                cause_detail["point_error"], ATTRIBUTION_TOLERANCE_POINTS
            )

    def test_ws1_checkpoints_and_sql_files_exist_and_are_swappable(self) -> None:
        """Checkpoints for ws1_eda_heatmap and ws1_attribution must exist in checkpoints/manifest.d/ with valid SQL files."""
        manifests = load_ws1_checkpoint_manifests(WORKTREE_ROOT)
        self.assertIn("ws1_eda_heatmap", manifests)
        self.assertIn("ws1_attribution", manifests)

        expected_specs: dict[str, dict[str, str]] = {
            "ws1_eda_heatmap": {
                "workstream": "ws1",
                "source_table": "checkpoint.ws1_eda_heatmap",
                "target_table": "staging.ws1_eda_heatmap",
                "sql_file": "sql/ws1_eda_heatmap.sql",
            },
            "ws1_attribution": {
                "workstream": "ws1",
                "source_table": "checkpoint.ws1_attribution",
                "target_table": "staging.ws1_attribution",
                "sql_file": "sql/ws1_attribution.sql",
            },
        }

        for cid, exp in expected_specs.items():
            desc: dict[str, Any] = manifests[cid]
            self.assertEqual(desc.get("id"), cid)
            self.assertEqual(desc.get("workstream"), exp["workstream"])
            self.assertEqual(desc.get("source_table"), exp["source_table"])
            self.assertEqual(desc.get("target_table"), exp["target_table"])
            self.assertEqual(desc.get("sql_file"), exp["sql_file"])
            self.assertTrue(desc.get("description"))

            sql_path = WORKTREE_ROOT / str(desc["sql_file"])
            self.assertTrue(sql_path.is_file(), f"Missing SQL file {sql_path}")
            sql_text = sql_path.read_text(encoding="utf-8")
            self.assertIn("staging.hospital_flu", sql_text)
            self.assertIn("SAFE_DIVIDE", sql_text)

    def test_glossary_compliance_and_verify_start_point_ws1_passes(self) -> None:
        """All new Issue #12 files must pass check-glossary.js, no reference answers leak, and verify-start-point ws1 must pass."""
        new_files = [
            ".agents/plugins/ds-command-center/agents/distribution-triage.md",
            ".agents/plugins/ds-command-center/agents/sampling-triage.md",
            ".agents/plugins/ds-command-center/agents/pipeline-triage.md",
            ".agents/plugins/ds-command-center/agents/stats-reviewer.md",
            ".agents/plugins/ds-command-center/plugin.json",
            ".agents/plugins/ds-command-center/rules/AGENTS.md",
            "lib/ws1_triage.py",
            "sql/ws1_eda_heatmap.sql",
            "sql/ws1_attribution.sql",
            "checkpoints/manifest.d/ws1_eda_heatmap.json",
            "checkpoints/manifest.d/ws1_attribution.json",
            "tests/test_ws1_triage_and_subagents.py",
        ]
        glossary_proc = subprocess.run(
            ["node", "bin/check-glossary.js", *new_files],
            cwd=WORKTREE_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            glossary_proc.returncode,
            0,
            f"check-glossary.js failed:\n{glossary_proc.stdout}\n{glossary_proc.stderr}",
        )

        # Ensure no answer_key.json exists outside fixtures/mock_withheld/
        answer_keys = list(WORKTREE_ROOT.rglob("answer_key.json"))
        self.assertEqual(answer_keys, [MOCK_ANSWER_KEY_PATH])

        # Verify verify-start-point ws1 passes cleanly
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, _ = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
            )
            proc = subprocess.run(
                [str(VERIFY_START_POINT_BIN), "ws1", "--env", str(env_file)],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                proc.returncode,
                0,
                f"verify-start-point ws1 failed:\n{proc.stdout}\n{proc.stderr}",
            )
            self.assertIn("[PASS]", proc.stdout)


if __name__ == "__main__":
    unittest.main()
