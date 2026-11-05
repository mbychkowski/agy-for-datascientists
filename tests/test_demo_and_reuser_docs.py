from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RETIRED_RUNBOOK_PATH = REPO_ROOT / "docs" / "presenter-runbook.md"
REUSER_GUIDE_PATH = REPO_ROOT / "docs" / "reuser-guide.md"
RECORDED_RUNTIMES_PATH = REPO_ROOT / "docs" / "recorded_runtimes.json"
EQUIVALENCE_SQL = (REPO_ROOT / "sql" / "verify_clean_equivalence.sql").read_text(
    encoding="utf-8"
)
README_PATH = REPO_ROOT / "README.md"
DEMO_PATH = REPO_ROOT / "DEMO.md"
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


# Presenter tooling that exists only on `main`, or that is stale on the stage
# branches, so Window 2 (the `main` repo) must run it, never the stage clone.
MAIN_ONLY_SCRIPTS = (
    "stage-clean-env",
    "preflight",
    "reset",
    "verify-start-point",
    "checkpoint",
    "run-pipeline-clean",
    "run-ws2-cohorts",
    "run-ws2-forecasts",
    "run-cohort-forecast-refresh",
    "load-reveal",
)


def _pre_stage_checklist(doc: str) -> str:
    """Return the T-15 Pre-Stage Checklist section of DEMO.md."""
    match = re.search(
        r"^## \d+\. Pre-Stage Checklist.*?(?=^## )", doc, re.MULTILINE | re.DOTALL
    )
    if match is None:
        raise AssertionError("Pre-Stage Checklist section not found")
    return match.group(0)


def _bash_blocks(doc: str) -> list[str]:
    """Return the bodies of every fenced bash block (blockquoted ones included)."""
    unquoted = re.sub(r"^\s*> ?", "", doc, flags=re.MULTILINE)
    return re.findall(r"```bash\n(.*?)```", unquoted, re.DOTALL)


def _stage_clone_dir(doc: str) -> str:
    """Return the target directory of the documented stage-clone command."""
    match = re.search(
        r"git clone\b[^\n]*--branch workstream-1-start[^\n]*?(\S+)\s*$",
        doc,
        re.MULTILINE,
    )
    if match is None:
        raise AssertionError("No `git clone ... --branch workstream-1-start` command")
    return match.group(1)


def _segment(doc: str, title: str) -> str:
    """Return the `##`/`###`/`####` section whose heading contains `title`.

    The section runs until the next heading at the same or a higher level.
    """
    match = re.search(
        rf"^(#{{2,4}}) [^\n]*{re.escape(title)}[^\n]*\n", doc, re.MULTILINE
    )
    if match is None:
        raise AssertionError(f"No section heading containing {title!r}")
    level = len(match.group(1))
    rest = doc[match.end() :]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.MULTILINE)
    return match.group(0) + (rest[: end.start()] if end else rest)


def _labelled_blocks(section: str, lang: str) -> list[tuple[str, str]]:
    """Return (label, body) for each fenced `lang` block in `section`.

    The label is the nearest preceding bold bullet (`* **...**`), which names
    the window and role of the block on stage.
    """
    blocks = []
    for fence in re.finditer(rf"```{lang}\n(.*?)```", section, re.DOTALL):
        labels = re.findall(
            r"^\s*[*-] \*\*[^\n]*", section[: fence.start()], re.MULTILINE
        )
        blocks.append((labels[-1] if labels else "", fence.group(1)))
    return blocks


def _table_rows(section: str, first_cell: str) -> list[str]:
    """Return the Markdown table rows whose first cell contains `first_cell`."""
    return [
        row
        for row in section.splitlines()
        if row.startswith("|") and first_cell in row.split("|")[1]
    ]


# Opening guardrail and Workstream 1 segment titles in DEMO.md.
GUARDRAIL_MOMENT = "Live Guardrail Moment"
WS1_SEGMENTS = ("Segment 1A", "Segment 1B", "Segment 1C")

