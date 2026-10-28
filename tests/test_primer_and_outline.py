import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(REPO_ROOT, "docs")
PRIMER_PATH = os.path.join(DOCS_DIR, "data-science-primer.md")
OUTLINE_PATH = os.path.join(DOCS_DIR, "demo-outline.md")

TOPICS = [
    "Positivity",
    "Sampling Artifact",
    "Simpson's paradox",
    "K-means",
    "ARIMA_PLUS",
    "TimesFM",
    "backtesting",
    "WAPE",
]

AVOID_TERMS = [
    (r"copilot", "Command Center"),
    (r"chatbot", "Command Center"),
    (r"hit[- ]rate", "Positivity"),
    (r"positive[- ]rate", "Positivity"),
    (r"as-of date", "Cutoff"),
    (r"root[- ]cause", "Attribution"),
    (r"validation set", "Reveal"),
    (r"\bholdout\b", "Reveal"),
    (r"\bsnapshot\b", "Start Point"),
]

FORBIDDEN_ID_PATTERNS = [
    r"\bproject-[a-z0-9]{5,}\b",
    r"\b[a-z0-9-]+\.iam\.gserviceaccount\.com\b",
]


class TestPrimerAndOutline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = {}
        for path in [PRIMER_PATH, OUTLINE_PATH]:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    cls.docs[path] = f.read()

    def _get_doc(self, path: str) -> str:
        content = self.docs.get(path)
        if content is None:
            self.skipTest(f"Document missing: {path}")
        return content

    def test_primer_file_exists(self):
        msg = f"Primer file missing: {PRIMER_PATH}"
        self.assertTrue(os.path.isfile(PRIMER_PATH), msg)

    def test_outline_file_exists(self):
        msg = f"Outline file missing: {OUTLINE_PATH}"
        self.assertTrue(os.path.isfile(OUTLINE_PATH), msg)

    def test_primer_covers_required_topics_with_qa(self):
        content = self._get_doc(PRIMER_PATH)

        for topic in TOPICS:
            pattern = re.compile(re.escape(topic), re.IGNORECASE)
            self.assertTrue(
                pattern.search(content),
                f"Primer must cover '{topic}'",
            )

        # Check that Q&A-ready answers exist in the primer
        qa_matches = re.findall(
            r"(?:Q&A|Question|Answer)", content, re.IGNORECASE
        )
        self.assertGreaterEqual(
            len(qa_matches),
            len(TOPICS),
            "Expected Q&A-ready answers for each required topic",
        )

    def test_outline_covers_three_messages_structure_and_reveal(self):
        content = self._get_doc(OUTLINE_PATH)

        # Three messages
        pattern_fits_work_today = r"fits how you work today"
        pattern_directs_army_agents = (
            r"one data scientist directs an army of agents and "
            r"reviews the evidence"
        )
        pattern_team_owned_files = (
            r"skills, subagents, hooks and MCP wiring are files your "
            r"team owns, versions and shares"
        )
        self.assertTrue(
            re.search(pattern_fits_work_today, content, re.IGNORECASE),
            "Outline must include message 1: 'fits how you work today'",
        )
        self.assertTrue(
            re.search(pattern_directs_army_agents, content, re.IGNORECASE),
            "Outline must include message 2: 'one data scientist...'",
        )
        self.assertTrue(
            re.search(pattern_team_owned_files, content, re.IGNORECASE),
            "Outline must include message 3: 'skills, subagents...'",
        )

        # 90-minute structure with timings
        self.assertTrue(
            re.search(r"Opening.*12", content, re.IGNORECASE),
            "Outline must specify Opening (12 min)",
        )
        self.assertTrue(
            re.search(r"Workstream 1.*35", content, re.IGNORECASE),
            "Outline must specify Workstream 1 (35 min)",
        )
        self.assertTrue(
            re.search(r"Workstream 2.*28", content, re.IGNORECASE),
            "Outline must specify Workstream 2 (28 min)",
        )
        self.assertTrue(
            re.search(r"Q&A.*15", content, re.IGNORECASE),
            "Outline must specify Q&A (15 min)",
        )

        # Both workstreams and Reveal
        self.assertIn("Workstream 1", content)
        self.assertIn("Workstream 2", content)
        self.assertIn("Reveal", content)

    def test_tailoring_needs_no_core_content_edits(self):
        content = self._get_doc(OUTLINE_PATH)

        pattern_zero_edits = (
            r"without (?:any )?edits? to (?:the )?repo(?:'s)? core content|"
            r"needs no edits"
        )
        self.assertTrue(
            re.search(pattern_zero_edits, content, re.IGNORECASE),
            "Outline must explain tailoring needs no edits to core content",
        )

    def test_company_neutrality(self):
        for path in [PRIMER_PATH, OUTLINE_PATH]:
            content = self.docs.get(path)
            if content is None:
                continue

            for pat in FORBIDDEN_ID_PATTERNS:
                self.assertFalse(
                    re.search(pat, content),
                    f"Found non-neutral identifier matching '{pat}' in {path}",
                )

    def test_glossary_vocabulary_compliance(self):
        for path in [PRIMER_PATH, OUTLINE_PATH]:
            content = self.docs.get(path)
            if content is None:
                continue

            for pattern, preferred in AVOID_TERMS:
                regex = re.compile(rf"\b{pattern}\b", re.IGNORECASE)
                matches = regex.findall(content)
                msg = (
                    f"Found forbidden term '{pattern}' in {path}. "
                    f"Use '{preferred}' instead."
                )
                self.assertEqual(len(matches), 0, msg)


if __name__ == "__main__":
    unittest.main()
