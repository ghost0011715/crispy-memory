"""Read-only integrity proof for the committed SQLite artifact.

This checks only the repository fixture. It never upgrades, writes, VACUUMs,
deletes, or asserts that the artifact is the live production database.
"""
from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path


class CommittedSQLiteIntegrityTests(unittest.TestCase):
    def test_checked_in_database_integrity_and_fk_readback(self):
        path = Path(__file__).resolve().parents[1] / "out" / "windows98_intake_new.db"
        self.assertTrue(path.is_file(), "COMMITTED_SQLITE_ARTIFACT_MISSING")
        # SQLite immutable=1 forces read-only and avoids journal/WAL creation.
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
        try:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertGreaterEqual(conn.execute("PRAGMA page_count").fetchone()[0], 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