# Top-level DEMO.md sections for each Workstream and the handoff between them.
WS1_SECTION = 'Workstream 1: "Is the Data Good to Use?"'
WS2_SECTION = 'Workstream 2: "Forecast at Scale"'
HANDOFF_SECTION = "Intermission: Handoff Between Workstreams"
WS2_SEGMENTS = ("Segment 2A", "Segment 2B", "Segment 2C", "Segment 2D")

# Per Workstream 2 segment: the Window 2 fallback script for the agent's own
# run, the Checkpoints that back it, and the recorded-runtime keys that time
# its 60-second-rule trigger.
WS2_FALLBACKS = {
    "Segment 2A": (
        "./run-ws2-cohorts",
        ("./checkpoint ws2_seasonal_features", "./checkpoint ws2_hospital_cohorts"),
        ("ws2_seasonal_features_and_kmeans",),
    ),
    "Segment 2B": (
        "./run-ws2-forecasts",
        ("./checkpoint ws2_experiment_trials", "./checkpoint ws2_forecast_leaderboard"),
        ("ws2_arima_plus_cohort_training", "ws2_timesfm_ai_forecast"),
    ),
    "Segment 2D": ("./run-cohort-forecast-refresh --period 2026-W44", (), ()),
}

# Rule 2: live-captured skills belong in the Command Center plugin.
SKILL_PATH = ".agents/plugins/ds-command-center/skills/cohort-forecast-refresh/SKILL.md"
EARLY_START = r"(?i)early[- ]start|start(?:ed)? early|trigger(?:ed)? early"


