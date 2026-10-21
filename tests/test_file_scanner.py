import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from file_scanner import FileDuplicateFinder, FileScanner
from main import FileAnalysisApp
from utils import format_bytes


class FileScannerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "nested").mkdir()
        (self.root / "alpha.txt").write_text("same content", encoding="utf-8")
        (self.root / "nested" / "copy.txt").write_text(
            "same content", encoding="utf-8"
        )
        (self.root / "nested" / "unique.py").write_text(
            "print('hello')", encoding="utf-8"
        )
        (self.root / ".hidden.txt").write_text("hidden", encoding="utf-8")
        (self.root / ".hidden-dir").mkdir()
        (self.root / ".hidden-dir" / "secret.txt").write_text(
            "hidden", encoding="utf-8"
        )
        (self.root / "__pycache__").mkdir()
        (self.root / "__pycache__" / "cached.pyc").write_bytes(b"bytecode")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_scan_excludes_hidden_entries_by_default(self):
        files = FileScanner(self.root).scan_directory()
        names = {item["name"] for item in files}
        self.assertEqual(names, {"alpha.txt", "copy.txt", "unique.py"})

    def test_scan_can_include_hidden_files_and_directories(self):
        files = FileScanner(self.root).scan_directory(include_hidden=True)
        self.assertEqual(len(files), 5)

    def test_scan_ignores_python_bytecode_caches(self):
        files = FileScanner(self.root).scan_directory(include_hidden=True)
        self.assertFalse(any(item["extension"] in {".pyc", ".pyo"} for item in files))

    def test_scan_returns_required_metadata_and_statistics(self):
        scanner = FileScanner(self.root)
        files = scanner.scan_directory()
        self.assertTrue(
            {"name", "path", "size_bytes", "extension", "modified_time"}
            <= files[0].keys()
        )
        stats = scanner.get_statistics(files)
        self.assertEqual(stats["total_files"], 3)
        self.assertEqual(stats["by_extension"], {".py": 1, ".txt": 2})
        self.assertEqual(stats["total_size_bytes"], sum(f["size_bytes"] for f in files))

    def test_extension_filter_normalizes_whitespace_and_case(self):
        scanner = FileScanner(self.root)
        files = scanner.scan_directory()
        selected = scanner.filter_by_extension(files, [" PY ", ".TXT"])
        self.assertEqual(len(selected), 3)

    def test_duplicate_finder_compares_contents_not_only_size(self):
        scanner = FileScanner(self.root)
        files = scanner.scan_directory()
        duplicates = FileDuplicateFinder().find_duplicates(files)
        self.assertEqual(len(duplicates), 1)
        group = next(iter(duplicates.values()))
        self.assertEqual({item["name"] for item in group}, {"alpha.txt", "copy.txt"})

    def test_missing_or_non_directory_path_is_reported(self):
        with self.assertRaises(FileNotFoundError):
            FileScanner(self.root / "missing").scan_directory()
        with self.assertRaises(NotADirectoryError):
            FileScanner(self.root / "alpha.txt").scan_directory()

    def test_empty_statistics_are_well_defined(self):
        stats = FileScanner.get_statistics([])
        self.assertEqual(stats["total_files"], 0)
        self.assertEqual(stats["total_size_bytes"], 0)
        self.assertIsNone(stats["largest_file"])

    def test_local_analysis_summary_does_not_require_network_or_api_keys(self):
        files = FileScanner(self.root).scan_directory()
        summary = FileAnalysisApp.analyze_files(files)
        self.assertEqual(summary["total_files"], 3)
        self.assertEqual(summary["top_extensions"][0], {
            "extension": ".txt",
            "count": 2,
        })

    def test_byte_formatting(self):
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(1024), "1.00 KB")


class CommandLineTests(unittest.TestCase):
    def test_scan_command_writes_utf8_json_report_and_duplicate_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "first.txt").write_text("duplicate", encoding="utf-8")
            (root / "second.txt").write_text("duplicate", encoding="utf-8")
            report_path = root / "نتائج.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parents[1] / "cli.py"),
                    "--scan",
                    str(root),
                    "--find-duplicates",
                    "--analyze",
                    "--output",
                    str(report_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["total_files"], 2)
            self.assertEqual(len(report["duplicates"]), 1)
            self.assertEqual(report["analysis"]["total_files"], 2)

    def test_cli_help_starts_without_missing_module_imports(self):
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[1] / "cli.py"),
                "--help",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--scan", result.stdout)


if __name__ == "__main__":
    unittest.main()
