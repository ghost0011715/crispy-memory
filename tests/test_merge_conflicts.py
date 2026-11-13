"""Regression checks for unresolved merge conflicts in source-critical files."""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPAIRED_FILES = (
    "file_intake.py",
    "sovereign_runtime.py",
    "tests/test_universal_intake.py",
    ".github/workflows/python-app.yml",
    ".berk/egitim_indeks.json",
)
CONFLICT_MARKERS = ("<<<<<<< ", "=======", ">>>>>>> ")


class MergeConflictRegressionTests(unittest.TestCase):
    def test_no_unresolved_conflicts(self):
        for relative in REPAIRED_FILES:
            with self.subTest(path=relative):
                content = (ROOT / relative).read_text(encoding="utf-8")
                conflicts = [
                    number
                    for number, line in enumerate(content.splitlines(), start=1)
                    if line.lstrip().startswith(CONFLICT_MARKERS)
                ]
                self.assertEqual(conflicts, [], f"{relative}: merge conflict markers")

    def test_python_syntax(self):
        for relative in REPAIRED_FILES:
            if not relative.endswith(".py"):
                continue
            with self.subTest(path=relative):
                source = (ROOT / relative).read_text(encoding="utf-8")
                ast.parse(source, filename=relative)

    def test_json_index_integrity(self):
        content = (ROOT / ".berk/egitim_indeks.json").read_text(encoding="utf-8")
        self.assertIsInstance(json.loads(content), dict)


if __name__ == "__main__":
    unittest.main()
