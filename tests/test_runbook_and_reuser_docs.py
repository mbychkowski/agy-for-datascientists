from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNBOOK_PATH = REPO_ROOT / "docs" / "presenter-runbook.md"
REUSER_GUIDE_PATH = REPO_ROOT / "docs" / "reuser-guide.md"
RECORDED_RUNTIMES_PATH = REPO_ROOT / "docs" / "recorded_runtimes.json"
README_PATH = REPO_ROOT / "README.md"
STAGE_CLEAN_BIN = REPO_ROOT / "bin" / "stage-clean-env"
STAGE_CLEAN_SYMLINK = REPO_ROOT / "stage-clean-env"

AVOID_TERMS = [  # glossary-ignore
    (r"copilot", "Command Center"),  # glossary-ignore
    (r"chatbot", "Command Center"),  # glossary-ignore
    (r"\bIDE\b", "Command Center"),  # glossary-ignore
    (r"hit[- ]rate", "Positivity"),  # glossary-ignore
    (r"positive[- ]rate", "Positivity"),  # glossary-ignore
    (r"feed[- ]file", "Hospital Feed"),  # glossary-ignore
    (r"hospital data", "Hospital Feed"),  # glossary-ignore
    (r"as-of date", "Cutoff"),  # glossary-ignore
    (r"\btoday\b", "Cutoff"),  # glossary-ignore
    (r"\bnow\b", "Cutoff"),  # glossary-ignore
    (r"data[- ]bug", "Pipeline Defect"),  # glossary-ignore
    (r"etl[- ]issue", "Pipeline Defect"),  # glossary-ignore
    (r"testing[- ]bias", "Sampling Artifact"),  # glossary-ignore
    (r"volume[- ]effect", "Sampling Artifact"),  # glossary-ignore
    (r"root[- ]cause", "Attribution"),  # glossary-ignore
    (r"decomposition", "Attribution"),  # glossary-ignore
    (r"ground[- ]truth", "Answer Key"),  # glossary-ignore
    (r"validation set", "Reveal"),  # glossary-ignore
    (r"\bholdout\b", "Reveal"),  # glossary-ignore
    (r"\bactuals\b", "Reveal"),  # glossary-ignore
    (r"\bsnapshot\b", "Start Point"),  # glossary-ignore
    (r"\bbackup\b", "Checkpoint"),  # glossary-ignore
    (r"\bcache\b", "Checkpoint"),  # glossary-ignore
]

FORBIDDEN_COMPANY_PATTERNS = [
    r"\bproject-[a-z0-9]{5,}\b",
    r"\b[a-z0-9-]+@[a-z0-9-]+\.iam\.gserviceaccount\.com\b",
    r"\baltostrat\.com\b",
    r"\bgoogle\.com\b",
    r"\bargolis\b",
]


