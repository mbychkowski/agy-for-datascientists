"""bin/check-glossary.js: avoid-terms inside phrases, and bolded glossary terms."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKER = REPO_ROOT / "bin" / "check-glossary.js"


def _run_checker(text: str) -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as handle:
        handle.write(text)
    try:
        return subprocess.run(
            ["node", str(CHECKER), handle.name],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        Path(handle.name).unlink()


def _unbolded(text: str) -> list[dict]:
    script = (
        "const g = require(process.argv[1]);"
        "const text = require('fs').readFileSync(0, 'utf8');"
        "console.log(JSON.stringify(g.findUnboldedTerms(text, g.loadGlossaryTerms())));"
    )
    proc = subprocess.run(
        ["node", "-e", script, str(CHECKER)],
        input=text,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


class TestAvoidTermsInPhrases(unittest.TestCase):
    def test_baseline_phrases_for_the_seasonal_ramp_fail(self) -> None:
        for phrase in (
            "a baseline trend",  # glossary-ignore
            "baseline growth",  # glossary-ignore
            "expected baseline increase",  # glossary-ignore
            "a baseline rise",  # glossary-ignore
            "a baseline-trend",  # glossary-ignore
            "a Baseline Trend",  # glossary-ignore
        ):
            with self.subTest(phrase=phrase):
                proc = _run_checker(f"Hospitals share {phrase}.\n")
                self.assertEqual(proc.returncode, 1, proc.stdout)
                self.assertIn("Seasonal Ramp", proc.stderr)

    def test_statistical_baseline_and_trend_still_pass(self) -> None:
        proc = _run_checker(
            "ARIMA_PLUS is a classical baseline that handles trend and seasonality.\n"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


class TestGlossaryTermsAreBolded(unittest.TestCase):
    def test_terms_come_from_glossary_headings(self) -> None:
        script = (
            "console.log(JSON.stringify(require(process.argv[1]).loadGlossaryTerms()));"
        )
        terms = json.loads(
            subprocess.run(
                ["node", "-e", script, str(CHECKER)],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        for term in ("Attribution", "Seasonal Ramp", "Checkpoint", "Cohort"):
            self.assertIn(term, terms)

    def test_unbolded_term_in_prose_is_reported(self) -> None:
        found = _unbolded("The agents present an Attribution table.\n")
        self.assertEqual([(v["line"], v["match"]) for v in found], [(1, "Attribution")])

    def test_plural_and_italic_quotes_are_reported(self) -> None:
        found = _unbolded('*"Why 4 Cohorts instead of 90 models?"*\n')
        self.assertEqual([v["match"] for v in found], ["Cohorts"])

    def test_exempt_contexts_pass(self) -> None:
        text = """\
## 4. Workstream 1: the Attribution heading
| Segment | Checkpoint |
| :--- | :--- |
| body | **Checkpoint** swap |
Bold **Attribution** and **Seasonal Ramps** are fine.
Code `./checkpoint ws1_attribution` and `Cohort` are fine.
- [Workstream 2 & The Reveal](#43-workstream-2)
```sql
-- Cohort assignments
```
A deliberate Attribution mention. <!-- glossary-ignore -->
"""
        self.assertEqual(_unbolded(text), [])

    def test_ignore_comment_on_the_line_above_is_honoured(self) -> None:
        text = "<!-- glossary-ignore -->\nAn Attribution mention.\n"
        self.assertEqual(_unbolded(text), [])

    def test_code_spans_containing_bold_markers_do_not_hide_terms(self) -> None:
        found = _unbolded("`a**b` Attribution `c**d`\n")
        self.assertEqual([v["match"] for v in found], ["Attribution"])

    def test_bold_check_applies_only_to_demo_and_runbook(self) -> None:
        script = (
            "const g = require(process.argv[1]);"
            "const out = {};"
            "for (const f of process.argv.slice(2)) {"
            "  out[f] = g.checkContent(f, 'An Attribution table.\\n').length;"
            "}"
            "console.log(JSON.stringify(out));"
        )
        files = [
            "DEMO.md",
            "docs/presenter-runbook.md",
            "docs\\presenter-runbook.md",
            "README.md",
            "docs/demo-outline.md",
        ]
        counts = json.loads(
            subprocess.run(
                ["node", "-e", script, str(CHECKER), *files],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        self.assertEqual(
            counts,
            {
                "DEMO.md": 1,
                "docs/presenter-runbook.md": 1,
                "docs\\presenter-runbook.md": 1,
                "README.md": 0,
                "docs/demo-outline.md": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()
