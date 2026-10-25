"""Orchestrate intake, authorized execution, station verification, and settlement."""

from __future__ import annotations

from typing import Any

from runtime.productive_units import validate_productive_unit
from runtime.register_station07 import register_station07
from runtime.station_engine import StationPipeline, StationRegistry, StationEngine
from runtime.universal_intake import UniversalIntake
from sovereign_runtime import RuntimeErrorState, SovereignRuntime


def run_production_flow(
    request: dict[str, Any],
    *,
    runtime: SovereignRuntime,
    station_registry: StationRegistry,
    universal_intake: UniversalIntake | None = None,
) -> dict[str, Any]:
    if not isinstance(request, dict):
        return {
            "success": False,
            "state": "HOLD",
            "blockers": ["REQUEST_MUST_BE_AN_OBJECT"],
        }
    required = ("source_path", "ticket_id", "workspace_id", "agent_id", "productive_units")
    missing = []
    for name in required:
        value = request.get(name)
        if name == "productive_units":
            if not isinstance(value, list):
                missing.append(name)
        elif not isinstance(value, str) or not value.strip():
            missing.append(name)
    if missing:
        return {
            "success": False,
            "state": "HOLD",
            "blockers": [f"REQUEST_FIELD_REQUIRED:{name}" for name in missing],
        }
    runtime_request = request.get("runtime")
    if not isinstance(runtime_request, dict) or runtime_request.get("required") is not True:
        return {
            "success": False,
            "state": "HOLD",
            "blockers": ["RUNTIME_REQUIRED_FOR_STATION_PIPELINE"],
        }
    if not isinstance(runtime_request.get("command"), str) or not runtime_request["command"].strip():
        return {"success": False, "state": "HOLD", "blockers": ["RUNTIME_COMMAND_REQUIRED"]}
    if not isinstance(runtime_request.get("cwd"), str) or not runtime_request["cwd"].strip():
        return {"success": False, "state": "HOLD", "blockers": ["RUNTIME_CWD_REQUIRED"]}
    args = runtime_request.get("args", [])
    if not isinstance(args, list) or any(not isinstance(value, str) for value in args):
        return {"success": False, "state": "HOLD", "blockers": ["RUNTIME_ARGS_MUST_BE_STRINGS"]}
    timeout_seconds = runtime_request.get("timeout_seconds", 60)
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 900:
        return {"success": False, "state": "HOLD", "blockers": ["TIMEOUT_OUT_OF_RANGE"]}
    for name in ("workspace_id", "agent_id"):
        if not request[name].strip():
            return {
                "success": False,
                "state": "HOLD",
                "blockers": [f"REQUEST_FIELD_REQUIRED:{name}"],
            }

    try:
        source_path = runtime.assert_allowed_path(request["source_path"])
        intake_record = runtime.intake_local(source_path)
        source = intake_record["source"]
    except (OSError, RuntimeErrorState, ValueError) as exc:
        return {
            "success": False,
            "state": "NOT_VERIFIED",
            "blockers": [f"SOURCE_INTAKE_FAILED:{type(exc).__name__}:{exc}"],
        }

    ticket = runtime.get_ticket(request["ticket_id"])
    ticket_blockers = []
    if ticket is None:
        ticket_blockers.append("TICKET_NOT_FOUND")
    else:
        if ticket.get("source_id") != source["source_id"]:
            ticket_blockers.append("SOURCE_TICKET_MISMATCH")
        if ticket.get("status") != "AUTHORIZED":
            ticket_blockers.append("TICKET_NOT_AUTHORIZED")
        if ticket.get("operation") != "ONE_RUN":
            ticket_blockers.append("TICKET_OPERATION_MISMATCH")
        if ticket.get("capability") != "TERMINAL_EXECUTION":
            ticket_blockers.append("TICKET_CAPABILITY_MISMATCH")
    if ticket_blockers:
        return {
            "success": False,
            "source_id": source["source_id"],
            "transit_id": source["transit_id"],
            "ticket_id": request["ticket_id"],
            "state": "HOLD",
            "blockers": ticket_blockers,
        }
    execution_gate = runtime.verify_ticket(
        ticket_id=request["ticket_id"],
        source_id=source["source_id"],
        operation="ONE_RUN",
        command=runtime_request["command"],
        cwd=runtime_request["cwd"],
    )
    if execution_gate["state"] != "READY":
        return {
            "success": False,
            "source_id": source["source_id"],
            "transit_id": source["transit_id"],
            "ticket_id": request["ticket_id"],
            "state": "HOLD",
            "blockers": execution_gate["blockers"],
        }

    intake = universal_intake or UniversalIntake(runtime)
    try:
        normalized = intake.ingest(source_path)
    except (OSError, RuntimeErrorState, ValueError) as exc:
        return {
            "success": False,
            "source_id": source["source_id"],
            "transit_id": source["transit_id"],
            "ticket_id": request["ticket_id"],
            "state": "NOT_VERIFIED",
            "blockers": [f"NORMALIZATION_FAILED:{type(exc).__name__}:{exc}"],
        }
    if normalized.get("state") != "PASS":
        return {
            "success": False,
            "source_id": source["source_id"],
            "transit_id": source["transit_id"],
            "ticket_id": request["ticket_id"],
            "state": normalized.get("state", "NOT_VERIFIED"),
            "normalized_packet": normalized,
            "blockers": ["NORMALIZATION_NOT_VERIFIED"],
        }

    try:
        run_receipt = runtime.run_one(
            ticket_id=request["ticket_id"],
            source_id=source["source_id"],
            command=runtime_request["command"],
            args=args,
            cwd=runtime_request["cwd"],
            timeout_seconds=timeout_seconds,
            workspace_id=request["workspace_id"],
            zone_id=request.get("zone_id"),
        )
    except (OSError, RuntimeErrorState, ValueError) as exc:
        return {
            "success": False,
            "source_id": source["source_id"],
            "transit_id": source["transit_id"],
            "ticket_id": request["ticket_id"],
            "state": "NOT_VERIFIED",
            "normalized_packet": normalized,
            "blockers": [f"ONE_RUN_FAILED:{type(exc).__name__}:{exc}"],
        }
    if run_receipt.get("final_state") != "PASS":
        return {
            "success": False,
            "source_id": source["source_id"],
            "transit_id": source["transit_id"],
            "ticket_id": request["ticket_id"],
            "run_id": run_receipt.get("run_id"),
            "state": run_receipt.get("final_state", "NOT_VERIFIED"),
            "normalized_packet": normalized,
            "blockers": run_receipt.get("errors", ["ONE_RUN_NOT_VERIFIED"]),
        }

    unit_blockers: list[str] = []
    seen_unit_ids: set[str] = set()
    for index, unit in enumerate(request["productive_units"]):
        validation = validate_productive_unit(unit)
        unit_id = unit.get("unit_id", f"INDEX-{index}") if isinstance(unit, dict) else f"INDEX-{index}"
        if isinstance(unit, dict):
            if unit.get("source_id") != source["source_id"]:
                validation["blockers"].append("PRODUCTIVE_UNIT_SOURCE_MISMATCH")
                validation["valid"] = False
            if unit.get("unit_id") in seen_unit_ids:
                validation["blockers"].append("DUPLICATE_UNIT_ID")
                validation["valid"] = False
            if isinstance(unit.get("unit_id"), str):
                seen_unit_ids.add(unit["unit_id"])
        if not validation["valid"]:
            unit_blockers.extend(
                f"{unit_id}:{blocker}" for blocker in validation["blockers"]
            )
    if unit_blockers:
        return {
            "success": False,
            "source_id": source["source_id"],
            "transit_id": source["transit_id"],
            "ticket_id": request["ticket_id"],
            "run_id": run_receipt["run_id"],
            "state": "HOLD",
            "normalized_packet": normalized,
            "blockers": unit_blockers,
        }

    register_station07(runtime, station_registry)
    pipeline = StationPipeline(StationEngine(runtime, station_registry)).run(
        source_id=source["source_id"],
        ticket_id=request["ticket_id"],
        run_id=run_receipt["run_id"],
        workspace_id=request["workspace_id"],
        zone_id=request.get("zone_id"),
        agent_id=request["agent_id"],
        input_ref=source["source_path"],
        start_station=1,
        end_station=7,
        metadata={
            "normalized_packet": normalized,
            "productive_units": request["productive_units"],
        },
    )
    if pipeline["state"] != "PASS":
        return {
            "success": False,
            "source_id": source["source_id"],
            "transit_id": source["transit_id"],
            "ticket_id": request["ticket_id"],
            "run_id": run_receipt["run_id"],
            "state": pipeline["state"],
            "normalized_packet": normalized,
            "pipeline": pipeline,
            "settlements": [],
            "blockers": [f"PIPELINE_STOPPED_AT:{pipeline['stopped_at']}"],
        }

    settlements = []
    for unit in request["productive_units"]:
        try:
            settlement = runtime.settle(
                source_id=source["source_id"],
                unit_id=unit["unit_id"],
                domain=unit["domain"],
                payload_pointer=unit["payload_pointer"],
                sha256=unit["content_sha256"],
                evidence_id=unit["evidence_id"],
                retrieval_point=unit["retrieval_point"],
            )
        except (OSError, RuntimeErrorState, ValueError) as exc:
            return {
                "success": False,
                "source_id": source["source_id"],
                "transit_id": source["transit_id"],
                "ticket_id": request["ticket_id"],
                "run_id": run_receipt["run_id"],
                "state": "NOT_VERIFIED",
                "normalized_packet": normalized,
                "pipeline": pipeline,
                "settlements": settlements,
                "blockers": [
                    f"SETTLEMENT_FAILED:{unit['unit_id']}:{type(exc).__name__}:{exc}"
                ],
            }
        settlements.append(settlement)

    return {
        "success": True,
        "source_id": source["source_id"],
        "transit_id": source["transit_id"],
        "ticket_id": request["ticket_id"],
        "run_id": run_receipt["run_id"],
        "state": "SETTLED",
        "normalized_packet": normalized,
        "pipeline": pipeline,
        "settlements": settlements,
    }
