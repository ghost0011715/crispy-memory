import sys
import tempfile
import unittest
from pathlib import Path

from runtime.station_engine import (
    StationEngine,
    StationHandlerResult,
    StationPipeline,
    StationRegistry,
)
from runtime.station07_settlement_gate import station07_settlement_gate
from sovereign_runtime import RuntimeErrorState, SovereignRuntime


class SovereignRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.allowed = self.root / "allowed"
        self.allowed.mkdir()
        self.runtime = SovereignRuntime(
            self.root / "runtime",
            allowed_roots=[self.allowed],
        )
        self.source_path = self.allowed / "system.zip"
        self.source_path.write_bytes(b"source-data")

    def tearDown(self):
        self.temporary.cleanup()

    def test_nova_registers_source_and_new_system_transit_id(self):
        intake = self.runtime.intake_local(self.source_path)
        source, ticket = intake["source"], intake["ticket"]

        self.assertEqual(source["transit_id"], "NewSystem-000-000-001")
        self.assertEqual(source["source_action"], "READ_ONLY")
        self.assertEqual(ticket["status"], "CREATED")
        self.assertEqual(self.runtime.current(source["source_id"])["current_state"], "OBSERVED")

    def test_authorization_is_required_before_run(self):
        intake = self.runtime.intake_local(self.source_path)
        ticket = self.runtime.create_ticket(
            intake["source"]["source_id"], "ONE_RUN", "TERMINAL_EXECUTION"
        )
        receipt = self.runtime.run_one(
            ticket_id=ticket["ticket_id"],
            source_id=intake["source"]["source_id"],
            command=sys.executable,
            args=["-c", "print('must not run')"],
            cwd=self.allowed,
        )

        self.assertEqual(receipt["final_state"], "HOLD")
        self.assertIn("TICKET_NOT_AUTHORIZED", receipt["errors"])

    def test_read_only_ticket_cannot_authorize_terminal_execution(self):
        intake = self.runtime.intake_local(self.source_path)
        source, ticket = intake["source"], intake["ticket"]
        self.runtime.authorize_ticket(ticket["ticket_id"], "USER")

        receipt = self.runtime.run_one(
            ticket_id=ticket["ticket_id"],
            source_id=source["source_id"],
            command=sys.executable,
            args=["-c", "print('must not run')"],
            cwd=self.allowed,
        )

        self.assertEqual(receipt["final_state"], "HOLD")
        self.assertIn("TICKET_OPERATION_MISMATCH", receipt["errors"])

    def test_run_and_seven_station_settlement_preserve_evidence(self):
        intake = self.runtime.intake_local(self.source_path)
        source = intake["source"]
        ticket = self.runtime.create_ticket(
            source["source_id"], "ONE_RUN", "TERMINAL_EXECUTION"
        )
        self.runtime.authorize_ticket(ticket["ticket_id"], "USER_EXPLICIT_APPROVAL")
        receipt = self.runtime.run_one(
            ticket_id=ticket["ticket_id"],
            source_id=source["source_id"],
            command=sys.executable,
            args=["-c", "print('runtime verified')"],
            cwd=self.allowed,
            timeout_seconds=10,
            workspace_id="WS-TEST",
            zone_id="CODE_ZONE",
        )

        self.assertEqual(receipt["final_state"], "PASS", receipt["errors"])
        self.assertTrue(receipt["readback_verified"])
        self.assertIn("runtime verified", Path(receipt["evidence_path"]).read_text(encoding="utf-8"))
        self.assertEqual(self.runtime.current(source["source_id"])["current_station"], "STATION_01")

        registry = StationRegistry()
        for station in range(2, 7):
            registry.register(
                station,
                lambda context: StationHandlerResult(
                    state="PASS",
                    operation=f"STATION_{context.station:02d}_TEST",
                    evidence={"station": context.station, "verified": True},
                ),
            )
        productive_unit = {
            "unit_id": "UNIT-001",
            "source_id": source["source_id"],
            "domain": "code",
            "unit_type": "source",
            "payload_pointer": str(self.source_path),
            "content_sha256": source["sha256"],
            "evidence_id": receipt["evidence_id"],
            "retrieval_point": "code.system.test",
            "verification_state": "PASS",
        }
        registry.register(7, station07_settlement_gate(self.runtime))
        pipeline = StationPipeline(StationEngine(self.runtime, registry)).run(
            source_id=source["source_id"],
            ticket_id=ticket["ticket_id"],
            run_id=receipt["run_id"],
            workspace_id="WS-TEST",
            zone_id="CODE_ZONE",
            agent_id="SHADOW",
            start_station=2,
            metadata={"productive_units": [productive_unit]},
        )
        self.assertEqual(pipeline["state"], "PASS", pipeline)

        settled = self.runtime.settle(
            source_id=source["source_id"],
            unit_id="UNIT-001",
            domain="code",
            payload_pointer=str(self.source_path),
            sha256=source["sha256"],
            evidence_id=receipt["evidence_id"],
            retrieval_point="code.system.test",
        )
        self.assertEqual(settled["state"], "SETTLED")
        self.assertEqual(self.runtime.current(source["source_id"])["current_state"], "SETTLED")
        self.assertEqual(self.runtime.events(source["source_id"])[-1]["operation"], "WAREHOUSE_SETTLEMENT")

    def test_run_uses_a_shadow_copy_not_the_source_workspace(self):
        intake = self.runtime.intake_local(self.source_path)
        source = intake["source"]
        ticket = self.runtime.create_ticket(
            source["source_id"], "ONE_RUN", "TERMINAL_EXECUTION"
        )
        self.runtime.authorize_ticket(ticket["ticket_id"], "USER_EXPLICIT_APPROVAL")
        receipt = self.runtime.run_one(
            ticket_id=ticket["ticket_id"],
            source_id=source["source_id"],
            command=sys.executable,
            args=["-c", "from pathlib import Path; Path('relative-result.txt').write_text('shadow')"],
            cwd=self.allowed,
            timeout_seconds=10,
        )

        self.assertEqual(receipt["final_state"], "PASS", receipt["errors"])
        self.assertFalse((self.allowed / "relative-result.txt").exists())
        self.assertFalse(Path(receipt["shadow_workspace"]).exists())

    def test_station_cannot_skip_order_or_pass_without_evidence(self):
        intake = self.runtime.intake_local(self.source_path)
        source = intake["source"]
        with self.assertRaisesRegex(RuntimeErrorState, "STATION_01_REQUIRES_ONE_RUN_PASS"):
            self.runtime.transition_station(
                source_id=source["source_id"],
                station=1,
                state="PASS",
                operation="FORGED_PASS",
                evidence_id="missing",
            )

    def test_settlement_rejects_tampered_evidence(self):
        intake = self.runtime.intake_local(self.source_path)
        source = intake["source"]
        ticket = self.runtime.create_ticket(
            source["source_id"], "ONE_RUN", "TERMINAL_EXECUTION"
        )
        self.runtime.authorize_ticket(ticket["ticket_id"], "USER")
        receipt = self.runtime.run_one(
            ticket_id=ticket["ticket_id"],
            source_id=source["source_id"],
            command=sys.executable,
            args=["-c", "print('ok')"],
            cwd=self.allowed,
        )
        if receipt["final_state"] != "PASS":
            self.fail(receipt["errors"])
        registry = StationRegistry()
        for station in range(2, 8):
            registry.register(
                station,
                lambda context: StationHandlerResult(
                    state="PASS",
                    operation=f"STATION_{context.station:02d}",
                    evidence={"station": context.station},
                ),
            )
        pipeline = StationPipeline(StationEngine(self.runtime, registry)).run(
            source_id=source["source_id"],
            ticket_id=ticket["ticket_id"],
            run_id=receipt["run_id"],
            workspace_id="WS-TEST",
            agent_id="SHADOW",
            start_station=2,
        )
        self.assertEqual(pipeline["state"], "PASS", pipeline)
        Path(receipt["evidence_path"]).write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeErrorState, "EVIDENCE_HASH_MISMATCH"):
            self.runtime.settle(
                source_id=source["source_id"],
                unit_id="UNIT-1",
                domain="code",
                payload_pointer=str(self.source_path),
                sha256=source["sha256"],
                evidence_id=receipt["evidence_id"],
                retrieval_point="code.test",
            )

    def test_source_hash_is_refreshed_for_changed_file(self):
        first = self.runtime.intake_local(self.source_path)["source"]
        self.source_path.write_bytes(b"updated-content")
        second = self.runtime.intake_local(self.source_path)["source"]

        self.assertEqual(first["source_id"], second["source_id"])
        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertEqual(second["size_bytes"], len(b"updated-content"))

    def test_outside_path_is_rejected(self):
        outside = self.root / "outside.txt"
        outside.write_text("no", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeErrorState, "PATH_NOT_ALLOWED"):
            self.runtime.intake_local(outside)

    def test_transit_prefix_separates_container_format_from_system_kind(self):
        self.assertEqual(SovereignRuntime._transit_prefix(".zip"), "NewSystem")
        self.assertEqual(SovereignRuntime._transit_prefix(".pdf"), "Pdf")

    def test_state_corruption_is_not_silently_reset(self):
        self.runtime.paths["sources"].write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeErrorState, "STATE_FILE_CORRUPT"):
            self.runtime.get_source("SRC-MISSING")


if __name__ == "__main__":
    unittest.main()
