import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from runtime.production_orchestrator import run_production_flow
from runtime.station_engine import (
    StationContext,
    StationEngine,
    StationHandlerResult,
    StationRegistry,
    file_readback_handler,
)
from sovereign_runtime import SovereignRuntime


class ProductionOrchestratorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.allowed = self.root / "allowed"
        self.allowed.mkdir()
        self.runtime = SovereignRuntime(
            self.root / "runtime",
            allowed_roots=[self.allowed],
        )
        self.source_path = self.allowed / "source.txt"
        self.source_path.write_text("isolated station integration input\n", encoding="utf-8")
        registration = self.runtime.intake_local(self.source_path)
        self.source = registration["source"]
        self.ticket = self.runtime.create_ticket(
            self.source["source_id"], "ONE_RUN", "TERMINAL_EXECUTION"
        )
        self.runtime.authorize_ticket(self.ticket["ticket_id"], "ISOLATED_TEST")

        baseline = self.runtime.run_one(
            ticket_id=self.ticket["ticket_id"],
            source_id=self.source["source_id"],
            command=sys.executable,
            args=["-c", "print('isolated baseline')"],
            cwd=self.allowed,
            timeout_seconds=10,
        )
        self.assertEqual(baseline["final_state"], "PASS", baseline["errors"])

        evidence_registry = StationRegistry()
        evidence_registry.register(1, file_readback_handler(self.runtime))
        evidence = StationEngine(self.runtime, evidence_registry).execute(
            StationContext(
                source_id=self.source["source_id"],
                station=1,
                ticket_id=self.ticket["ticket_id"],
                run_id=baseline["run_id"],
                workspace_id="WS-ISOLATED-TEST",
                zone_id="TEST",
                agent_id="TEST",
                input_ref=str(self.source_path),
            )
        )
        self.assertEqual(evidence["state"], "PASS", evidence["errors"])
        self.unit = {
            "unit_id": "UNIT-ISOLATED-SOURCE",
            "source_id": self.source["source_id"],
            "domain": "test",
            "unit_type": "text",
            "payload_pointer": str(self.source_path),
            "content_sha256": self.source["sha256"],
            "evidence_id": evidence["evidence_id"],
            "retrieval_point": "test.source.readback",
            "verification_state": "PASS",
        }

    def tearDown(self):
        self.temporary.cleanup()

    def registry(self, *, stop_at=None, no_evidence_at=None):
        registry = StationRegistry()
        called = []

        for station in range(1, 7):
            def handler(context, registered_station=station):
                called.append(registered_station)
                state = "HOLD" if registered_station == stop_at else "PASS"
                evidence = (
                    {}
                    if registered_station == no_evidence_at
                    else {
                        "source_id": context.source_id,
                        "transit_id": self.source["transit_id"],
                        "ticket_id": context.ticket_id,
                        "station": registered_station,
                        "source_sha256": self.source["sha256"],
                    }
                )
                return StationHandlerResult(
                    state=state,
                    operation=f"STATION_{registered_station:02d}_TEST",
                    evidence=evidence,
                )

            registry.register(station, handler)
        return registry, called

    def request(self):
        return {
            "source_path": str(self.source_path),
            "ticket_id": self.ticket["ticket_id"],
            "workspace_id": "WS-ISOLATED-TEST",
            "agent_id": "TEST_AGENT",
            "productive_units": [self.unit],
            "runtime": {
                "required": True,
                "command": sys.executable,
                "args": ["-c", "print('isolated production flow')"],
                "cwd": str(self.allowed),
                "timeout_seconds": 10,
            },
        }

    def assert_station_receipt_evidence(self, receipt):
        evidence_bytes = Path(receipt["evidence_path"]).read_bytes()
        evidence = json.loads(evidence_bytes)
        self.assertEqual(
            hashlib.sha256(evidence_bytes).hexdigest(),
            receipt["evidence_sha256"],
        )
        self.assertEqual(evidence["evidence_id"], receipt["evidence_id"])
        self.assertEqual(evidence["source_id"], self.source["source_id"])
        self.assertEqual(evidence["transit_id"], self.source["transit_id"])
        self.assertEqual(evidence["ticket_id"], self.ticket["ticket_id"])
        self.assertEqual(evidence["station"], receipt["station"])
        self.assertEqual(evidence["state"], receipt["state"])
        self.assertTrue(evidence["evidence"])

        saved_receipt = json.loads(
            Path(receipt["receipt_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(saved_receipt, receipt)
        journal_events = [
            event
            for event in self.runtime.events(self.source["source_id"])
            if event.get("evidence_id") == receipt["evidence_id"]
        ]
        self.assertEqual(len(journal_events), 1)
        event = journal_events[0]
        self.assertEqual(event["source_id"], self.source["source_id"])
        self.assertEqual(event["transit_id"], self.source["transit_id"])
        self.assertEqual(event["ticket_id"], self.ticket["ticket_id"])
        self.assertEqual(event["to_station"], receipt["station_id"])
        self.assertEqual(event["evidence_sha256"], receipt["evidence_sha256"])

    def test_intake_to_station_seven_preserves_identity_ticket_and_evidence(self):
        registry, called = self.registry()

        result = run_production_flow(
            self.request(),
            runtime=self.runtime,
            station_registry=registry,
        )

        self.assertTrue(result["success"], result.get("blockers"))
        self.assertEqual(result["state"], "SETTLED")
        self.assertEqual(result["source_id"], self.source["source_id"])
        self.assertEqual(result["transit_id"], self.source["transit_id"])
        self.assertEqual(result["ticket_id"], self.ticket["ticket_id"])
        self.assertEqual(
            result["normalized_packet"]["source_id"], self.source["source_id"]
        )
        self.assertEqual(
            result["normalized_packet"]["transit_id"], self.source["transit_id"]
        )
        normalization_events = [
            event
            for event in self.runtime.events(self.source["source_id"])
            if event.get("operation") == "READABLE_NORMALIZATION_PASS"
        ]
        self.assertEqual(len(normalization_events), 1)
        normalization_ticket = self.runtime.get_ticket(
            normalization_events[0]["ticket_id"]
        )
        self.assertIsNotNone(normalization_ticket)
        self.assertEqual(
            normalization_ticket["source_id"], self.source["source_id"]
        )
        self.assertEqual(
            normalization_ticket["operation"], "READ_ONLY_INSPECTION"
        )
        self.assertEqual(
            normalization_ticket["capability"], "FILESYSTEM_INSPECTION"
        )
        self.assertEqual(called, list(range(1, 7)))
        pipeline = result["pipeline"]
        self.assertEqual(pipeline["completed_stations"], list(range(1, 8)))
        self.assertEqual(len(pipeline["receipts"]), 7)
        for station, receipt in enumerate(pipeline["receipts"], start=1):
            self.assertEqual(receipt["station"], station)
            self.assertEqual(receipt["source_id"], self.source["source_id"])
            self.assertEqual(receipt["transit_id"], self.source["transit_id"])
            self.assertEqual(receipt["ticket_id"], self.ticket["ticket_id"])
            self.assertTrue(receipt["readback_verified"])
            self.assertTrue(receipt["receipt_readback_verified"])
            self.assert_station_receipt_evidence(receipt)
        self.assertEqual(
            self.runtime.current(self.source["source_id"])["current_station"],
            "WAREHOUSE_35",
        )
        self.assertEqual(len(result["settlements"]), 1)

    def test_pipeline_stops_on_first_failure(self):
        registry, called = self.registry(stop_at=3)

        result = run_production_flow(
            self.request(),
            runtime=self.runtime,
            station_registry=registry,
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["state"], "HOLD")
        self.assertEqual(result["pipeline"]["stopped_at"], 3)
        self.assertEqual(result["pipeline"]["completed_stations"], [1, 2])
        self.assertEqual(called, [1, 2, 3])
        for receipt in result["pipeline"]["receipts"]:
            self.assert_station_receipt_evidence(receipt)
        self.assertEqual(result["settlements"], [])

    def test_pass_without_evidence_is_downgraded_and_stops_pipeline(self):
        registry, called = self.registry(no_evidence_at=2)

        result = run_production_flow(
            self.request(),
            runtime=self.runtime,
            station_registry=registry,
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["state"], "NOT_VERIFIED")
        self.assertEqual(result["pipeline"]["stopped_at"], 2)
        self.assertEqual(called, [1, 2])
        self.assertIn(
            "PASS_REQUIRES_EVIDENCE",
            result["pipeline"]["receipts"][-1]["errors"],
        )
        failed_receipt = result["pipeline"]["receipts"][-1]
        self.assertEqual(failed_receipt["state"], "NOT_VERIFIED")
        self.assert_station_receipt_evidence(failed_receipt)
        self.assertEqual(result["settlements"], [])

    def test_unauthorized_ticket_is_blocked_before_normalization_and_stations(self):
        pending_ticket = self.runtime.create_ticket(
            self.source["source_id"], "ONE_RUN", "TERMINAL_EXECUTION"
        )
        request = self.request()
        request["ticket_id"] = pending_ticket["ticket_id"]
        registry, called = self.registry()

        result = run_production_flow(
            request,
            runtime=self.runtime,
            station_registry=registry,
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["state"], "HOLD")
        self.assertIn("TICKET_NOT_AUTHORIZED", result["blockers"])
        self.assertEqual(called, [])
        self.assertNotIn("pipeline", result)
        self.assertFalse(
            any(
                event.get("operation") == "READABLE_NORMALIZATION_STARTED"
                for event in self.runtime.events(self.source["source_id"])
            )
        )


if __name__ == "__main__":
    unittest.main()
