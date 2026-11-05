"""`make check-docs`: the fast iterate loop for docs-only changes."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _doc_tests() -> list[str]:
    # Ask make for the expanded value rather than parsing the Makefile.
    return subprocess.run(
        [
            "make",
            "-s",
            "--no-print-directory",
            "--eval",
            "print-doc-tests: ; @echo $(DOC_TESTS)",
            "print-doc-tests",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()


class TestCheckDocsTarget(unittest.TestCase):
    def test_every_listed_doc_test_exists(self) -> None:
        tests = _doc_tests()
        self.assertTrue(tests, "DOC_TESTS is empty")
        for test in tests:
            with self.subTest(test=test):
                self.assertTrue((REPO_ROOT / test).is_file(), f"missing {test}")

    def test_target_runs_glossary_ruff_and_doc_tests(self) -> None:
        dry_run = subprocess.run(
            ["make", "-n", "check-docs"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertIn("node bin/check-glossary.js", dry_run)
        self.assertIn("ruff check .", dry_run)
        self.assertIn("ruff format --check .", dry_run)
        for test in _doc_tests():
            with self.subTest(test=test):
                self.assertIn(test.removesuffix(".py").replace("/", "."), dry_run)
        # Docs-only loop: no Terraform or shellcheck.
        self.assertNotRegex(dry_run, r"(?m)^\s*terraform ")
        self.assertNotIn("shellcheck ", dry_run)

    def test_agents_md_points_to_check_docs(self) -> None:
        agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        guardrail = agents.split("### Verification guardrail", 1)[1]
        self.assertIn("make check-docs", guardrail)


if __name__ == "__main__":
    unittest.main()
