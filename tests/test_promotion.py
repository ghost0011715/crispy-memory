import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from promote_windows98_intake import classify_target, connect, promote, should_promote


class PromotionClassificationTests(unittest.TestCase):
    def classify(self, name, extension, **values):
        entry = {
            "entry_name": name,
            "extension": extension,
            "category": "other",
            "tags_json": "[]",
            "preview": "",
        }
        entry.update(values)
        return classify_target(entry, values.get("content", ""))

    def test_windows_paths_and_case_are_normalized(self):
        decision = self.classify(
            r"Windows_98\FileScannerSystem\GO.PY", ".py"
        )
        self.assertEqual(decision["target_layer"], "go_runtime")

    def test_build_and_vendor_directories_are_metadata_only(self):
        decision = self.classify(
            r"package\DIST\runner.exe", ".exe"
        )
        self.assertEqual(decision["decision"], "skip_content")

    def test_unsafe_extension_is_quarantined_before_component_routing(self):
        decision = self.classify(
            r"FileScannerSystem\runner.exe", ".exe"
        )
        self.assertEqual(decision["target_layer"], "unsafe_quarantine")
        self.assertEqual(decision["risk_level"], "high")

    def test_pdf_remains_no_copy_even_when_risk_terms_are_found(self):
        decision = self.classify(
            "documents/guide.pdf", ".pdf", content="password"
        )
        self.assertEqual(decision["decision"], "direct_extract_no_copy")

    def test_risk_detection_uses_word_boundaries(self):
        decision = self.classify(
            "src/tokenizer.py", ".py", content="tokenizer implementation"
        )
        self.assertEqual(decision["target_layer"], "code")

    def test_malformed_tags_do_not_crash_or_promote_unknown_file(self):
        row = {
            "entry_name": "unknown.data",
            "extension": ".data",
            "category": "other",
            "indexed_content": "not-a-flag",
            "tags_json": "{bad json",
        }
        self.assertFalse(should_promote(row))

    def test_unsafe_candidate_tag_is_promoted_and_held(self):
        row = {
            "entry_name": "unknown.data",
            "extension": ".data",
            "category": "other",
            "indexed_content": 0,
            "tags_json": '["unsafe_candidate"]',
        }
        self.assertTrue(should_promote(row))
        decision = classify_target(row, "")
        self.assertEqual(decision["decision"], "hold")

    def test_unlisted_unsafe_extensions_are_still_promoted(self):
        row = {
            "entry_name": "plugin.dll",
            "extension": "DLL",
            "category": "other",
            "indexed_content": 0,
            "tags_json": "[]",
        }
        self.assertTrue(should_promote(row))
        decision = classify_target(row, "")
        self.assertEqual(decision["target_layer"], "unsafe_quarantine")

    def test_file_extension_overrides_inconsistent_metadata(self):
        row = {
            "entry_name": "source/module.py",
            "extension": ".txt",
            "category": "other",
            "indexed_content": 0,
            "tags_json": "[]",
        }
        self.assertTrue(should_promote(row))


class PromotionDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "intake.db"
        con = sqlite3.connect(self.db_path)
        try:
            con.executescript("""
                CREATE TABLE zip_intake_runs (
                    intake_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE zip_intake_entries (
                    intake_id TEXT NOT NULL,
                    entry_name TEXT NOT NULL,
                    extension TEXT,
                    size_bytes INTEGER,
                    category TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    indexed_content INTEGER NOT NULL DEFAULT 0,
                    content_status TEXT,
                    content_sha256 TEXT,
                    preview TEXT,
                    PRIMARY KEY (intake_id, entry_name)
                );
                CREATE TABLE zip_intake_contents (
                    intake_id TEXT NOT NULL,
                    entry_name TEXT NOT NULL,
                    encoding TEXT,
                    content_sha256 TEXT,
                    content TEXT NOT NULL,
                    PRIMARY KEY (intake_id, entry_name)
                );
                INSERT INTO zip_intake_runs VALUES ('intake-1', '2026-10-20T12:00:00');
                INSERT INTO zip_intake_entries VALUES
                    ('intake-1', 'src/app.py', '.py', 12, 'text_or_code', '[]', 1, 'ok', 'abc', ''),
                    ('intake-1', 'SRC\\APP.PY', '.py', 12, 'text_or_code', '[]', 1, 'ok', 'abc', ''),
                    ('intake-1', 'dist/runner.exe', '.exe', 4, 'skipped_noise', '[]', 0, NULL, NULL, ''),
                    ('intake-1', 'notes/readme.md', '.md', 4, 'other', '{bad json', 0, NULL, NULL, '');
                INSERT INTO zip_intake_contents VALUES
                    ('intake-1', 'src/app.py', 'utf-8', 'different', 'print("hello")');
            """)
            con.commit()
        finally:
            con.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_dry_run_does_not_create_review_tables_or_write_rows(self):
        con = sqlite3.connect(self.db_path)
        try:
            before = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        finally:
            con.close()

        report = promote(self.db_path, dry_run=True)

        con = sqlite3.connect(self.db_path)
        try:
            after = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            run_count = con.execute("SELECT COUNT(*) FROM zip_intake_runs").fetchone()[0]
        finally:
            con.close()
        self.assertEqual(before, after)
        self.assertEqual(run_count, 1)
        self.assertEqual(report["promoted_count"], 2)
        self.assertEqual(report["would_queue_count"], 2)
        self.assertEqual(report["newly_queued_count"], 0)
        self.assertEqual(report["duplicate_normalized_path_count"], 1)
        self.assertEqual(report["data_quality_warning_count"], 3)
        self.assertTrue(report["dry_run"])
        queued_readme = next(
            item for item in report["items"]
            if item["entry_name"] == "notes/readme.md"
        )
        self.assertEqual(json.loads(queued_readme["tags_json"]), [])

    def test_promotion_is_idempotent_and_reports_new_rows(self):
        first = promote(self.db_path)
        second = promote(self.db_path)
        self.assertEqual(first["newly_queued_count"], 2)
        self.assertEqual(first["already_queued_count"], 0)
        self.assertEqual(second["newly_queued_count"], 0)
        self.assertEqual(second["already_queued_count"], 2)
        self.assertEqual(second["gold_write"], 0)
        self.assertEqual(second["direct_execution"], 0)
        con = sqlite3.connect(self.db_path)
        try:
            queue_count = con.execute(
                "SELECT COUNT(*) FROM intake_review_queue"
            ).fetchone()[0]
            run_count = con.execute(
                "SELECT COUNT(*) FROM intake_promotion_runs"
            ).fetchone()[0]
        finally:
            con.close()
        self.assertEqual(queue_count, 2)
        self.assertEqual(run_count, 2)

    def test_dry_run_counts_existing_queue_items_without_writing(self):
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("""
                CREATE TABLE intake_review_queue (
                    id INTEGER PRIMARY KEY,
                    intake_id TEXT,
                    entry_name TEXT,
                    target_layer TEXT
                )
            """)
            con.execute(
                "INSERT INTO intake_review_queue VALUES (1, ?, ?, ?)",
                ("intake-1", "src/app.py", "code"),
            )
            con.commit()
        finally:
            con.close()

        report = promote(self.db_path, dry_run=True)

        self.assertEqual(report["would_queue_count"], 1)
        self.assertEqual(report["already_queued_count"], 1)
        self.assertEqual(report["newly_queued_count"], 0)

    def test_missing_database_is_not_created(self):
        missing = self.db_path.parent / "missing.db"
        with self.assertRaises(FileNotFoundError):
            promote(missing, dry_run=True)
        self.assertFalse(missing.exists())

    def test_readonly_connection_rejects_writes(self):
        con = connect(self.db_path, readonly=True)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("CREATE TABLE should_not_exist (id INTEGER)")
        finally:
            con.close()

    def test_unknown_intake_id_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Unknown intake ID"):
            promote(self.db_path, intake_id="unknown", dry_run=True)


if __name__ == "__main__":
    unittest.main()
