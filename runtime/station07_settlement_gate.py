"""Station 07 gate for contract-valid, physically verified productive units."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from runtime.productive_units import validate_productive_unit
from runtime.station_engine import (
    StationContext,
    StationHandler,
    StationHandlerResult,
)
from sovereign_runtime import RuntimeErrorState, SovereignRuntime, _read_json, sha256_file


def station07_settlement_gate(runtime: SovereignRuntime) -> StationHandler:
    def handle(context: StationContext) -> StationHandlerResult:
        units = context.metadata.get("productive_units")
        if not isinstance(units, list):
            return StationHandlerResult(
                state="HOLD",
                operation="STATION_07_SETTLEMENT_GATE",
                evidence={"productive_units": None},
                errors=["PRODUCTIVE_UNITS_REQUIRED"],
            )
        if not units:
            return StationHandlerResult(
                state="HOLD",
                operation="STATION_07_SETTLEMENT_GATE",
                evidence={"productive_units": []},
                errors=["NO_PRODUCTIVE_UNITS"],
            )

        validations = []
        valid_units: list[dict[str, Any]] = []
        seen_unit_ids: set[str] = set()
        for index, unit in enumerate(units):
            validation = validate_productive_unit(unit)
            unit_id = unit.get("unit_id") if isinstance(unit, dict) else None
            if isinstance(unit_id, str):
                if unit_id in seen_unit_ids:
                    validation["valid"] = False
                    validation["blockers"].append("DUPLICATE_UNIT_ID")
                seen_unit_ids.add(unit_id)
            if isinstance(unit, dict) and unit.get("source_id") != context.source_id:
                validation["valid"] = False
                validation["blockers"].append("PRODUCTIVE_UNIT_SOURCE_MISMATCH")
            validations.append(
                {"index": index, "unit_id": unit_id, **validation}
            )
            if validation["valid"]:
                valid_units.append(unit)

        invalid = [item for item in validations if not item["valid"]]
        if invalid:
            return StationHandlerResult(
                state="HOLD",
                operation="STATION_07_SETTLEMENT_GATE",
                evidence={"total_units": len(units), "invalid_units": invalid},
                errors=["PRODUCTIVE_UNIT_CONTRACT_FAILED"],
            )

        readbacks: list[dict[str, Any]] = []
        for unit in valid_units:
            unit_id = unit["unit_id"]
            evidence_id = unit["evidence_id"]
            payload_path: Path | None = None
            actual: str | None = None
            evidence_digest: str | None = None
            try:
                payload_path = runtime.assert_allowed_path(unit["payload_pointer"])
                if not payload_path.is_file():
                    raise RuntimeErrorState("PRODUCTIVE_UNIT_PAYLOAD_NOT_FILE")
                actual = sha256_file(payload_path)
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", evidence_id):
                    raise RuntimeErrorState("INVALID_EVIDENCE_ID")
                evidence_path = runtime.paths["evidence"] / f"{evidence_id}.json"
                if not evidence_path.is_file():
                    raise RuntimeErrorState("UNIT_EVIDENCE_NOT_FOUND")
                unit_evidence = _read_json(evidence_path, None)
                if (
                    not isinstance(unit_evidence, dict)
                    or unit_evidence.get("source_id") != context.source_id
                ):
                    raise RuntimeErrorState("UNIT_EVIDENCE_SOURCE_MISMATCH")
                run_receipt_path = (
                    runtime.paths["one_run"]
                    / f"{unit_evidence.get('run_id')}.json"
                    if isinstance(unit_evidence.get("run_id"), str)
                    and re.fullmatch(
                        r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}",
                        unit_evidence["run_id"],
                    )
                    else None
                )
                is_verified_run_evidence = False
                if run_receipt_path and run_receipt_path.is_file():
                    run_receipt = _read_json(run_receipt_path, None)
                    is_verified_run_evidence = (
                        isinstance(run_receipt, dict)
                        and run_receipt.get("final_state") == "PASS"
                        and run_receipt.get("evidence_id") == evidence_id
                        and sha256_file(evidence_path)
                        == run_receipt.get("evidence_sha256")
                    )
                if unit_evidence.get("state") != "PASS" and not is_verified_run_evidence:
                    raise RuntimeErrorState("UNIT_EVIDENCE_NOT_PASS")

                evidence_digest = sha256_file(evidence_path)
                expected = unit["content_sha256"].lower()
                readbacks.append(
                    {
                        "unit_id": unit_id,
                        "exists": payload_path.is_file(),
                        "expected_sha256": expected,
                        "actual_sha256": actual,
                        "matches": actual.lower() == expected,
                        "evidence_sha256": evidence_digest,
                    }
                )
            except (OSError, RuntimeErrorState) as exc:
                readbacks.append(
                    {
                        "unit_id": unit_id,
                        "exists": payload_path is not None and payload_path.is_file(),
                        "expected_sha256": unit["content_sha256"].lower(),
                        "actual_sha256": actual,
                        "matches": False,
                        "error": f"{type(exc).__name__}:{exc}",
                    }
                )

        failed = [item for item in readbacks if not item["matches"]]
        if failed:
            return StationHandlerResult(
                state="NOT_VERIFIED",
                operation="STATION_07_SETTLEMENT_GATE",
                evidence={
                    "total_units": len(valid_units),
                    "readbacks": readbacks,
                    "failed_readback": failed,
                },
                errors=["PRODUCTIVE_UNIT_READBACK_FAILED"],
            )

        return StationHandlerResult(
            state="PASS",
            operation="STATION_07_SETTLEMENT_GATE",
            output_ref=context.input_ref,
            evidence={
                "total_units": len(valid_units),
                "verified_units": [
                    {
                        "unit_id": unit["unit_id"],
                        "domain": unit["domain"],
                        "unit_type": unit["unit_type"],
                        "retrieval_point": unit["retrieval_point"],
                        "evidence_id": unit["evidence_id"],
                        "sha256": unit["content_sha256"].lower(),
                        "evidence_sha256": next(
                            item["evidence_sha256"]
                            for item in readbacks
                            if item["unit_id"] == unit["unit_id"]
                        ),
                    }
                    for unit in valid_units
                ],
                "readbacks": readbacks,
            },
        )

    return handle
