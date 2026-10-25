"""Read-only readiness check; this module never deletes source files."""

from __future__ import annotations

import re
from typing import Any

from sovereign_runtime import (
    RuntimeErrorState,
    SovereignRuntime,
    _read_json,
    sha256_file,
)


def check_source_removal_readiness(
    runtime: SovereignRuntime, source_id: str
) -> dict[str, Any]:
    source = runtime.get_source(source_id)
    if source is None:
        raise RuntimeErrorState("SOURCE_NOT_FOUND")

    blockers: list[str] = []
    current = runtime.current(source_id)
    if not isinstance(current, dict):
        blockers.append("FSX_STATE_MISSING")
    else:
        if current.get("current_state") != "SETTLED":
            blockers.append("SOURCE_NOT_SETTLED")
        if current.get("current_station") != "WAREHOUSE_35":
            blockers.append("WAREHOUSE_READINESS_NOT_REACHED")
        if not current.get("evidence_id"):
            blockers.append("FINAL_EVIDENCE_MISSING")
        if not current.get("ticket_id"):
            blockers.append("TICKET_MISSING")
        ticket = runtime.get_ticket(current.get("ticket_id", ""))
        if not ticket or ticket.get("source_id") != source_id or ticket.get("status") != "AUTHORIZED":
            blockers.append("AUTHORIZED_SOURCE_TICKET_NOT_FOUND")

    settlement_events = [
        event
        for event in runtime.events(source_id)
        if event.get("to_station") == "WAREHOUSE_35"
        and event.get("to_state") == "SETTLED"
        and event.get("operation") == "WAREHOUSE_SETTLEMENT"
    ]
    if not settlement_events:
        blockers.append("WAREHOUSE_SETTLEMENT_EVIDENCE_MISSING")
    elif current:
        evidence_id = current.get("evidence_id")
        try:
            if not isinstance(evidence_id, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", evidence_id
            ):
                raise RuntimeErrorState("FINAL_EVIDENCE_ID_INVALID")
            evidence_path = runtime.paths["evidence"] / f"{evidence_id}.json"
            if not evidence_path.is_file():
                raise RuntimeErrorState("FINAL_EVIDENCE_NOT_FOUND")
            if (
                sha256_file(evidence_path) != current.get("evidence_sha256")
                or settlement_events[-1].get("evidence_id") != evidence_id
            ):
                raise RuntimeErrorState("FINAL_EVIDENCE_HASH_MISMATCH")
        except (OSError, RuntimeErrorState):
            blockers.append("FINAL_EVIDENCE_READBACK_FAILED")

    try:
        warehouse_records = _read_json(runtime.paths["warehouse"], [])
    except RuntimeErrorState:
        warehouse_records = []
        blockers.append("WAREHOUSE_REGISTRY_INVALID")
    if not isinstance(warehouse_records, list):
        warehouse_records = []
        blockers.append("WAREHOUSE_REGISTRY_INVALID")
    source_units = [
        item
        for item in warehouse_records
        if isinstance(item, dict)
        and item.get("source_id") == source_id
        and item.get("state") == "SETTLED"
    ]
    if not source_units:
        blockers.append("SETTLED_PRODUCTIVE_UNITS_MISSING")
    for unit in source_units:
        try:
            payload_path = runtime.assert_allowed_path(unit["payload_pointer"])
            expected_hash = unit["sha256"]
            if (
                not payload_path.is_file()
                or not isinstance(expected_hash, str)
                or sha256_file(payload_path).lower() != expected_hash.lower()
            ):
                blockers.append(
                    f"SETTLED_UNIT_READBACK_FAILED:{unit.get('unit_id', 'UNKNOWN')}"
                )
        except (KeyError, OSError, RuntimeErrorState):
            blockers.append(
                f"SETTLED_UNIT_READBACK_FAILED:{unit.get('unit_id', 'UNKNOWN')}"
            )

    source_exists = False
    try:
        source_path = runtime.assert_allowed_path(source["source_path"])
        source_exists = source_path.is_file()
        if not source_exists:
            blockers.append("SOURCE_PHYSICAL_READBACK_FAILED")
        elif sha256_file(source_path) != source["sha256"]:
            blockers.append("SOURCE_CONTENT_CHANGED")
    except (OSError, RuntimeErrorState):
        blockers.append("SOURCE_PHYSICAL_READBACK_FAILED")

    return {
        "eligible": not blockers,
        "source_id": source["source_id"],
        "source_exists": source_exists,
        "blockers": blockers,
        "retained_identity": {
            "source_name": source["source_name"],
            "source_id": source["source_id"],
            "transit_id": source["transit_id"],
            "sha256": source["sha256"],
            "size_bytes": source["size_bytes"],
        },
    }
