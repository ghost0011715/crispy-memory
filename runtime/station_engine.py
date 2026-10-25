"""Evidence-backed, sequential seven-station execution."""

from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sovereign_runtime import RuntimeErrorState, SovereignRuntime, _read_json, _write_json_atomic, sha256_file


STATION_STATES = {
    "PASS",
    "FAIL",
    "HOLD",
    "NOT_VERIFIED",
    "NEEDS_CONTEXT",
    "MAINTENANCE_REQUIRED",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(12).upper()}"


@dataclass
class StationContext:
    source_id: str
    station: int
    ticket_id: str
    workspace_id: str
    agent_id: str
    run_id: str | None = None
    zone_id: str | None = None
    input_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StationHandlerResult:
    state: str
    operation: str
    evidence: dict[str, Any]
    output_ref: str | None = None
    sha256_before: str | None = None
    sha256_after: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


StationHandler = Callable[[StationContext], StationHandlerResult]


class StationRegistry:
    def __init__(self) -> None:
        self._handlers: dict[int, StationHandler] = {}
        self._lock = threading.RLock()

    def register(self, station: int, handler: StationHandler) -> None:
        if station in self._handlers:
            raise RuntimeErrorState(f"STATION_HANDLER_ALREADY_REGISTERED:{station}")
        self.replace(station, handler)

    def replace(self, station: int, handler: StationHandler) -> None:
        if type(station) is not int or not 1 <= station <= 7:
            raise RuntimeErrorState("STATION_MUST_BE_1_TO_7")
        if not callable(handler):
            raise TypeError("STATION_HANDLER_MUST_BE_CALLABLE")
        with self._lock:
            self._handlers[station] = handler

    def get(self, station: int) -> StationHandler | None:
        with self._lock:
            return self._handlers.get(station)

    def has(self, station: int) -> bool:
        return self.get(station) is not None

    def list(self) -> list[dict[str, Any]]:
        return [
            {
                "station": station,
                "station_id": f"STATION_{station:02d}",
                "registered": self.has(station),
            }
            for station in range(1, 8)
        ]


class StationEngine:
    def __init__(
        self, runtime: SovereignRuntime, registry: StationRegistry | None = None
    ) -> None:
        self.runtime = runtime
        self.registry = registry or StationRegistry()
        self.receipt_root = runtime.root / "stations" / "receipts"
        self.evidence_root = runtime.root / "stations" / "evidence"
        self.receipt_root.mkdir(parents=True, exist_ok=True)
        self.evidence_root.mkdir(parents=True, exist_ok=True)

    def execute(self, context: StationContext) -> dict[str, Any]:
        if type(context.station) is not int or not 1 <= context.station <= 7:
            raise RuntimeErrorState("STATION_MUST_BE_1_TO_7")
        source = self.runtime.get_source(context.source_id)
        if source is None:
            raise RuntimeErrorState("SOURCE_NOT_FOUND")
        ticket = self.runtime.get_ticket(context.ticket_id)
        if ticket is None:
            raise RuntimeErrorState("TICKET_NOT_FOUND")
        if ticket["source_id"] != context.source_id:
            raise RuntimeErrorState("SOURCE_TICKET_MISMATCH")
        if ticket["status"] != "AUTHORIZED":
            raise RuntimeErrorState("TICKET_NOT_AUTHORIZED")
        if not context.workspace_id.strip() or not context.agent_id.strip():
            raise RuntimeErrorState("WORKSPACE_AND_AGENT_REQUIRED")

        station_id = f"STATION_{context.station:02d}"
        started_at = _now()
        input_ref = context.input_ref or source["source_path"]
        self.runtime.transition_station(
            source_id=context.source_id,
            station=context.station,
            state="RUNNING",
            operation=f"{station_id}_STARTED",
            ticket_id=context.ticket_id,
            run_id=context.run_id,
            workspace_id=context.workspace_id,
            zone_id=context.zone_id,
            agent_id=context.agent_id,
        )

        handler = self.registry.get(context.station)
        if handler is None:
            result = StationHandlerResult(
                state="HOLD",
                operation="STATION_HANDLER_REQUIRED",
                evidence={
                    "reason": "STATION_HANDLER_NOT_REGISTERED",
                    "station": context.station,
                },
                errors=["STATION_HANDLER_NOT_REGISTERED"],
            )
        else:
            try:
                result = handler(context)
                if not isinstance(result, StationHandlerResult):
                    raise TypeError("HANDLER_MUST_RETURN_STATION_HANDLER_RESULT")
                if result.state not in STATION_STATES:
                    raise ValueError("INVALID_STATION_HANDLER_STATE")
                if result.state == "PASS" and not result.evidence:
                    result = StationHandlerResult(
                        state="NOT_VERIFIED",
                        operation=result.operation,
                        evidence={"reason": "PASS_WITHOUT_EVIDENCE"},
                        errors=[*result.errors, "PASS_REQUIRES_EVIDENCE"],
                    )
            except Exception as exc:
                result = StationHandlerResult(
                    state="FAIL",
                    operation=f"{station_id}_HANDLER_ERROR",
                    evidence={"exception": f"{type(exc).__name__}:{exc}"},
                    errors=[f"{type(exc).__name__}:{exc}"],
                )

        evidence_id = _id("EVD")
        evidence = {
            "evidence_id": evidence_id,
            "source_id": source["source_id"],
            "transit_id": source["transit_id"],
            "station": context.station,
            "station_id": station_id,
            "ticket_id": context.ticket_id,
            "run_id": context.run_id,
            "workspace_id": context.workspace_id,
            "zone_id": context.zone_id,
            "agent_id": context.agent_id,
            "state": result.state,
            "operation": result.operation,
            "evidence": result.evidence,
            "warnings": result.warnings,
            "errors": result.errors,
            "metadata": result.metadata,
            "captured_at": _now(),
        }
        evidence_path = self.evidence_root / f"{evidence_id}.json"
        _write_json_atomic(evidence_path, evidence)
        expected = _read_json(evidence_path, None)
        evidence_hash = sha256_file(evidence_path)
        readback_verified = expected == evidence
        final_state = result.state if readback_verified else "NOT_VERIFIED"
        errors = list(result.errors)
        if not readback_verified:
            errors.append("EVIDENCE_READBACK_FAILED")
        if final_state == "PASS" and not result.evidence:
            final_state = "NOT_VERIFIED"
            errors.append("PASS_REQUIRES_EVIDENCE")

        receipt = {
            "station_receipt_id": _id("STR"),
            "source_id": source["source_id"],
            "transit_id": source["transit_id"],
            "station": context.station,
            "station_id": station_id,
            "ticket_id": context.ticket_id,
            "run_id": context.run_id,
            "workspace_id": context.workspace_id,
            "zone_id": context.zone_id,
            "agent_id": context.agent_id,
            "operation": result.operation,
            "state": final_state,
            "input_ref": input_ref,
            "output_ref": result.output_ref,
            "evidence_id": evidence_id,
            "evidence_path": str(evidence_path),
            "evidence_sha256": evidence_hash,
            "readback_verified": readback_verified,
            "sha256_before": result.sha256_before or source["sha256"],
            "sha256_after": result.sha256_after or result.sha256_before or source["sha256"],
            "warnings": list(result.warnings),
            "errors": errors,
            "started_at": started_at,
            "ended_at": _now(),
        }
        receipt_path = (
            self.receipt_root
            / source["source_id"]
            / f"{station_id}_{receipt['station_receipt_id']}.json"
        )
        _write_json_atomic(receipt_path, receipt)

        try:
            self.runtime.transition_station(
                source_id=context.source_id,
                station=context.station,
                state=final_state,
                operation=result.operation,
                evidence_id=evidence_id,
                run_id=context.run_id,
                ticket_id=context.ticket_id,
                workspace_id=context.workspace_id,
                zone_id=context.zone_id,
                agent_id=context.agent_id,
                output_ref=result.output_ref or str(evidence_path),
            )
        except RuntimeErrorState as exc:
            receipt["state"] = "NOT_VERIFIED"
            receipt["errors"].append(f"FSX_TRANSITION_FAILED:{exc}")
            receipt["ended_at"] = _now()
            _write_json_atomic(receipt_path, receipt)
        receipt["receipt_path"] = str(receipt_path)
        return receipt


