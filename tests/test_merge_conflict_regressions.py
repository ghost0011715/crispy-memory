"""Regression checks for the merge-conflict fixes on isolated temp workspaces.

These tests never start a training run or touch production data.
"""
import tempfile
import unittest
from pathlib import Path

from file_intake import FileIntake, IntakeError
from sovereign_runtime import RuntimeErrorState, SovereignRuntime


class MergeConflictRegressionTests(unittest.TestCase):
    def test_file_intake_rejects_invalid_input_before_path_construction(self):
        with tempfile.TemporaryDirectory() as root:
            intake = FileIntake(Path(root) / "output")
            with self.assertRaisesRegex(IntakeError, "SOURCE_MUST_BE_FILE_OR_DIRECTORY"):
                intake.process(None)
            with self.assertRaisesRegex(IntakeError, "SOURCE_MUST_BE_FILE_OR_DIRECTORY"):
                intake.process([])

    def test_runtime_rejects_non_path_without_raw_type_error(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = SovereignRuntime(
                runtime_root=Path(root) / "state", allowed_roots=[root]
            )
            with self.assertRaisesRegex(RuntimeErrorState, "PATH_INVALID"):
                runtime.assert_allowed_path(None)
            with self.assertRaisesRegex(RuntimeErrorState, "PATH_INVALID"):
                runtime.assert_allowed_path({})

    def test_ticket_gate_blocks_missing_operation_and_command(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = SovereignRuntime(
                runtime_root=Path(root) / "state", allowed_roots=[root]
            )
            result = runtime.verify_ticket(
                ticket_id="unknown", source_id="SRC-unset",
                operation=None, command=None, cwd=root,
            )
            self.assertEqual(result["state"], "BLOCKED")
            self.assertIn("TICKET_NOT_FOUND", result["blockers"])
            self.assertIn("OPERATION_REQUIRED", result["blockers"])
            self.assertIn("COMMAND_REQUIRED", result["blockers"])

    def test_run_one_rejects_blank_command_before_execution(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = SovereignRuntime(
                runtime_root=Path(root) / "state", allowed_roots=[root]
            )
            with self.assertRaisesRegex(RuntimeErrorState, "COMMAND_REQUIRED"):
                runtime.run_one(
                    ticket_id="unused", source_id="SRC-unset",
                    command="", cwd=root,
                )
            with self.assertRaisesRegex(RuntimeErrorState, "COMMAND_REQUIRED"):
                runtime.run_one(
                    ticket_id="unused", source_id="SRC-unset",
                    command=None, cwd=root,
                )


if __name__ == "__main__":
    unittest.main()
