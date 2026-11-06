"""Evidence Board frontend contract: built and type-checked in the guardrail and CI.

Spec #88 tests the frontend through its Vite production build and type check
(no component unit tests). These static checks pin that wiring: the build
script type-checks then bundles, the pre-commit hook and CI both run it, and
the board carries no Gemini Data Analytics chat panel.
"""

from __future__ import annotations

import json
import re
import unittest

from tests.helpers import WORKTREE_ROOT

FRONTEND_DIR = (
    WORKTREE_ROOT
    / ".agents"
    / "plugins"
    / "ds-command-center"
    / "sidecars"
    / "evidence-board"
    / "frontend"
)
FRONTEND_REL = FRONTEND_DIR.relative_to(WORKTREE_ROOT).as_posix()


class FrontendBuildContractTest(unittest.TestCase):
    def test_build_script_type_checks_then_bundles_with_vite(self) -> None:
        package = json.loads((FRONTEND_DIR / "package.json").read_text("utf-8"))

        build = package["scripts"]["build"]

        self.assertRegex(build, r"\btsc\b.*&&.*\bvite build\b")
        for dep in ("react", "echarts"):
            self.assertIn(dep, package["dependencies"])
        self.assertTrue((FRONTEND_DIR / "package-lock.json").is_file())

    def test_make_target_installs_and_builds_the_frontend(self) -> None:
        makefile = (WORKTREE_ROOT / "Makefile").read_text("utf-8")

        target = re.search(
            r"^build-frontend:.*?(?=^\S|\Z)", makefile, re.MULTILINE | re.DOTALL
        )

        self.assertIsNotNone(target, "Makefile needs a build-frontend target")
        self.assertIn(FRONTEND_REL, makefile)
        self.assertIn("npm ci", target.group(0))
        self.assertIn("npm run build", target.group(0))

    def test_pre_commit_and_ci_both_build_the_frontend(self) -> None:
        for rel in (".husky/pre-commit", ".github/workflows/ci.yml"):
            with self.subTest(file=rel):
                text = (WORKTREE_ROOT / rel).read_text("utf-8")
                self.assertRegex(text, r"(?m)^\s*(run:\s*)?make build-frontend\s*$")

    def test_built_bundle_is_gitignored(self) -> None:
        gitignore = (WORKTREE_ROOT / ".gitignore").read_text("utf-8")

        self.assertIn(f"{FRONTEND_REL}/dist/", gitignore.splitlines())

    def test_no_gemini_data_analytics_chat_panel(self) -> None:
        package = (FRONTEND_DIR / "package.json").read_text("utf-8")
        sources = "\n".join(
            p.read_text("utf-8")
            for p in sorted((FRONTEND_DIR / "src").rglob("*"))
            if p.is_file()
        )

        for text in (package, sources):
            self.assertNotRegex(
                text, r"(?i)geminidataanalytics|data[_-]?analytics|ChatPanel"
            )

    def test_charts_import_the_esm_build_of_echarts_for_react(self) -> None:
        # The CJS `lib/` entry reaches the browser as `{ default }`, so React
        # throws error #130 and the whole board goes blank once a chart lands.
        for path in sorted((FRONTEND_DIR / "src").rglob("*.tsx")):
            with self.subTest(path=path.name):
                self.assertNotRegex(
                    path.read_text("utf-8"), r"from\s+[\"']echarts-for-react/lib/"
                )


if __name__ == "__main__":
    unittest.main()
