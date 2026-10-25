import sys
import tempfile
import unittest
from pathlib import Path

from runtime.station_engine import (
    StationContext,
    StationEngine,
    StationHandlerResult,
    StationPipeline,
    StationRegistry,
    file_readback_handler,
)
from runtime.station07_settlement_gate import station07_settlement_gate
from sovereign_runtime import RuntimeErrorState, SovereignRuntime


class StationEngineTests(unittest.TestCase):
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
        self.source_path.write_text("station pipeline input", encoding="utf-8")
        registered = self.runtime.intake_local(self.source_path)
        self.source = registered["source"]
        self.read_only_ticket = registered["ticket"]
        self.runtime.authorize_ticket(self.read_only_ticket["ticket_id"], "TEST_READ_ONLY_APPROVAL")
        self.ticket = self.runtime.create_ticket(
            self.source["source_id"], "ONE_RUN", "TERMINAL_EXECUTION"
        )
        self.runtime.authorize_ticket(self.ticket["ticket_id"], "TEST_APPROVAL")
        self.one_run = self.runtime.run_one(
            ticket_id=self.ticket["ticket_id"],
            source_id=self.source["source_id"],
            command=sys.executable,
            args=["-c", "print('station engine test')"],
            cwd=self.allowed,
            timeout_seconds=10,
        )
        self.assertEqual(self.one_run["final_state"], "PASS", self.one_run["errors"])

    def tearDown(self):
        self.temporary.cleanup()

    def context(self, station=1):
        return StationContext(
            source_id=self.source["source_id"],
            station=station,
            ticket_id=self.ticket["ticket_id"],
            run_id=self.one_run["run_id"],
            workspace_id="WS-TEST",
            zone_id="TEST_ZONE",
            agent_id="TEST_AGENT",
            input_ref=str(self.source_path),
        )

    def test_unregistered_handler_holds_and_records_evidence_and_receipt(self):
        engine = StationEngine(self.runtime, StationRegistry())

        receipt = engine.execute(self.context())

        self.assertEqual(receipt["state"], "HOLD")
        self.assertIn("STATION_HANDLER_NOT_REGISTERED", receipt["errors"])
        self.assertTrue(receipt["readback_verified"])
        self.assertTrue(receipt["receipt_readback_verified"])
        self.assertTrue(Path(receipt["evidence_path"]).is_file())
        self.assertTrue(Path(receipt["receipt_path"]).is_file())
        self.assertEqual(
            self.runtime.current(self.source["source_id"])["current_state"], "HOLD"
        )

    def test_pipeline_runs_registered_handlers_in_order_with_distinct_evidence(self):
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
        unit = {
            "unit_id": "UNIT-STATION-TEST",
            "source_id": self.source["source_id"],
            "domain": "test",
            "unit_type": "text",
            "payload_pointer": str(self.source_path),
            "content_sha256": self.source["sha256"],
            "evidence_id": self.one_run["evidence_id"],
            "retrieval_point": "test.station.pipeline",
            "verification_state": "PASS",
        }
        registry.register(7, station07_settlement_gate(self.runtime))
        pipeline = StationPipeline(StationEngine(self.runtime, registry))

        result = pipeline.run(
            source_id=self.source["source_id"],
            ticket_id=self.ticket["ticket_id"],
            run_id=self.one_run["run_id"],
            workspace_id="WS-TEST",
            zone_id="TEST_ZONE",
            agent_id="TEST_AGENT",
            input_ref=str(self.source_path),
            metadata={"productive_units": [unit]},
        )

        self.assertEqual(result["state"], "PASS")
        self.assertEqual(result["completed_stations"], list(range(1, 8)))
        evidence_ids = [item["evidence_id"] for item in result["receipts"]]
        self.assertEqual(len(set(evidence_ids)), 7)
        self.assertTrue(all(item["readback_verified"] for item in result["receipts"]))
        self.assertEqual(
            self.runtime.current(self.source["source_id"])["current_station"],
            "STATION_07",
        )
        settled = self.runtime.settle(
            source_id=self.source["source_id"],
            unit_id=unit["unit_id"],
            domain=unit["domain"],
            payload_pointer=unit["payload_pointer"],
            sha256=unit["content_sha256"],
            evidence_id=unit["evidence_id"],
            retrieval_point=unit["retrieval_point"],
        )
        self.assertEqual(settled["state"], "SETTLED")

    def test_pipeline_stops_at_first_non_pass(self):
        registry = StationRegistry()
        called = []
        for station in range(1, 8):
            def handler(context, registered_station=station):
                called.append(registered_station)
                return StationHandlerResult(
                    state="HOLD" if registered_station == 3 else "PASS",
                    operation=f"STATION_{registered_station:02d}_TEST",
                    evidence={"station": registered_station},
                )

            registry.register(station, handler)
        result = StationPipeline(StationEngine(self.runtime, registry)).run(
            source_id=self.source["source_id"],
            ticket_id=self.ticket["ticket_id"],
            run_id=self.one_run["run_id"],
            workspace_id="WS-TEST",
            agent_id="TEST_AGENT",
            input_ref=str(self.source_path),
        )

        self.assertEqual(result["state"], "HOLD")
        self.assertEqual(result["completed_stations"], [1, 2])
        self.assertEqual(result["stopped_at"], 3)
        self.assertEqual(called, [1, 2, 3])

    def test_file_readback_handler_records_hash_evidence(self):
        registry = StationRegistry()
        registry.register(1, file_readback_handler(self.runtime))
        context = self.context()
        context.input_ref = None
        receipt = StationEngine(self.runtime, registry).execute(context)

        self.assertEqual(receipt["state"], "PASS")
        self.assertEqual(
            receipt["sha256_after"], self.source["sha256"]
        )
        self.assertTrue(receipt["readback_verified"])

    def test_registry_rejects_duplicate_and_invalid_station(self):
        registry = StationRegistry()
        handler = lambda context: StationHandlerResult(
            state="PASS", operation="TEST", evidence={"ok": True}
        )
        registry.register(1, handler)
        with self.assertRaisesRegex(RuntimeErrorState, "STATION_HANDLER_ALREADY_REGISTERED"):
            registry.register(1, handler)
        with self.assertRaisesRegex(RuntimeErrorState, "STATION_MUST_BE_1_TO_7"):
            registry.register(8, handler)

    def test_read_only_ticket_cannot_run_station_handlers(self):
        context = self.context()
        context.ticket_id = self.read_only_ticket["ticket_id"]
        engine = StationEngine(self.runtime, StationRegistry())

        with self.assertRaisesRegex(RuntimeErrorState, "TICKET_OPERATION_MISMATCH"):
            engine.execute(context)

        self.assertEqual(
            self.runtime.current(self.source["source_id"])["current_station"],
            "STATION_01",
        )


if __name__ == "__main__":
    unittest.main()