class TestPresenterRunbookAndReuserDocs(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runbook = RUNBOOK_PATH.read_text(encoding="utf-8")
        cls.reuser_guide = REUSER_GUIDE_PATH.read_text(encoding="utf-8")
        cls.readme = README_PATH.read_text(encoding="utf-8")
        cls.recorded_runtimes = json.loads(
            RECORDED_RUNTIMES_PATH.read_text(encoding="utf-8")
        )

    def test_files_exist_and_readme_links_them(self) -> None:
        self.assertTrue(RUNBOOK_PATH.is_file(), f"Missing {RUNBOOK_PATH}")
        self.assertTrue(REUSER_GUIDE_PATH.is_file(), f"Missing {REUSER_GUIDE_PATH}")
        self.assertIn("docs/presenter-runbook.md", self.readme)
        self.assertIn("docs/reuser-guide.md", self.readme)
        self.assertIn("docs/data-science-primer.md", self.readme)
        self.assertIn("docs/demo-outline.md", self.readme)

    def test_runbook_covers_per_segment_timings_prompts_and_narration(self) -> None:
        content = self.runbook

        # 90-minute master timings (12 + 35 + 28 + 15 = 90)
        self.assertRegex(content, re.compile(r"Opening.*12\s*min", re.IGNORECASE))
        self.assertRegex(content, re.compile(r"Workstream 1.*35\s*min", re.IGNORECASE))
        self.assertRegex(content, re.compile(r"Workstream 2.*28\s*min", re.IGNORECASE))
        self.assertRegex(content, re.compile(r"Q&A.*15\s*min", re.IGNORECASE))
        self.assertRegex(content, re.compile(r"90\s*min", re.IGNORECASE))

        # Sub-segment breakdown in Workstream 1 (10 + 12 + 13 = 35) and Workstream 2 (8 + 10 + 6 + 4 = 28)
        for seg_header in (
            "Segment 1A",
            "Segment 1B",
            "Segment 1C",
            "Segment 2A",
            "Segment 2B",
            "Segment 2C",
            "Segment 2D",
        ):
            self.assertIn(seg_header, content)

        # Prompts to type and narration cues across segments
        prompt_headers = re.findall(r"Prompt(?:\s+\d+)?\s+to\s+Type", content)
        narration_headers = re.findall(r"What\s+to\s+Narrate", content)
        self.assertGreaterEqual(
            len(prompt_headers),
            7,
            "Runbook must include explicit prompts to type for each interactive step",
        )
        self.assertGreaterEqual(
            len(narration_headers),
            8,
            "Runbook must include speaker narration cues for every segment",
        )

    def test_runbook_covers_early_start_jobs_and_recorded_runtimes(self) -> None:
        content = self.runbook
        clean_entry = self.recorded_runtimes["ws1_pipeline_clean_dataproc_runtime_3_0"]
        v1_entry = self.recorded_runtimes["ws1_pipeline_v1_dataproc_runtime_3_0"]

        self.assertIn("recorded_runtimes.json", content)
        self.assertIn(f"{clean_entry['last_observed_seconds']}s", content)
        self.assertIn(f"{v1_entry['last_observed_seconds']}s", content)
        self.assertIn("./run-pipeline-clean --async", content)
        self.assertIn("./run-pipeline-clean --sql-fallback", content)
        self.assertRegex(
            content,
            re.compile(r"Start.*ARIMA_PLUS.*Training\s+First", re.IGNORECASE),
        )

    def test_runbook_covers_guardrail_moment_and_checkpoint_swaps(self) -> None:
        content = self.runbook

        # Guardrail moment in Antigravity 101
        self.assertIn("The Guardrail Moment in Antigravity 101", content)
        self.assertIn("raw.hospital_flu_feeds", content)
        self.assertIn("ops.pipeline_run_log", content)
        self.assertIn(".agents/plugins/ds-command-center/bin/guardrail-hook", content)
        self.assertRegex(content, re.compile(r"read-only", re.IGNORECASE))
        self.assertRegex(
            content, re.compile(r"stay(?:ing|s) in control", re.IGNORECASE)
        )

        # Pre-stage step moving personal rules and skills aside
        self.assertIn("./stage-clean-env --stash", content)
        self.assertIn("./stage-clean-env --status", content)
        self.assertIn("./stage-clean-env --restore", content)

        # Checkpoint swap commands for Workstream 1 and Workstream 2
        expected_checkpoints = [
            "./checkpoint ws1_eda_heatmap",
            "./checkpoint ws1_attribution",
            "./checkpoint ws1_staging_clean",
            "./checkpoint ws2_seasonal_features",
            "./checkpoint ws2_hospital_cohorts",
            "./checkpoint ws2_experiment_trials",
            "./checkpoint ws2_forecast_leaderboard",
        ]
        for cmd in expected_checkpoints:
            self.assertIn(
                cmd, content, f"Runbook missing Checkpoint swap command: {cmd}"
            )

    def test_reuser_guide_covers_env_terraform_dak_skills_java21_quota_and_iam(
        self,
    ) -> None:
        content = self.reuser_guide

        # 1. Environment file
        for env_token in (
            "cp demo.env.example demo.env",
            "PROJECT_ID",
            "REGION",
            "STAGING_BUCKET",
            "STATE_BUCKET",
            "SUBNET",
            "CLOUDSDK_CORE_PROJECT",
            "GOOGLE_CLOUD_QUOTA_PROJECT",
            "TF_VAR_project_id",
        ):
            self.assertIn(env_token, content)

        # 2. Minimum IAM roles reflecting ADR 0002
        self.assertIn("0002-dataproc-runs-as-presenter.md", content)
        self.assertIn("roles/owner", content)
        for role in (
            "roles/serviceusage.serviceUsageAdmin",
            "roles/compute.networkAdmin",
            "roles/compute.securityAdmin",
            "roles/storage.admin",
            "roles/bigquery.admin",
            "roles/bigquery.dataEditor",
            "roles/bigquery.jobUser",
            "roles/dataproc.editor",
            "roles/iam.serviceAccountUser",
            "roles/dataproc.worker",
        ):
            self.assertIn(role, content, f"Reuser guide missing IAM role: {role}")

        # 3. Terraform bootstrap and apply
        self.assertIn("./bin/bootstrap-tf-state", content)
        self.assertIn("terraform -chdir=infra plan", content)
        self.assertIn("terraform -chdir=infra apply", content)

        # 4. Data Agent Kit workspace skills installation (licensed, not redistributed)
        self.assertIn(".gemini/skills", content)
        self.assertRegex(content, re.compile(r"not redistributed", re.IGNORECASE))
        self.assertRegex(content, re.compile(r"licensed", re.IGNORECASE))
        self.assertIn("mcp_proxy_bundle.cjs", content)

        # 5. Java 21 for local Spark 4 tests
        self.assertIn("openjdk@21", content)
        self.assertIn("JAVA_HOME", content)
        self.assertIn("ensure_java_21_env", content)
        self.assertIn("Java 25", content)

        # 6. Stale ADC quota project pitfall
        self.assertIn("application_default_credentials.json", content)
        self.assertIn("quota_project_id", content)
        self.assertIn("403 Forbidden", content)
        self.assertIn(
            'gcloud auth application-default set-quota-project "${PROJECT_ID}"', content
        )

    def test_stage_clean_env_stash_status_and_restore(self) -> None:
        self.assertTrue(STAGE_CLEAN_BIN.is_file(), f"Missing {STAGE_CLEAN_BIN}")
        self.assertTrue(
            os.access(STAGE_CLEAN_BIN, os.X_OK),
            "bin/stage-clean-env must be executable",
        )
        self.assertTrue(
            STAGE_CLEAN_SYMLINK.is_symlink(), "Root stage-clean-env symlink missing"
        )
        self.assertEqual(STAGE_CLEAN_SYMLINK.resolve(), STAGE_CLEAN_BIN.resolve())

        script_text = STAGE_CLEAN_BIN.read_text(encoding="utf-8")
        self.assertIn("set -uo pipefail", script_text)
        self.assertIn("REPO_ROOT=", script_text)

        with tempfile.TemporaryDirectory() as tmp_home:
            home_path = Path(tmp_home)
            gemini_dir = home_path / ".gemini"

            # Create personal rules and skills + one licensed DAK skill
            personal_rule = gemini_dir / "rules" / "my_rule.md"
            config_rule = gemini_dir / "config" / "rules" / "corp_rule.md"
            agents_md = gemini_dir / "AGENTS.md"
            personal_skill = (
                gemini_dir / "skills" / "custom-personal-skill" / "SKILL.md"
            )
            config_skill = (
                gemini_dir / "config" / "skills" / "extra-personal-skill" / "SKILL.md"
            )
            dak_skill = gemini_dir / "skills" / "bigquery-ai-ml" / "SKILL.md"

            for file_path, body in (
                (personal_rule, "# Personal Rule\n"),
                (config_rule, "# Config Rule\n"),
                (agents_md, "# Personal Agents\n"),
                (personal_skill, "# Custom Personal Skill\n"),
                (config_skill, "# Extra Personal Skill\n"),
                (dak_skill, "# Licensed DAK Skill\n"),
            ):
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(body, encoding="utf-8")

            # 1. Initial status should be active
            status_before = subprocess.run(
                [str(STAGE_CLEAN_SYMLINK), "--status", "--home-dir", str(home_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(status_before.returncode, 0, status_before.stderr)
            self.assertIn("STATUS: active", status_before.stdout)

            # 2. Stash personal rules and non-DAK skills
            stash_res = subprocess.run(
                [str(STAGE_CLEAN_SYMLINK), "--stash", "--home-dir", str(home_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(stash_res.returncode, 0, stash_res.stderr)
            self.assertIn(
                "[PASS] Stashed 5 personal rule/skill item(s)", stash_res.stdout
            )

            self.assertFalse(personal_rule.exists())
            self.assertFalse(config_rule.exists())
            self.assertFalse(agents_md.exists())
            self.assertFalse(personal_skill.exists())
            self.assertFalse(config_skill.exists())
            # DAK skill remains untouched
            self.assertTrue(dak_skill.is_file())

            # 3. Status should report stashed
            status_stashed = subprocess.run(
                [str(STAGE_CLEAN_SYMLINK), "--status", "--home-dir", str(home_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(status_stashed.returncode, 0, status_stashed.stderr)
            self.assertIn("STATUS: stashed", status_stashed.stdout)
            self.assertIn("skills/custom-personal-skill", status_stashed.stdout)

            # 4. Restore should put everything back cleanly
            restore_res = subprocess.run(
                [str(STAGE_CLEAN_SYMLINK), "--restore", "--home-dir", str(home_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(restore_res.returncode, 0, restore_res.stderr)
            self.assertIn(
                "[PASS] Restored 5 personal rule/skill item(s)", restore_res.stdout
            )

            self.assertEqual(
                personal_rule.read_text(encoding="utf-8"), "# Personal Rule\n"
            )
            self.assertEqual(config_rule.read_text(encoding="utf-8"), "# Config Rule\n")
            self.assertEqual(
                agents_md.read_text(encoding="utf-8"), "# Personal Agents\n"
            )
            self.assertEqual(
                personal_skill.read_text(encoding="utf-8"), "# Custom Personal Skill\n"
            )
            self.assertEqual(
                config_skill.read_text(encoding="utf-8"), "# Extra Personal Skill\n"
            )
            self.assertTrue(dak_skill.is_file())
            self.assertFalse((gemini_dir / ".demo-stage-stash").exists())

    def test_company_neutrality_and_glossary_compliance(self) -> None:
        for path in (RUNBOOK_PATH, REUSER_GUIDE_PATH, README_PATH):
            content = path.read_text(encoding="utf-8")
            for pat in FORBIDDEN_COMPANY_PATTERNS:
                self.assertIsNone(
                    re.search(pat, content, re.IGNORECASE),
                    f"Found non-neutral identifier matching '{pat}' in {path}",
                )
            for pattern, preferred in AVOID_TERMS:
                matches = re.findall(pattern, content, re.IGNORECASE)
                self.assertEqual(
                    len(matches),
                    0,
                    f"Found forbidden term '{pattern}' in {path}; use '{preferred}' instead.",
                )

        proc = subprocess.run(
            [
                "node",
                str(REPO_ROOT / "bin" / "check-glossary.js"),
                str(RUNBOOK_PATH),
                str(REUSER_GUIDE_PATH),
                str(README_PATH),
                str(STAGE_CLEAN_BIN),
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            proc.returncode, 0, f"check-glossary.js failed:\n{proc.stderr}"
        )


if __name__ == "__main__":
    unittest.main()
