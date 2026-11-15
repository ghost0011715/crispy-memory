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
        self.assertEqual(result["settlements"], [])


if __name__ == "__main__":
    unittest.main()
