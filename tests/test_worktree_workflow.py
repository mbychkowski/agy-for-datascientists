"""Worktree workflow guards: pre-commit refuses main, CI enforces branch names, docs agree."""

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import WORKTREE_ROOT, write_noop_stubs

PRE_COMMIT = WORKTREE_ROOT / ".husky" / "pre-commit"
CI_YML = WORKTREE_ROOT / ".github" / "workflows" / "ci.yml"
AGENTS_MD = WORKTREE_ROOT / "AGENTS.md"
README_MD = WORKTREE_ROOT / "README.md"


def ci_branch_pattern() -> str:
    """The branch-name regex exactly as the CI step declares it."""
    match = re.search(
        r"^\s*pattern='([^']+)'$", CI_YML.read_text(encoding="utf-8"), re.MULTILINE
    )
    assert match, "ci.yml must declare pattern='<regex>' in the branch-name step"
    return match.group(1)


class TestPreCommitMainGuard(unittest.TestCase):
    """Runs .husky/pre-commit the way husky does (`sh -e`) in a throwaway repo."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name) / "repo"
        stub_bin = Path(tmp.name) / "bin"
        self.repo.mkdir()
        # Stub the verification tools so only the branch guard is exercised.
        write_noop_stubs(stub_bin, "uvx", "make")
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
            with self.subTest(branch=branch):
                proc = self._run_pre_commit_on(branch)
                self.assertEqual(proc.returncode, 0, proc.stderr)


class TestBranchNameCheck(unittest.TestCase):
    def test_ci_checks_branch_name_on_pull_requests_only(self):
        ci_text = CI_YML.read_text(encoding="utf-8")
        self.assertEqual(ci_branch_pattern(), "^(issue[0-9]{3}|chore)/[a-z0-9-]+$")
        self.assertIn("if: github.event_name == 'pull_request'", ci_text)
        self.assertIn("name: Check & Test", ci_text)

    def test_branch_pattern_accepts_conventions_only(self):
        """Evaluate the ci.yml pattern with bash `=~`, as the CI step does."""
        pattern = ci_branch_pattern()

        def matches(branch: str) -> bool:
            script = 'pattern=$1; [[ "$2" =~ $pattern ]]'
            proc = subprocess.run(
                ["bash", "-c", script, "_", pattern, branch], check=False
            )
            return proc.returncode == 0

        cases = {
            "issue019/fix-preflight": True,
            "chore/worktree-rule": True,
            "main": False,
            "fix/foo": False,
            "issue19/foo": False,
            "chore/Upper": False,
            "chore/": False,
        }
        for branch, expected in cases.items():
            with self.subTest(branch=branch):
                self.assertEqual(matches(branch), expected)


class TestWorktreeDocs(unittest.TestCase):
    def test_agents_md_states_issue_and_chore_conventions(self):
        agents_text = AGENTS_MD.read_text(encoding="utf-8")
        self.assertIn(
            "`.worktree/issue-<3-digit-id>` on branch `issue<3-digit-id>/<slug>`",
            agents_text,
        )
        self.assertIn("`.worktree/chore-<slug>` on branch `chore/<slug>`", agents_text)
        self.assertIn("npm ci", agents_text)

    def test_agents_md_removes_worktree_only_if_still_listed(self):
        # gh pr merge --delete-branch usually removes the worktree already.
        agents_text = AGENTS_MD.read_text(encoding="utf-8")
        self.assertIn("git worktree list", agents_text)
        self.assertNotIn("pull `main`, and remove the worktree", agents_text)

    def test_agents_md_briefs_reviewers_with_guardrail_result(self):
        # Reviewers should not re-run or re-flag what the hook already enforces.
        agents_text = AGENTS_MD.read_text(encoding="utf-8")
        review_line = next(
            line for line in agents_text.splitlines() if "/code-review" in line
        )
        self.assertIn("guardrail", review_line)

    def test_agents_md_requires_scripted_edits_to_assert_match_counts(self):
        # Silent zero- or over-matching replaces have mislabelled docs before.
        agents_text = AGENTS_MD.read_text(encoding="utf-8")
        self.assertRegex(agents_text, r"(?i)scripted.*edit.*match count")

    def test_readme_points_to_agents_md(self):
        readme_text = README_MD.read_text(encoding="utf-8")
        self.assertIn("AGENTS.md#worktree-execution", readme_text)
        self.assertNotIn(".worktree/<branch-slug>", readme_text)


if __name__ == "__main__":
    unittest.main()
