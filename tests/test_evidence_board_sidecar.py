"""Evidence Board sidecar packaging and install (#91).

Seams: the sidecar descriptor (static contract), the `install-evidence-board`
CLI run against a temp home via `--home-dir` (prior art: `stage-clean-env`
tests), and the pre-stage docs and `ds-command-center` rules that reference it.
Standard library only: no FastAPI, no npm, no GCP.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import WORKTREE_ROOT, create_demo_env_file

PLUGIN_DIR = WORKTREE_ROOT / ".agents" / "plugins" / "ds-command-center"
SIDECAR_DIR = PLUGIN_DIR / "sidecars" / "evidence-board"
DESCRIPTOR = SIDECAR_DIR / "sidecar.json"
AUX_PANE = "SIDECAR_UI_ENTRYPOINT_AUX_PANE"
INSTALL_BIN = WORKTREE_ROOT / "bin" / "install-evidence-board"
INSTALL_SYMLINK = WORKTREE_ROOT / "install-evidence-board"
# A standalone global sidecar, not a global `ds-command-center` plugin: that
# would share a folder name (and its enable toggle) with the workspace plugin.
INSTALLED_REL = Path(".gemini", "config", "sidecars", "evidence-board")
SIDECAR_ID = "evidence-board"
USER_CONFIG_REL = Path(".gemini", "config", "config.json")


class SidecarDescriptorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.descriptor = json.loads(DESCRIPTOR.read_text("utf-8"))

    def test_descriptor_has_web_ui_and_exactly_one_aux_pane_view(self) -> None:
        self.assertIs(self.descriptor.get("has_web_ui"), True)
        views = self.descriptor["ui_config"]["views"]
        self.assertEqual(len(views), 1)
        self.assertEqual(
            views[0],
            {"entrypoint": AUX_PANE, "path": "/", "title": "Evidence Board"},
        )
        self.assertEqual(self.descriptor["display_name"], "Evidence Board")

    def test_descriptor_runs_a_command_that_ships_in_the_sidecar(self) -> None:
        self.assertNotIn("builtin", self.descriptor)
        self.assertEqual(self.descriptor["command"], "bash")
        script = SIDECAR_DIR / self.descriptor["args"][0]
        self.assertTrue(script.is_file(), f"{script} must ship with the sidecar")


def _tree(root: Path) -> dict[str, bytes]:
    """Relative path -> bytes for every file under `root`."""
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


class InstallCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "home"
        self.workspace = Path(tmp.name) / "stage clone"
        self.workspace.mkdir(parents=True)
        create_demo_env_file(self.workspace)
        self.user_config = self.home / USER_CONFIG_REL
        self.user_config.parent.mkdir(parents=True)
        self.user_config.write_text('{"plugins": {}}\n', "utf-8")
        self.installed = self.home / INSTALLED_REL

        # A fake interpreter the installer records; the installed entrypoint
        # runs it, so its argv shows how the sidecar would start the backend.
        self.fake_python = Path(tmp.name) / "fake-python"
        self.fake_python.write_text(
            '#!/usr/bin/env bash\nprintf "%s\\n" "$PWD" "$@"\n', "utf-8"
        )
        self.fake_python.chmod(0o755)

    def _install(self, *extra: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ, PYTHON=str(self.fake_python))
        return subprocess.run(
            [
                str(INSTALL_SYMLINK),
                "--home-dir",
                str(self.home),
                "--workspace",
                str(self.workspace),
                "--no-build",
                *extra,
            ],
            cwd=WORKTREE_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_wrapper_is_an_executable_root_symlink(self) -> None:
        self.assertTrue(os.access(INSTALL_BIN, os.X_OK))
        self.assertTrue(INSTALL_SYMLINK.is_symlink())
        self.assertEqual(INSTALL_SYMLINK.resolve(), INSTALL_BIN.resolve())

    def test_copies_a_standalone_global_sidecar_without_symlinks(
        self,
    ) -> None:
        proc = self._install()

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        for rel in ("sidecar.json", "tiles.json", "board/__main__.py", "bin/serve"):
            path = self.installed / rel
            self.assertTrue(path.is_file(), f"missing installed {rel}")
            self.assertEqual(path.read_bytes(), (SIDECAR_DIR / rel).read_bytes())
        for path in [self.installed, *self.installed.rglob("*")]:
            self.assertFalse(path.is_symlink(), f"{path} must be a copy")
        self.assertEqual(list(self.installed.rglob("node_modules")), [])
        self.assertFalse((self.home / ".gemini" / "config" / "plugins").exists())

    def test_installed_entrypoint_starts_the_backend_against_the_workspace(
        self,
    ) -> None:
        self.assertEqual(self._install().returncode, 0)
        descriptor = json.loads((self.installed / "sidecar.json").read_text("utf-8"))

        # Antigravity runs the descriptor command from the sidecar folder.
        started = subprocess.run(
            [descriptor["command"], *descriptor["args"]],
            cwd=self.installed,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(started.returncode, 0, started.stderr)
        cwd, *argv = started.stdout.splitlines()
        self.assertEqual(Path(cwd).resolve(), self.installed.resolve())
        self.assertEqual(argv, ["-m", "board", "--workspace", str(self.workspace)])

    def test_reinstall_is_idempotent_and_drops_stale_files(self) -> None:
        self.assertEqual(self._install().returncode, 0)
        first = _tree(self.installed)
        (self.installed / "stale.txt").write_text("old install", "utf-8")

        again = self._install()

        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertEqual(_tree(self.installed), first)
        siblings = sorted(p.name for p in self.installed.parent.iterdir())
        self.assertEqual(siblings, ["evidence-board"])

    def test_reinstall_warns_when_a_running_sidecar_still_serves_the_old_copy(
        self,
    ) -> None:
        self.assertEqual(self._install().returncode, 0)
        # Antigravity runs the sidecar with the installed folder as its cwd; a
        # process there keeps serving the old copy until it restarts.
        running = subprocess.Popen(["sleep", "30"], cwd=self.installed)
        self.addCleanup(running.wait)
        self.addCleanup(running.kill)

        again = self._install()

        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn("[WARN]", again.stderr)
        self.assertIn(str(running.pid), again.stderr)
        self.assertIn("restart", again.stderr)

    def test_fresh_install_prints_no_running_sidecar_warning(self) -> None:
        proc = self._install()

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("still running", proc.stderr)

    def test_never_touches_the_antigravity_user_config_and_prints_enable_step(
        self,
    ) -> None:
        before = self.user_config.stat()

        proc = self._install()

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        after = self.user_config.stat()
        self.assertEqual(self.user_config.read_text("utf-8"), '{"plugins": {}}\n')
        self.assertEqual(
            (before.st_mtime_ns, before.st_ino), (after.st_mtime_ns, after.st_ino)
        )
        self.assertIn(str(self.user_config), proc.stdout)
        self.assertIn(f'"{SIDECAR_ID}": {{"enabled": true}}', proc.stdout)

    def test_fails_without_demo_env_in_the_workspace_and_installs_nothing(
        self,
    ) -> None:
        (self.workspace / "demo.env").unlink()

        proc = self._install()

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("demo.env", proc.stderr)
        self.assertFalse(self.installed.exists())


class PreStageAndRulesTest(unittest.TestCase):
    def test_pre_stage_setup_installs_the_board_once_per_machine(self) -> None:
        demo = (WORKTREE_ROOT / "DEMO.md").read_text("utf-8")
        checklist = demo.split("\n## 3.", 1)[0].split("\n## 2. Pre-Stage Checklist", 1)[
            1
        ]
        steps = checklist.split("\n### ")[1:]
        installs = [s for s in steps if "./install-evidence-board" in s]

        self.assertEqual(len(installs), 1)
        step = installs[0]
        heading = step.splitlines()[0]
        self.assertIn("Window 2", heading)
        self.assertIn("Once per Machine", heading)
        # The enable step restarts the App, so it runs with the stage clone
        # setup, before the T-15 steps rather than among them.
        self.assertLess(
            steps.index(step),
            next(i for i, s in enumerate(steps) if s.startswith("Step 1:")),
        )
        self.assertIn("--workspace ~/demo-stage/agy-ws1", step)
        self.assertIn(f'"{SIDECAR_ID}": {{"enabled": true}}', step)
        self.assertIn("config.json", step)
        self.assertNotIn("ds-command-center/evidence-board", demo)

    def test_rules_name_the_board_the_tile_manifest_and_the_pill(self) -> None:
        rules = (PLUGIN_DIR / "rules" / "AGENTS.md").read_text("utf-8")
        # Glossary terms are bolded in the rules; compare the plain text.
        section = rules.replace("**", "").split("\n## 6. Evidence Board\n", 1)[1]
        section = section.split("\n## ", 1)[0]

        self.assertIn("sidecars/evidence-board/tiles.json", section)
        self.assertIn("Tile manifest", section)
        self.assertIn(f"[Evidence Board](sidecar://{SIDECAR_ID}/)", section)
        self.assertNotIn("ds-command-center/evidence-board", section)


if __name__ == "__main__":
    unittest.main()
