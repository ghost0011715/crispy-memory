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
        # An authorized ONE_RUN ticket is NOT deletion authorization.
        if (
            not ticket
            or ticket.get("operation") != "SOURCE_RETIREMENT"
            or ticket.get("capability") != "SOURCE_REMOVAL"
            or ticket.get("authorized_by") != "ONE_AGENT"
            or ticket.get("source_id") != source_id
        ):
            blockers.append("SOURCE_RETIREMENT_AUTHORIZATION_MISSING")


    # The current intake implementation does not persist a complete inventory
    # certificate. Fail closed until an independently checked inventory exists.
    if not isinstance(source.get("inventory_id"), str) or not source["inventory_id"]:
        blockers.append("SOURCE_INVENTORY_PROOF_MISSING")
    if type(source.get("source_file_count")) is not int or source["source_file_count"] < 1:
        blockers.append("SOURCE_FILE_COUNT_PROOF_MISSING")

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
    source_path_for_alias = None
    try:
        source_path_for_alias = runtime.assert_allowed_path(source["source_path"])
    except (OSError, RuntimeErrorState, KeyError, TypeError, ValueError):
        blockers.append("SOURCE_PATH_NOT_VERIFIED")

    for unit in source_units:
        try:
            payload_path = runtime.assert_allowed_path(unit["payload_pointer"])
            expected_hash = unit["sha256"]
            # A settled pointer into the original file cannot survive its removal.
            if source_path_for_alias is not None and (
                payload_path == source_path_for_alias
                or payload_path.samefile(source_path_for_alias)
            ):
                blockers.append(
                    f"PRODUCTIVE_UNIT_POINTS_TO_ORIGINAL:{unit.get('unit_id', 'UNKNOWN')}"
                )
            # A byte-for-byte copy is not a decomposed/reusable output.
            if (
                isinstance(expected_hash, str)
                and expected_hash.lower() == source["sha256"].lower()
                and payload_path != source_path_for_alias
            ):
                blockers.append(
                    f"ORIGINAL_BYTES_RETAINED_AS_UNIT:{unit.get('unit_id', 'UNKNOWN')}"
                )
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

    # Current runtime has no independent, persisted retrieval proof packet.
    # SETTLED/FSX current state by itself is insufficient for retirement.
    blockers.append("INDEPENDENT_FSX_RETRIEVAL_PROOF_MISSING")

    # Verify every station receipt before considering retirement.
    receipts_root = runtime.root / "stations" / "receipts" / source_id
    for station in range(1, 8):
        files = list(receipts_root.glob(f"STATION_{station:02d}_*.json"))
        station_ok = False
        for receipt_path in files:
            try:
                receipt = _read_json(receipt_path, None)
                if not isinstance(receipt, dict):
                    continue
                evidence_id = receipt.get("evidence_id")
                if not isinstance(evidence_id, str) or not re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", evidence_id
                ):
                    continue
                evidence_path = runtime.paths["evidence"] / f"{evidence_id}.json"
                evidence = _read_json(evidence_path, None)
                if (
                    receipt.get("source_id") == source_id
                    and receipt.get("transit_id") == source["transit_id"]
                    and receipt.get("station") == station
                    and receipt.get("state") == "PASS"
                    and receipt.get("readback_verified") is True
                    and receipt.get("receipt_readback_verified") is True
                    and receipt.get("evidence_sha256") == sha256_file(evidence_path)
                    and isinstance(evidence, dict)
                    and evidence.get("source_id") == source_id
                    and evidence.get("station") == station
                    and evidence.get("state") == "PASS"
                ):
                    station_ok = True
                    break
            except (OSError, RuntimeErrorState, ValueError):
                continue
        if not station_ok:
            blockers.append(f"STATION_{station:02d}_VERIFIED_RECEIPT_MISSING")

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

    # Never grant deletion readiness from generic settlement success.
    blockers = list(dict.fromkeys(blockers))
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
