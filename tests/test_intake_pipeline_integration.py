"""End-to-end identity, evidence and fail-closed station integration fixtures."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from runtime.production_orchestrator import run_production_flow
from runtime.station_engine import StationHandlerResult, StationRegistry
from sovereign_runtime import SovereignRuntime, sha256_file


class IntakeStationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.allowed = self.root / "allowed"
        self.allowed.mkdir()
        self.source_path = self.allowed / "عينة.txt"
        self.source_path.write_text("نص عربي قابل لإعادة الاستخدام.", encoding="utf-8")
        self.runtime = SovereignRuntime(self.root / "runtime", allowed_roots=[self.allowed])
        self.source = self.runtime.intake_local(self.source_path)["source"]
        self.ticket = self.runtime.create_ticket(
            self.source["source_id"], "ONE_RUN", "TERMINAL_EXECUTION"
        )
        self.runtime.authorize_ticket(self.ticket["ticket_id"], "ISOLATED_TEST")
        self.evidence_id = "EVD-INTEGRATION-UNIT"
        (self.runtime.paths["evidence"] / (self.evidence_id + ".json")).write_text(
            json.dumps({
                "evidence_id": self.evidence_id,
                "source_id": self.source["source_id"],
                "state": "PASS",
            }), encoding="utf-8"
        )

    def request(self):
        return {
            "source_path": str(self.source_path),
            "ticket_id": self.ticket["ticket_id"],
            "workspace_id": "WS-ISOLATED",
            "agent_id": "TEST_AGENT",
            "runtime": {
                "required": True,
                "command": sys.executable,
                "args": ["-c", "print('isolated test')"],
                "cwd": str(self.allowed),
                "timeout_seconds": 10,
            },
            "productive_units": [{
                "unit_id": "UNIT-ISOLATED-ARABIC",
                "source_id": self.source["source_id"],
                "domain": "test",
                "unit_type": "text",
                "payload_pointer": str(self.source_path),
                "content_sha256": sha256_file(self.source_path),
                "evidence_id": self.evidence_id,
                "retrieval_point": "tests.integration.arabic",
                "verification_state": "PASS",
            }],
        }

    @staticmethod
    def registry(*, stop_at=None, empty_evidence_at=None):
        registry = StationRegistry()
        for station in range(1, 7):
            def handler(context, number=station):
                return StationHandlerResult(
                    state="HOLD" if number == stop_at else "PASS",
                    operation=f"STATION_{number:02d}_ISOLATED_TEST",
                    evidence={} if number == empty_evidence_at else {
                        "station": number,
                        "source_id": context.source_id,
                        "ticket_id": context.ticket_id,
                        "run_id": context.run_id,
                        "packet_source_id": context.metadata["normalized_packet"]["source_id"],
                    },
                )
            registry.register(station, handler)
        return registry

    def test_all_seven_stations_keep_source_ticket_run_and_evidence(self):
        result = run_production_flow(
            self.request(), runtime=self.runtime, station_registry=self.registry()
        )
        self.assertTrue(result["success"], result)
        self.assertEqual(result["state"], "SETTLED")
        self.assertEqual(result["normalized_packet"]["source_id"], self.source["source_id"])
        self.assertEqual(result["normalized_packet"]["transit_id"], self.source["transit_id"])
        self.assertEqual(result["normalized_packet"]["source_sha256"], self.source["sha256"])
        self.assertEqual(result["pipeline"]["completed_stations"], list(range(1, 8)))
        self.assertEqual(len(result["settlements"]), 1)
        seen = set()
        for receipt in result["pipeline"]["receipts"]:
            self.assertEqual(receipt["state"], "PASS")
            self.assertEqual(receipt["source_id"], self.source["source_id"])
            self.assertEqual(receipt["transit_id"], self.source["transit_id"])
            self.assertEqual(receipt["ticket_id"], self.ticket["ticket_id"])
            self.assertEqual(receipt["run_id"], result["run_id"])
            self.assertTrue(receipt["readback_verified"])
            self.assertTrue(receipt["receipt_readback_verified"])
            evidence = json.loads(Path(receipt["evidence_path"]).read_text(encoding="utf-8"))
            self.assertEqual(evidence["source_id"], self.source["source_id"])
            self.assertEqual(evidence["transit_id"], self.source["transit_id"])
            self.assertEqual(evidence["ticket_id"], self.ticket["ticket_id"])
            self.assertEqual(evidence["run_id"], result["run_id"])
            seen.add(receipt["evidence_id"])
        self.assertEqual(len(seen), 7)
        self.assertTrue(self.source_path.is_file())

    def test_station_failure_stops_and_never_settles(self):
        result = run_production_flow(
            self.request(), runtime=self.runtime, station_registry=self.registry(stop_at=3)
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["state"], "HOLD")
        self.assertEqual(result["pipeline"]["completed_stations"], [1, 2])
        self.assertEqual(result["pipeline"]["stopped_at"], 3)
        self.assertEqual(len(result["pipeline"]["receipts"]), 3)
        self.assertEqual(result["settlements"], [])
        self.assertTrue(self.source_path.is_file())

    def test_pass_without_evidence_is_rejected(self):
        result = run_production_flow(
            self.request(), runtime=self.runtime,
            station_registry=self.registry(empty_evidence_at=1),
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["state"], "NOT_VERIFIED")
        self.assertEqual(result["pipeline"]["stopped_at"], 1)
        self.assertIn("PASS_REQUIRES_EVIDENCE", result["pipeline"]["receipts"][0]["errors"])
        self.assertEqual(result["settlements"], [])
        self.assertTrue(self.source_path.is_file())

    def test_unapproved_ticket_blocks_before_execution(self):
        request = self.request()
        unapproved = self.runtime.create_ticket(
            self.source["source_id"], "ONE_RUN", "TERMINAL_EXECUTION"
        )
        request["ticket_id"] = unapproved["ticket_id"]
        result = run_production_flow(
            request, runtime=self.runtime, station_registry=self.registry()
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["state"], "HOLD")
        self.assertIn("TICKET_NOT_AUTHORIZED", result["blockers"])
        self.assertNotIn("pipeline", result)
        self.assertTrue(self.source_path.is_file())


if __name__ == "__main__":
    unittest.main()
