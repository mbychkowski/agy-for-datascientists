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
INSTALLED_REL = Path(
    ".gemini", "config", "plugins", "ds-command-center", "sidecars", "evidence-board"
)
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

    def test_copies_the_sidecar_under_ds_command_center_without_symlinks(
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
        self.assertIn('"ds-command-center/evidence-board"', proc.stdout)
        self.assertIn('"enabled": true', proc.stdout)

    def test_fails_without_demo_env_in_the_workspace_and_installs_nothing(
        self,
    ) -> None:
        (self.workspace / "demo.env").unlink()

        proc = self._install()

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("demo.env", proc.stderr)
        self.assertFalse(self.installed.exists())


class PreStageAndRulesTest(unittest.TestCase):
    def test_pre_stage_checklist_installs_the_board_from_window_2(self) -> None:
        demo = (WORKTREE_ROOT / "DEMO.md").read_text("utf-8")
        checklist = demo.split("## 3.", 1)[0].split("## 2. Pre-Stage Checklist", 1)[1]
        step = next(
            s for s in checklist.split("\n### ") if "./install-evidence-board" in s
        )

        self.assertIn("Window 2", step)
        self.assertIn("--workspace ~/demo-stage/agy-ws1", step)
        self.assertIn('"ds-command-center/evidence-board"', step)
        self.assertIn("config.json", step)

    def test_rules_name_the_board_the_tile_manifest_and_the_pill(self) -> None:
        rules = (PLUGIN_DIR / "rules" / "AGENTS.md").read_text("utf-8")
        # Glossary terms are bolded in the rules; compare the plain text.
        section = rules.replace("**", "").split("\n## 6. Evidence Board\n", 1)[1]

        self.assertIn("sidecars/evidence-board/tiles.json", section)
        self.assertIn("Tile manifest", section)
        self.assertIn(
            "[Evidence Board](sidecar://ds-command-center/evidence-board/)", section
        )


if __name__ == "__main__":
    unittest.main()