class StationPipeline:
    def __init__(self, engine: StationEngine) -> None:
        self.engine = engine

    def run(
        self,
        *,
        source_id: str,
        ticket_id: str,
        workspace_id: str,
        agent_id: str,
        run_id: str | None = None,
        zone_id: str | None = None,
        input_ref: str | None = None,
        start_station: int = 1,
        end_station: int = 7,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if type(start_station) is not int or type(end_station) is not int or not 1 <= start_station <= end_station <= 7:
            raise RuntimeErrorState("INVALID_STATION_RANGE")
        completed: list[int] = []
        receipts: list[dict[str, Any]] = []
        for station in range(start_station, end_station + 1):
            receipt = self.engine.execute(
                StationContext(
                    source_id=source_id,
                    station=station,
                    ticket_id=ticket_id,
                    run_id=run_id,
                    workspace_id=workspace_id,
                    zone_id=zone_id,
                    agent_id=agent_id,
                    input_ref=input_ref,
                    metadata=metadata or {},
                )
            )
            receipts.append(receipt)
            if receipt["state"] != "PASS":
                return {
                    "source_id": source_id,
                    "state": receipt["state"],
                    "completed_stations": completed,
                    "stopped_at": station,
                    "receipts": receipts,
                }
            completed.append(station)
        return {
            "source_id": source_id,
            "state": "PASS",
            "completed_stations": completed,
            "stopped_at": None,
            "receipts": receipts,
        }


def file_readback_handler(runtime: SovereignRuntime) -> StationHandler:
    def handle(context: StationContext) -> StationHandlerResult:
        if not context.input_ref:
            return StationHandlerResult(
                state="NEEDS_CONTEXT",
                operation="FILE_READBACK",
                evidence={"input_ref": None},
                errors=["INPUT_REF_REQUIRED"],
            )
        try:
            path = runtime.assert_allowed_path(context.input_ref)
            if not path.is_file():
                return StationHandlerResult(
                    state="HOLD",
                    operation="FILE_READBACK",
                    evidence={"input_ref": str(path), "is_file": False},
                    errors=["INPUT_NOT_FILE"],
                )
            stat = path.stat()
            digest = sha256_file(path)
            return StationHandlerResult(
                state="PASS",
                operation="FILE_READBACK",
                output_ref=str(path),
                sha256_after=digest,
                evidence={
                    "input_ref": str(path),
                    "exists": True,
                    "is_file": True,
                    "size_bytes": stat.st_size,
                    "sha256": digest,
                    "modified_at": datetime.fromtimestamp(
                        stat.st_mtime, timezone.utc
                    ).isoformat(),
                },
            )
        except (OSError, RuntimeErrorState) as exc:
            return StationHandlerResult(
                state="FAIL",
                operation="FILE_READBACK",
                evidence={"input_ref": context.input_ref, "error": str(exc)},
                errors=[f"{type(exc).__name__}:{exc}"],
            )

    return handle


def _unused_sleep_marker() -> None:
    time.sleep(0)
