"""Worktree workflow guards: pre-commit refuses main, CI enforces branch names, docs agree."""

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import WORKTREE_ROOT

PRE_COMMIT = WORKTREE_ROOT / ".husky" / "pre-commit"
CI_YML = WORKTREE_ROOT / ".github" / "workflows" / "ci.yml"
AGENTS_MD = WORKTREE_ROOT / "AGENTS.md"
README_MD = WORKTREE_ROOT / "README.md"
BRANCH_PATTERN = "^(issue[0-9]{3}|chore)/[a-z0-9-]+$"


class TestPreCommitMainGuard(unittest.TestCase):
    """Runs .husky/pre-commit the way husky does (`sh -e`) in a throwaway repo."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name) / "repo"
        stub_bin = Path(tmp.name) / "bin"
        self.repo.mkdir()
        stub_bin.mkdir()
        # Stub the verification tools so only the branch guard is exercised.
        for tool in ("uvx", "make"):
            stub = stub_bin / tool
            stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        # Drop GIT_* so a hook-invoked test run never touches the real repo.
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env["PATH"] = f"{stub_bin}{os.pathsep}{self.env['PATH']}"
        self._git("init", "-q")

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.repo, env=self.env, check=True)

    def _run_pre_commit_on(self, branch: str) -> subprocess.CompletedProcess:
        self._git("symbolic-ref", "HEAD", f"refs/heads/{branch}")
        return subprocess.run(
            ["sh", "-e", str(PRE_COMMIT)],
            check=False,
            cwd=self.repo,
            env=self.env,
            capture_output=True,
            text=True,
        )

    def test_refuses_commit_on_main(self):
        proc = self._run_pre_commit_on("main")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("refusing to commit on main", proc.stderr)

    def test_allows_commit_on_feature_branch(self):
        for branch in ("chore/worktree-rule", "issue019/fix-preflight"):
            proc = self._run_pre_commit_on(branch)
            self.assertEqual(proc.returncode, 0, f"{branch}: {proc.stderr}")


class TestBranchNameCheck(unittest.TestCase):
    def test_ci_checks_branch_name_on_pull_requests_only(self):
        ci_text = CI_YML.read_text(encoding="utf-8")
        self.assertIn(f"pattern='{BRANCH_PATTERN}'", ci_text)
        self.assertIn("if: github.event_name == 'pull_request'", ci_text)
        self.assertIn("name: Check & Test", ci_text)

    def test_branch_pattern_accepts_conventions_only(self):
        """Evaluate the pattern with bash `=~`, as the CI step does."""

        def matches(branch: str) -> bool:
            script = 'pattern=$1; [[ "$2" =~ $pattern ]]'
            proc = subprocess.run(
                ["bash", "-c", script, "_", BRANCH_PATTERN, branch], check=False
            )
            return proc.returncode == 0

        for ok in ("issue019/fix-preflight", "chore/worktree-rule"):
            self.assertTrue(matches(ok), ok)
        for bad in ("main", "fix/foo", "issue19/foo", "chore/Upper", "chore/"):
            self.assertFalse(matches(bad), bad)


class TestWorktreeDocs(unittest.TestCase):
    def test_agents_md_states_issue_and_chore_conventions(self):
        agents_text = AGENTS_MD.read_text(encoding="utf-8")
        self.assertIn(
            "`.worktree/issue-<3-digit-id>` on branch `issue<3-digit-id>/<slug>`",
            agents_text,
        )
        self.assertIn("`.worktree/chore-<slug>` on branch `chore/<slug>`", agents_text)
        self.assertIn("npm ci", agents_text)

    def test_readme_points_to_agents_md(self):
        readme_text = README_MD.read_text(encoding="utf-8")
        self.assertIn("AGENTS.md#worktree-execution", readme_text)
        self.assertNotIn(".worktree/<branch-slug>", readme_text)


if __name__ == "__main__":
    unittest.main()