class TestDemoAndReuserDocs(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reuser_guide = REUSER_GUIDE_PATH.read_text(encoding="utf-8")
        cls.readme = README_PATH.read_text(encoding="utf-8")
        cls.demo = DEMO_PATH.read_text(encoding="utf-8")
        cls.recorded_runtimes = json.loads(
            RECORDED_RUNTIMES_PATH.read_text(encoding="utf-8")
        )

    def _docs(self) -> tuple[tuple[str, str], ...]:
        """The presenter docs every run-through assertion covers: DEMO.md only."""
        return (("DEMO.md", self.demo),)

    def test_files_exist_and_readme_links_them(self) -> None:
        self.assertTrue(REUSER_GUIDE_PATH.is_file(), f"Missing {REUSER_GUIDE_PATH}")
        self.assertTrue(DEMO_PATH.is_file(), f"Missing {DEMO_PATH}")
        self.assertIn("DEMO.md", self.readme)
        self.assertIn("docs/reuser-guide.md", self.readme)
        self.assertIn("docs/data-science-primer.md", self.readme)
        self.assertIn("docs/demo-outline.md", self.readme)
        self.assertIn("```mermaid", self.readme)
        self.assertIn("flowchart TB", self.readme)
        self.assertIn("Workstream 1", self.demo)
        self.assertIn("Workstream 2", self.demo)
        self.assertIn("./stage-clean-env --stash", self.demo)
        self.assertIn("./checkpoint", self.demo)

    def test_t15_checklist_builds_isolated_single_branch_stage_clone(self) -> None:
        for name, doc in self._docs():
            with self.subTest(doc=name):
                checklist = _pre_stage_checklist(doc)
                self.assertRegex(
                    checklist,
                    r"git clone --single-branch --branch workstream-1-start ",
                )
                clone_dir = _stage_clone_dir(checklist)
                self.assertRegex(
                    clone_dir,
                    r"^(~/|\$HOME/|\.\./)",
                    f"{name}: stage clone must live outside the presenter repo",
                )
                self.assertIn(f"git -C {clone_dir} remote remove origin", checklist)
                self.assertIn(f"cp demo.env {clone_dir}/", checklist)
                # .gemini/skills/ is git-ignored, so the clone starts without
                # the licensed DAK skills the agent and subagents need.
                self.assertIn(f"cp -R .gemini/skills {clone_dir}/.gemini/", checklist)

    def test_docs_explain_why_worktree_or_in_repo_folder_breaks_guarantee(
        self,
    ) -> None:
        for name, doc in self._docs():
            with self.subTest(doc=name):
                checklist = _pre_stage_checklist(doc)
                self.assertRegex(checklist, r"(?i)worktree")
                self.assertRegex(checklist, r"(?i)share[sd]? `?\.git`?")
                self.assertIn("git show main:", checklist)
                self.assertRegex(checklist, r"(?i)in-repo folder")
                self.assertIn("0001-answer-key-outside-agent-reach.md", checklist)

    def test_t15_resets_clone_code_then_ws1_data_from_main_repo(self) -> None:
        for name, doc in self._docs():
            with self.subTest(doc=name):
                checklist = _pre_stage_checklist(doc)
                clone_dir = _stage_clone_dir(checklist)
                ordered_steps = (
                    f"git -C {clone_dir} reset --hard",
                    f"git -C {clone_dir} clean -fd",
                    "./reset ws1 --yes",
                    "./verify-start-point ws1",
                )
                positions = []
                for step in ordered_steps:
                    self.assertIn(step, checklist, f"{name} T-15 missing: {step}")
                    positions.append(checklist.index(step))
                self.assertEqual(
                    positions,
                    sorted(positions),
                    f"{name}: reset the clone's code before resetting ws1 data",
                )
                self.assertRegex(checklist, r"(?i)every rehearsal")

    def test_stage_clean_env_and_preflight_are_window_2_commands(self) -> None:
        for name, doc in self._docs():
            sections = re.split(r"^(?=#{2,4} )", doc, flags=re.MULTILINE)
            labelled = 0
            for section in sections:
                commands = "\n".join(_bash_blocks(section))
                if not re.search(r"\./(stage-clean-env|preflight)\b", commands):
                    continue
                labelled += 1
                heading = section.splitlines()[0]
                with self.subTest(doc=name, section=heading):
                    self.assertIn("Window 2", section)
            self.assertGreaterEqual(labelled, 3, f"{name}: stash, preflight, restore")

    def test_no_main_only_script_runs_from_the_stage_clone(self) -> None:
        main_only = re.compile(r"\./(" + "|".join(MAIN_ONLY_SCRIPTS) + r")\b")
        for name, doc in self._docs():
            with self.subTest(doc=name):
                # Checking out the stage branch in the presenter repo is the
                # one-checkout model this setup replaces.
                self.assertNotIn("git checkout workstream-1-start", doc)
                clone_dir = _stage_clone_dir(doc)

                # A shell step that changes into the stage clone, in any form
                # (`cd`, `(cd ... && ...)`, `pushd`), must not run a script
                # that only Window 2 owns.
                for block in _bash_blocks(doc):
                    in_clone = False
                    for line in block.splitlines():
                        cd = re.search(
                            r"\b(?:cd|pushd)\s+[\"']?(\S+?)[\"']?(?:\s|$)", line
                        )
                        if cd:
                            in_clone = cd.group(1).startswith(clone_dir)
                        if in_clone:
                            self.assertIsNone(
                                main_only.search(line),
                                f"{name} runs a main-only script from the "
                                f"stage clone: {line.strip()}",
                            )

                # Text labelled Window 1 must not tell the presenter to run a
                # script that only Window 2 owns. A label covers the text after
                # it up to the next Window 2 label, table cell, or line break
                # in a cell, so a table row may name both windows.
                for section in re.split(r"^(?=#{2,4} )", doc, flags=re.MULTILINE):
                    heading = section.splitlines()[0] if section else ""
                    chunks = (
                        [section]
                        if "Window 1" in heading
                        else re.split(r"\n\s*\n|\n(?=\s*(?:[*-]|\d+\.) )", section)
                    )
                    for chunk in chunks:
                        for label in re.finditer(r"Window 1", chunk):
                            scope = re.split(
                                r"Window 2|\||<br>", chunk[label.end() :], maxsplit=1
                            )[0]
                            self.assertIsNone(
                                main_only.search(scope),
                                f"{name}: Window 1 text names a main-only "
                                f"script: {scope.strip()[:120]}",
                            )

    def test_window_1_opens_on_the_stage_clone(self) -> None:
        for name, doc in self._docs():
            with self.subTest(doc=name):
                checklist = _pre_stage_checklist(doc)
                clone_dir = _stage_clone_dir(checklist)
                layout = next(
                    section
                    for section in re.split(r"^(?=### )", checklist, flags=re.MULTILINE)
                    if section.startswith("### ") and "**Window 1" in section
                )
                self.assertIn(clone_dir, layout)
                self.assertRegex(layout, r"\*\*Window 2[^\n]*`main`")

    def test_readme_notes_the_two_stage_windows(self) -> None:
        self.assertRegex(self.readme, r"Window 1[^\n]*workstream-1-start")
        self.assertRegex(self.readme, r"Window 2[^\n]*`main`")
        self.assertIn("DEMO.md#2-pre-stage-checklist-t-15-minutes", self.readme)

    def test_reuser_guide_explains_the_two_repository_setup(self) -> None:
        guide = self.reuser_guide
        self.assertIn("git clone --single-branch --branch workstream-1-start ", guide)
        clone_dir = _stage_clone_dir(guide)
        self.assertIn(f"git -C {clone_dir} remote remove origin", guide)
        self.assertIn(f"cp demo.env {clone_dir}/", guide)
        self.assertIn("Window 1", guide)
        self.assertIn("Window 2", guide)
        self.assertRegex(guide, r"(?i)worktree")
        self.assertIn("git show main:", guide)

    def test_stage_prompts_are_typed_into_window_1(self) -> None:
        for name, doc in self._docs():
            for title in (GUARDRAIL_MOMENT, *WS1_SEGMENTS, *WS2_SEGMENTS):
                prompts = _labelled_blocks(_segment(doc, title), "text")
                with self.subTest(doc=name, segment=title):
                    self.assertTrue(prompts, "segment has no prompt to type")
                    for label, _ in prompts:
                        self.assertIn("Window 1", label)

    def test_stage_presenter_commands_run_from_window_2(self) -> None:
        for name, doc in self._docs():
            for title in (*WS1_SEGMENTS, *WS2_SEGMENTS):
                for label, body in _labelled_blocks(_segment(doc, title), "bash"):
                    if "./" not in body:
                        continue
                    with self.subTest(doc=name, segment=title, block=body.strip()):
                        self.assertIn("Window 2", label)

    def test_1c_prompt_has_agent_write_pipeline_clean_and_wait(self) -> None:
        for name, doc in self._docs():
            with self.subTest(doc=name):
                prompt = "\n".join(
                    body
                    for _, body in _labelled_blocks(_segment(doc, "Segment 1C"), "text")
                )
                self.assertRegex(
                    prompt, r"(?i)\bwrite\b[^.]*pipelines/pipeline_clean\.py"
                )
                self.assertIn("(hospital_id, feed_date)", prompt)
                self.assertRegex(prompt, r"(?i)null-safe Positivity")
                self.assertRegex(prompt, r"(?i)\bdiff\b")
                self.assertRegex(prompt, r"(?i)wait for my approval")
                # pipeline_clean.py doesn't exist on workstream-1-start, so the
                # agent cannot diff against it; it has to write it.
                self.assertNotRegex(
                    prompt, r"diff between \S*pipeline_v1\.py and \S*pipeline_clean\.py"
                )

    def test_1c_agent_submits_its_own_pinned_batch_as_presenter(self) -> None:
        for name, doc in self._docs():
            with self.subTest(doc=name):
                section = _segment(doc, "Segment 1C")
                prompt = "\n".join(
                    body for _, body in _labelled_blocks(section, "text")
                )
                self.assertRegex(prompt, r"(?i)submit[^.]*Dataproc Serverless")
                for pin in ("PROJECT_ID", "REGION", "demo.env"):
                    self.assertIn(pin, prompt)
                self.assertIn("staging.hospital_flu_clean", prompt)
                # ADR 0002: the batch runs as the presenter identity.
                # The equivalence SQL compares these columns by name, so the
                # agent has to write exactly the reference schema.
                select = re.search(
                    r"pyspark_clean AS \(\s*SELECT(.*?)FROM", EQUIVALENCE_SQL, re.DOTALL
                )
                for column in re.findall(r"(\w+),?\n", select.group(1)):
                    self.assertRegex(prompt, rf"\b{column}\b")
                self.assertNotIn("--service-account", section)
                # The agent's batch replaces the presenter's early-start job.
                self.assertNotIn("--async", section)
                self.assertNotRegex(section, r"(?i)early-start")

    def test_1c_verifies_agent_output_equivalence_from_window_2(self) -> None:
        for name, doc in self._docs():
            with self.subTest(doc=name):
                section = _segment(doc, "Segment 1C")
                verify = [
                    label
                    for label, body in _labelled_blocks(section, "bash")
                    if "./run-pipeline-clean --verify-equivalence" in body
                ]
                self.assertEqual(len(verify), 1, "one Window 2 equivalence step")
                self.assertIn("Window 2", verify[0])
                self.assertNotRegex(verify[0], r"(?i)fallback")
                self.assertIn("sql/verify_clean_equivalence.sql", section)

    def test_1c_fallbacks_are_window_2_with_trigger_times(self) -> None:
        clean_runtime = self.recorded_runtimes[
            "ws1_pipeline_clean_dataproc_runtime_3_0"
        ]["last_observed_seconds"]
        for name, doc in self._docs():
            section = _segment(doc, "Segment 1C")
            blocks = _labelled_blocks(section, "bash")
            for command in (
                "./run-pipeline-clean --sql-fallback",
                "./checkpoint ws1_staging_clean",
            ):
                with self.subTest(doc=name, command=command):
                    labels = [label for label, body in blocks if command in body]
                    self.assertEqual(len(labels), 1)
                    self.assertIn("Window 2", labels[0])
                    self.assertRegex(labels[0], r"(?i)fallback")
                    self.assertRegex(labels[0], r"`\d{2}:\d{2}`", "trigger time")
            with self.subTest(doc=name, rule="60-second rule"):
                self.assertRegex(section, r"(?i)60 seconds")
                self.assertIn(f"{clean_runtime}s", section)
                self.assertRegex(section, r"(?i)--sql-fallback[^\n]*reference pipeline")
            with self.subTest(doc=name, rule="trigger order"):
                # Fallback A fires once the batch is 60s past its runtime,
                # Fallback B after A, and both before the Window 2 check.
                trigger = {
                    command: re.search(r"`(\d{2}:\d{2})`", label).group(1)
                    for label, body in blocks
                    for command in ("--sql-fallback", "ws1_staging_clean", "--verify")
                    if command in body
                }
                self.assertLess(trigger["--sql-fallback"], trigger["ws1_staging_clean"])
                self.assertLess(trigger["ws1_staging_clean"], trigger["--verify"])

    def test_docs_cite_the_real_equivalence_sql_file(self) -> None:
        self.assertTrue((REPO_ROOT / "sql" / "verify_clean_equivalence.sql").is_file())
        for name, doc in (*self._docs(), ("README.md", self.readme)):
            with self.subTest(doc=name):
                self.assertNotIn("ws1_pipeline_clean_equiv", doc)
        for name, doc in (("DEMO.md", self.demo), ("README.md", self.readme)):
            with self.subTest(doc=name):
                self.assertIn("verify_clean_equivalence.sql", doc)

    def test_schedule_and_fallback_matrix_show_a_window_per_action(self) -> None:
        schedule = _segment(self.demo, "3.1 Segment Schedule")
        for first_cell in (
            "Opening",
            "Segment 1A",
            "Segment 1B",
            "Segment 1C",
            *WS2_SEGMENTS,
        ):
            with self.subTest(doc="DEMO.md 3.1", row=first_cell):
                (row,) = _table_rows(schedule, first_cell)
                self.assertIn("Window 1", row)
                if first_cell != "Opening":
                    self.assertIn("Window 2", row)

        demo_matrix = _segment(self.demo, "3.2 ")
        for name, matrix, first_cell in (
            ("DEMO.md 3.2", demo_matrix, "Workstream 1C"),
            ("DEMO.md 3.2", demo_matrix, "Workstream 2A"),
            ("DEMO.md 3.2", demo_matrix, "Workstream 2B"),
            ("DEMO.md 3.2", demo_matrix, "Workstream 2D"),
        ):
            with self.subTest(doc=name, row=first_cell):
                (row,) = _table_rows(matrix, first_cell)
                self.assertIn("Window 1", row)
                self.assertIn("Window 2", row)
                self.assertRegex(row, r"(?i)fallback")
                self.assertNotIn("--async", row)
                self.assertRegex(row, r"(?i)60 seconds")

    def test_ws2_stays_in_the_ws1_clone(self) -> None:
        for name, doc in self._docs():
            with self.subTest(doc=name):
                ws2 = _segment(doc, HANDOFF_SECTION)
                self.assertNotIn("git checkout workstream-2-start", doc)
                # The agent carries its own Workstream 1 outputs forward.
                self.assertRegex(ws2, r"(?i)\bstay\b[^.]*clone")
                self.assertIn(_stage_clone_dir(doc), ws2)

    def test_ws2_start_is_recovery_only_and_cloned_in_isolation(self) -> None:
        for name, doc in self._docs():
            with self.subTest(doc=name):
                ws2 = _segment(doc, HANDOFF_SECTION)
                self.assertRegex(ws2, r"(?i)recovery")
                match = re.search(
                    r"git clone --single-branch --branch workstream-2-start "
                    r'"\$\(git remote get-url origin\)" (\S+)',
                    ws2,
                )
                self.assertIsNotNone(match, "isolated workstream-2-start clone")
                clone_dir = match.group(1)
                self.assertRegex(clone_dir, r"^(~/|\$HOME/|\.\./)")
                self.assertNotEqual(clone_dir, _stage_clone_dir(doc))
                for step in (
                    f"git -C {clone_dir} remote remove origin",
                    f"cp demo.env {clone_dir}/",
                    f"cp -R .gemini/skills {clone_dir}/.gemini/",
                    "./reset ws2 --yes",
                    "./verify-start-point ws2",
                ):
                    self.assertIn(step, ws2)

    def test_ws2_prompts_have_the_agent_write_the_sql_and_the_skill(self) -> None:
        for name, doc in self._docs():
            prompts = {
                title: "\n".join(
                    body for _, body in _labelled_blocks(_segment(doc, title), "text")
                )
                for title in WS2_SEGMENTS
            }
            with self.subTest(doc=name, segment="2A"):
                prompt = prompts["Segment 2A"]
                self.assertRegex(prompt, r"(?i)\bwrite\b[^.]*\bSQL\b")
                self.assertRegex(prompt, r"(?i)K-means")
                self.assertIn("features.hospital_seasonal_features", prompt)
                self.assertIn("features.hospital_cohorts", prompt)
            with self.subTest(doc=name, segment="2B"):
                prompt = prompts["Segment 2B"]
                self.assertRegex(prompt, r"(?i)\bwrite\b[^.]*\bSQL\b")
                self.assertLess(prompt.index("ARIMA_PLUS"), prompt.index("TimesFM"))
                self.assertRegex(prompt, r"(?i)ARIMA_PLUS[^.]*\bfirst\b")
            with self.subTest(doc=name, segment="2D"):
                self.assertRegex(
                    prompts["Segment 2D"],
                    rf"(?i)\b(?:create|write)\b[^\n]*{re.escape(SKILL_PATH)}",
                )
                self.assertNotIn(".gemini/skills/cohort-forecast-refresh", doc)

    def test_reveal_loads_from_window_2(self) -> None:
        for name, doc in self._docs():
            with self.subTest(doc=name):
                blocks = _labelled_blocks(_segment(doc, "Segment 2C"), "bash")
                labels = [label for label, body in blocks if "./load-reveal" in body]
                self.assertEqual(len(labels), 1)
                self.assertIn("Window 2", labels[0])

    def test_ws2_fallbacks_are_window_2_with_trigger_times(self) -> None:
        for name, doc in self._docs():
            for title, (script, checkpoints, runtimes) in WS2_FALLBACKS.items():
                section = _segment(doc, title)
                clock = re.search(
                    r"`(\d{2}:\d{2})–(\d{2}:\d{2})`", section.splitlines()[0]
                )
                self.assertIsNotNone(clock, f"{name} {title} heading has no clock")
                start, end = clock.groups()
                blocks = _labelled_blocks(section, "bash")
                triggers = []
                for command in (script, *checkpoints):
                    with self.subTest(doc=name, command=command):
                        labels = [label for label, body in blocks if command in body]
                        self.assertEqual(len(labels), 1)
                        self.assertIn("Window 2", labels[0])
                        self.assertRegex(labels[0], r"(?i)fallback")
                        trigger = re.search(r"`(\d{2}:\d{2})`", labels[0])
                        self.assertIsNotNone(trigger, "trigger time")
                        self.assertTrue(
                            start < trigger.group(1) < end,
                            f"trigger {trigger.group(1)} outside {start}–{end}",
                        )
                        triggers.append(trigger.group(1))
                with self.subTest(doc=name, segment=title, rule="60-second rule"):
                    self.assertRegex(section, r"(?i)60 seconds")
                    for key in runtimes:
                        seconds = self.recorded_runtimes[key]["last_observed_seconds"]
                        self.assertIn(f"{seconds}s", section)
                    # The script swaps in before its Checkpoints do.
                    self.assertEqual(triggers, sorted(triggers))

    def test_no_early_start_wording_remains(self) -> None:
        for name, doc in (*self._docs(), ("README.md", self.readme)):
            with self.subTest(doc=name):
                self.assertNotRegex(doc, EARLY_START)

    def test_rehearsal_repeats_the_live_written_prompts(self) -> None:
        for name, doc in self._docs():
            with self.subTest(doc=name):
                section = _segment(doc, "Rehears")
                for segment in ("1C", "2A", "2B", "2D"):
                    self.assertRegex(section, rf"\b{segment}\b")
                self.assertRegex(section, r"(?i)several times")
                self.assertRegex(section, r"(?i)consistent")

    def test_shortened_cuts_use_the_two_window_model(self) -> None:
        cuts = _segment(self.demo, "Shortened Demo Cuts")
        for first_cell in ("45-Minute", "60-Minute"):
            with self.subTest(row=first_cell):
                (row,) = _table_rows(cuts, first_cell)
                self.assertIn("Window 1", row)
                self.assertIn("Window 2", row)
                self.assertRegex(row, r"(?i)fallback")
                self.assertIn("T-15", row)

    def test_team_of_specialized_agents_is_used_consistently(self) -> None:
        for name, doc in (
            *self._docs(),
            ("README.md", self.readme),
            ("reuser guide", self.reuser_guide),
        ):
            with self.subTest(doc=name):
                self.assertNotRegex(doc, r"(?i)\barmy\b")
        for name, doc in (*self._docs(), ("README.md", self.readme)):
            with self.subTest(doc=name):
                self.assertIn("team of specialized agents", doc)

    def test_demo_covers_per_segment_timings_prompts_and_narration(self) -> None:
        content = self.demo

        # 90-minute master timings (12 + 35 + 28 + 15 = 90)
        self.assertRegex(content, re.compile(r"Opening.*12\s*min", re.IGNORECASE))
        self.assertRegex(content, re.compile(r"Workstream 1.*35\s*min", re.IGNORECASE))
        self.assertRegex(content, re.compile(r"Workstream 2.*28\s*min", re.IGNORECASE))
        self.assertRegex(content, re.compile(r"Q&A.*15\s*min", re.IGNORECASE))
        self.assertRegex(content, re.compile(r"90\s*min", re.IGNORECASE))

        # Every Opening part and Workstream segment has a prompt to type into
        # Window 1 and a narration cue for the audience.
        for title in (
            "Part A",
            "Part B",
            "Part C",
            *WS1_SEGMENTS,
            *WS2_SEGMENTS,
        ):
            with self.subTest(segment=title):
                section = _segment(content, title)
                self.assertRegex(section, r"(?i)say to the audience")
                if title in ("Part A", "Part B"):
                    continue
                prompts = [
                    label
                    for label, _ in _labelled_blocks(section, "text")
                    if "Window 1" in label
                ]
                self.assertTrue(prompts, f"{title} has no Window 1 prompt")

    def test_demo_covers_fallback_jobs_and_recorded_runtimes(self) -> None:
        content = self.demo
        clean_entry = self.recorded_runtimes["ws1_pipeline_clean_dataproc_runtime_3_0"]
        v1_entry = self.recorded_runtimes["ws1_pipeline_v1_dataproc_runtime_3_0"]

        self.assertIn("recorded_runtimes.json", content)
        self.assertIn(f"{clean_entry['last_observed_seconds']}s", content)
        self.assertIn(f"{v1_entry['last_observed_seconds']}s", content)
        # The agent submits its own Workstream 1C batch, so `--async` is no
        # longer a presenter step; the SQL fallback stays as a Window 2 swap.
        self.assertIn("./run-pipeline-clean --sql-fallback", content)
        self.assertRegex(
            content,
            re.compile(r"Start.*ARIMA_PLUS.*Training\s+First", re.IGNORECASE),
        )

    def test_demo_covers_guardrail_moment_and_checkpoint_swaps(self) -> None:
        content = self.demo

        # Guardrail moment in Antigravity 101
        opening = _segment(content, "Antigravity 101")
        self.assertIn("Guardrail Moment", opening)
        self.assertIn("raw.hospital_flu_feeds", opening)
        self.assertIn("ops.pipeline_run_log", opening)
        self.assertIn(".agents/plugins/ds-command-center/bin/guardrail-hook", opening)
        self.assertRegex(opening, re.compile(r"read-only", re.IGNORECASE))
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
                cmd, content, f"DEMO.md missing Checkpoint swap command: {cmd}"
            )

    def test_demo_is_the_sole_run_through_with_a_section_per_workstream(
        self,
    ) -> None:
        self.assertFalse(
            RETIRED_RUNBOOK_PATH.exists(),
            "DEMO.md is the sole run-through; the presenter runbook is retired",
        )
        for title in (
            "Pre-Stage Checklist",
            "Opening",
            WS1_SECTION,
            "Intermission",
            WS2_SECTION,
            "Q&A",
            "Rehears",
            "Shortened Demo Cuts",
        ):
            with self.subTest(section=title):
                self.assertRegex(self.demo, rf"(?m)^## [^\n]*{re.escape(title)}")

        ws1 = _segment(self.demo, WS1_SECTION)
        for title in WS1_SEGMENTS:
            with self.subTest(workstream=1, segment=title):
                self.assertTrue(_labelled_blocks(_segment(ws1, title), "text"))
        for command in (
            "./checkpoint ws1_eda_heatmap",
            "./checkpoint ws1_attribution",
            "./checkpoint ws1_staging_clean",
            "./run-pipeline-clean --sql-fallback",
            "--verify-equivalence",
        ):
            with self.subTest(workstream=1, command=command):
                self.assertIn(command, ws1)

        ws2 = _segment(self.demo, WS2_SECTION)
        for title in WS2_SEGMENTS:
            with self.subTest(workstream=2, segment=title):
                self.assertTrue(_labelled_blocks(_segment(ws2, title), "text"))
        for script, checkpoints, _ in WS2_FALLBACKS.values():
            for command in (script, *checkpoints):
                with self.subTest(workstream=2, command=command):
                    self.assertIn(command, ws2)
        self.assertIn("./load-reveal", ws2)

    def test_no_tracked_file_links_the_retired_runbook(self) -> None:
        tracked = subprocess.run(
            ["git", "ls-files"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        # Live links and commands only: Markdown docs (ADRs keep their history),
        # presenter scripts and the Makefile.
        for rel in tracked:
            path = REPO_ROOT / rel
            is_doc = rel.endswith(".md") and not rel.startswith("docs/adr/")
            if not (is_doc or rel.startswith("bin/") or rel == "Makefile"):
                continue
            if not path.is_file():
                continue
            with self.subTest(file=rel):
                text = path.read_text(encoding="utf-8", errors="ignore")
                self.assertNotIn("presenter-runbook.md", text)

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
        for path in (REUSER_GUIDE_PATH, README_PATH, DEMO_PATH):
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
                str(REUSER_GUIDE_PATH),
                str(README_PATH),
                str(DEMO_PATH),
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
