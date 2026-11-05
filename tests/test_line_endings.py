"""Every tracked text file is LF in the git index, including staged changes.

Agent tool output can render `\\r\\n` for LF files, so line endings are checked
against the index instead of trusted by eye. `git ls-files --eol` reads the
index, so a CRLF file staged for the commit under way fails the pre-commit hook.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BAD_INDEX_EOLS = {"i/crlf", "i/mixed"}


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _inside_git_worktree() -> bool:
    if shutil.which("git") is None:
        return False
    result = _git("rev-parse", "--is-inside-work-tree")
    return result.returncode == 0 and result.stdout.strip() == "true"


@unittest.skipUnless(_inside_git_worktree(), "not inside a git worktree")
class TestLineEndings(unittest.TestCase):
    def test_no_crlf_or_mixed_line_endings_in_index(self) -> None:
        result = _git("ls-files", "--eol", "-z")
        self.assertEqual(result.returncode, 0, result.stderr)
        offenders = []
        for entry in filter(None, result.stdout.split("\0")):
            info, path = entry.split("\t", 1)
            index_eol = info.split()[0]
            if index_eol in BAD_INDEX_EOLS:
                offenders.append(f"{index_eol} {path}")
        self.assertEqual(
            offenders,
            [],
            "CRLF line endings in the git index; convert to LF and re-stage:\n"
            + "\n".join(offenders),
        )

    def test_gitattributes_normalizes_text_to_lf(self) -> None:
        result = _git("check-attr", "text", "eol", "--", "GLOSSARY.md")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("GLOSSARY.md: text: auto", result.stdout)
        self.assertIn("GLOSSARY.md: eol: lf", result.stdout)


if __name__ == "__main__":
    unittest.main()
