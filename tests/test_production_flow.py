import json
import sys
import tempfile
import unittest
from pathlib import Path

from runtime.production_orchestrator import run_production_flow
from runtime.source_removal_gate import check_source_removal_readiness
from runtime.station_engine import StationHandlerResult, StationRegistry
from sovereign_runtime import RuntimeErrorState, SovereignRuntime, sha256_file


class ProductionFlowTests(unittest.TestCase):
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
        self.source_path.write_text("production input", encoding="utf-8")
        self.source = self.runtime.intake_local(self.source_path)["source"]
        self.ticket = self.runtime.create_ticket(
            self.source["source_id"], "ONE_RUN", "TERMINAL_EXECUTION"
        )
        self.runtime.authorize_ticket(self.ticket["ticket_id"], "TEST_APPROVAL")
        self.productive_evidence_id = "EVD-PRODUCTIVE-TEST"
        evidence_path = self.runtime.paths["evidence"] / f"{self.productive_evidence_id}.json"
        evidence_path.write_text(
            json.dumps(
                {
                    "evidence_id": self.productive_evidence_id,
                    "source_id": self.source["source_id"],
                    "state": "PASS",
                }
            ),
            encoding="utf-8",
        )
        self.second_payload_path = self.allowed / "second-unit.txt"
        self.second_payload_path.write_text("second productive unit", encoding="utf-8")
        self.second_evidence_id = "EVD-PRODUCTIVE-SECOND"
        (self.runtime.paths["evidence"] / f"{self.second_evidence_id}.json").write_text(
            json.dumps(
                {
                    "evidence_id": self.second_evidence_id,
                    "source_id": self.source["source_id"],
                    "state": "PASS",
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def request(self):
        return {
            "source_path": str(self.source_path),
            "ticket_id": self.ticket["ticket_id"],
            "workspace_id": "WS-PRODUCTION-TEST",
            "zone_id": "TEST",
            "agent_id": "TEST_AGENT",
            "runtime": {
                "required": True,
                "command": sys.executable,
                "args": ["-c", "print('production flow')"],
                "cwd": str(self.allowed),
                "timeout_seconds": 10,
            },
            "productive_units": [
                {
                    "unit_id": "UNIT-PRODUCTION-TEST",
                    "source_id": self.source["source_id"],
                    "domain": "test",
                    "unit_type": "text",
                    "payload_pointer": str(self.source_path),
                    "content_sha256": self.source["sha256"],
                    "evidence_id": self.productive_evidence_id,
                    "retrieval_point": "tests.production.flow",
                    "verification_state": "PASS",
                },
                {
                    "unit_id": "UNIT-PRODUCTION-SECOND",
                    "source_id": self.source["source_id"],
                    "domain": "test",
                    "unit_type": "text",
                    "payload_pointer": str(self.second_payload_path),
                    "content_sha256": sha256_file(self.second_payload_path),
                    "evidence_id": self.second_evidence_id,
                    "retrieval_point": "tests.production.second",
                    "verification_state": "PASS",
                },
            ],
        }

    def registry_with_first_six_stations(self):
        registry = StationRegistry()
        for station in range(1, 7):
            registry.register(
                station,
                lambda context: StationHandlerResult(
                    state="PASS",
                    operation=f"STATION_{context.station:02d}_TEST",
                    evidence={"station": context.station, "verified": True},
                ),
            )
        return registry

    def test_production_flow_verifies_and_settles_productive_unit(self):
        result = run_production_flow(
            self.request(),
            runtime=self.runtime,
            station_registry=self.registry_with_first_six_stations(),
        )

        self.assertTrue(result["success"], result)
        self.assertEqual(result["state"], "SETTLED")
        self.assertEqual(len(result["settlements"]), 2)
        for unit, settlement in zip(self.request()["productive_units"], result["settlements"]):
            repeated = self.runtime.settle(
                source_id=self.source["source_id"],
                unit_id=unit["unit_id"],
                domain=unit["domain"],
                payload_pointer=unit["payload_pointer"],
                sha256=unit["content_sha256"],
                evidence_id=unit["evidence_id"],
                retrieval_point=unit["retrieval_point"],
            )
            self.assertEqual(repeated["settlement_id"], settlement["settlement_id"])
        readiness = check_source_removal_readiness(
            self.runtime, self.source["source_id"]
        )
        self.assertTrue(readiness["eligible"], readiness)

    def test_production_flow_holds_when_any_station_handler_is_missing(self):
        registry = StationRegistry()
        result = run_production_flow(
            self.request(),
            runtime=self.runtime,
            station_registry=registry,
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["state"], "HOLD")
        self.assertEqual(result["pipeline"]["stopped_at"], 1)
        self.assertIn(
            "STATION_HANDLER_NOT_REGISTERED",
            result["pipeline"]["receipts"][0]["errors"],
        )

    def test_source_removal_readiness_detects_changed_source_bytes(self):
        result = run_production_flow(
            self.request(),
            runtime=self.runtime,
            station_registry=self.registry_with_first_six_stations(),
        )
        self.assertTrue(result["success"], result)

        self.source_path.write_text("changed after settlement", encoding="utf-8")
        readiness = check_source_removal_readiness(
            self.runtime, self.source["source_id"]
        )

        self.assertFalse(readiness["eligible"])
        self.assertIn("SOURCE_CONTENT_CHANGED", readiness["blockers"])
        self.assertIn(
            "SETTLED_UNIT_READBACK_FAILED:UNIT-PRODUCTION-TEST",
            readiness["blockers"],
        )

    def test_production_flow_does_not_settle_when_unit_payload_hash_mismatches(self):
        request = self.request()
        request["productive_units"][0]["content_sha256"] = "0" * 64

        result = run_production_flow(
            request,
            runtime=self.runtime,
            station_registry=self.registry_with_first_six_stations(),
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["state"], "NOT_VERIFIED")
        self.assertEqual(result["pipeline"]["stopped_at"], 7)
        self.assertEqual(result["settlements"], [])
        self.assertEqual(self.runtime.current(self.source["source_id"])["current_station"], "STATION_07")

    def test_station_completion_cannot_use_evidence_for_another_station(self):
        run = self.runtime.run_one(
            ticket_id=self.ticket["ticket_id"],
            source_id=self.source["source_id"],
            command=sys.executable,
            args=["-c", "print('run')"],
            cwd=self.allowed,
            timeout_seconds=10,
        )
        self.assertEqual(run["final_state"], "PASS", run["errors"])
        with self.assertRaisesRegex(RuntimeErrorState, "STATION_01_REQUIRES_RUNNING_STATE"):
            self.runtime.transition_station(
                source_id=self.source["source_id"],
                station=1,
                state="PASS",
                operation="STATION_01_DIRECT_PASS",
                evidence_id=run["evidence_id"],
                run_id=run["run_id"],
                ticket_id=self.ticket["ticket_id"],
            )
        self.runtime.transition_station(
            source_id=self.source["source_id"],
            station=1,
            state="RUNNING",
            operation="STATION_01_STARTED",
            run_id=run["run_id"],
            ticket_id=self.ticket["ticket_id"],
        )
        wrong_station_evidence = {
            "evidence_id": "EVD-WRONG-STATION",
            "source_id": self.source["source_id"],
            "station": 2,
            "station_id": "STATION_02",
            "ticket_id": self.ticket["ticket_id"],
            "run_id": run["run_id"],
            "state": "PASS",
        }
        evidence_path = (
            self.runtime.paths["evidence"] / "EVD-WRONG-STATION.json"
        )
        evidence_path.write_text(json.dumps(wrong_station_evidence), encoding="utf-8")
        with self.assertRaisesRegex(
            RuntimeErrorState, "STATION_EVIDENCE_BINDING_MISMATCH"
        ):
            self.runtime.transition_station(
                source_id=self.source["source_id"],
                station=1,
                state="PASS",
                operation="STATION_01_FORGED_PASS",
                evidence_id="EVD-WRONG-STATION",
                evidence_sha256=sha256_file(evidence_path),
                run_id=run["run_id"],
                ticket_id=self.ticket["ticket_id"],
            )


if __name__ == "__main__":
    unittest.main()
