"""Normalize a Nova-registered source and persist a source-linked packet."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from file_intake import FileIntake, IntakeError
from runtime.capability_registry import capabilities_for
from sovereign_runtime import RuntimeErrorState, SovereignRuntime


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class UniversalIntake:
    def __init__(self, runtime: SovereignRuntime) -> None:
        self.runtime = runtime
        self.normalized_root = runtime.root / "normalized"
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def ingest(self, source_path: str | Path) -> dict[str, Any]:
        registered = self.runtime.intake_local(source_path)
        source, ticket = registered["source"], registered["ticket"]
        packet_id = "NORM-" + secrets.token_hex(12).upper()
        output_dir = (
            self.normalized_root / source["source_id"] / packet_id
        ).resolve()
        output_dir.mkdir(parents=True, exist_ok=False)
        flow = self.runtime.current(source["source_id"])
        flow_id = flow["flow_id"] if flow else "FLOW-" + secrets.token_hex(12)

        self.runtime.emit(
            flow_id=flow_id,
            entity_id=source["source_id"],
            source_id=source["source_id"],
            transit_id=source["transit_id"],
            from_state=(flow or {}).get("current_state", "OBSERVED"),
            to_state="RUNNING",
            from_station=(flow or {}).get("current_station", "NOVA"),
            to_station="NORMALIZATION",
            workspace_id=f"WS-NORMALIZE-{source['source_id']}",
            zone_id="UNIVERSAL_CONTENT_ZONE",
            agent_id="FILESCANNER",
            operation="READABLE_NORMALIZATION_STARTED",
            input_ref=source["source_path"],
            sha256_before=source["sha256"],
            ticket_id=ticket["ticket_id"],
        )

        try:
            report = FileIntake(output_dir).process(source["source_path"])
        except (OSError, IntakeError, ValueError) as exc:
            self.runtime.emit(
                flow_id=flow_id,
                entity_id=source["source_id"],
                source_id=source["source_id"],
                transit_id=source["transit_id"],
                from_state="RUNNING",
                to_state="NOT_VERIFIED",
                from_station="NORMALIZATION",
                to_station="NORMALIZATION",
                workspace_id=f"WS-NORMALIZE-{source['source_id']}",
                zone_id="UNIVERSAL_CONTENT_ZONE",
                agent_id="FILESCANNER",
                operation="READABLE_NORMALIZATION_FAILED",
                input_ref=source["source_path"],
                sha256_before=source["sha256"],
                ticket_id=ticket["ticket_id"],
            )
            raise RuntimeErrorState(f"NORMALIZATION_FAILED:{exc}") from exc

        records = report["records"]
        record = records[0] if records else {}
        statuses = {item["status"] for item in records}
        if statuses == {"EXTRACTED"}:
            state = "PASS"
        elif "PARTIAL" in statuses or "UNSUPPORTED" in statuses:
            state = "HOLD"
        else:
            state = "NOT_VERIFIED"

        output_ref = (
            str(output_dir / record["readable_output_path"])
            if record.get("readable_output_path")
            else None
        )
        manifest_path = output_dir / "intake-report.json"
        capability_rows = capabilities_for(source["extension"])
        provider_required = next(
            (
                item["provider"]
                for item in capability_rows
                if item["mode"] in {"OPTIONAL_LIBRARY", "OPTIONAL_LOCAL_TOOL"}
            ),
            None,
        )
        packet = {
            "packet_id": packet_id,
            "source_id": source["source_id"],
            "transit_id": source["transit_id"],
            "source_name": source["source_name"],
            "source_path": source["source_path"],
            "source_sha256": source["sha256"],
            "source_size_bytes": source["size_bytes"],
            "detected_kind": record.get("detected_format", "UNKNOWN"),
            "extractor": record.get("adapter_id") or "UNKNOWN",
            "state": state,
            "derived_manifest": str(manifest_path),
            "text_ref": output_ref,
            "structured_ref": str(manifest_path),
            "provider_required": provider_required,
            "warnings": [warning for item in records for warning in item["warnings"]],
            "errors": [error for item in records for error in item["errors"]],
            "capabilities": capability_rows,
            "flow_id": flow_id,
            "created_at": _now(),
        }
        packet_path = output_dir / "normalized_packet.json"
        _write_json(packet_path, packet)
        packet_hash = self.runtime_hash(packet_path)

        self.runtime.emit(
            flow_id=flow_id,
            entity_id=source["source_id"],
            source_id=source["source_id"],
            transit_id=source["transit_id"],
            from_state="RUNNING",
            to_state=state,
            from_station="NORMALIZATION",
            to_station="NORMALIZATION",
            workspace_id=f"WS-NORMALIZE-{source['source_id']}",
            zone_id="UNIVERSAL_CONTENT_ZONE",
            agent_id="FILESCANNER",
            operation=(
                "READABLE_NORMALIZATION_PASS"
                if state == "PASS"
                else "READABLE_NORMALIZATION_HOLD"
            ),
            input_ref=source["source_path"],
            output_ref=str(packet_path),
            sha256_before=source["sha256"],
            sha256_after=packet_hash,
            ticket_id=ticket["ticket_id"],
        )
        return packet

    @staticmethod
    def runtime_hash(path: Path) -> str:
        from sovereign_runtime import sha256_file

        return sha256_file(path)

    def read_normalized(self, source_id: str) -> list[dict[str, Any]]:
        source_root = (self.normalized_root / source_id).resolve()
        try:
            source_root.relative_to(self.normalized_root.resolve())
        except ValueError as exc:
            raise RuntimeErrorState("SOURCE_ID_PATH_NOT_ALLOWED") from exc
        if not source_root.is_dir():
            return []
        packets = []
        for child in sorted(source_root.iterdir()):
            if not child.is_dir() or child.is_symlink():
                continue
            path = child / "normalized_packet.json"
            if not path.is_file():
                continue
            try:
                packet = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeErrorState(f"NORMALIZED_PACKET_INVALID:{path}") from exc
            if packet.get("source_id") != source_id:
                raise RuntimeErrorState("NORMALIZED_PACKET_SOURCE_MISMATCH")
            packets.append(packet)
        return sorted(packets, key=lambda packet: packet["created_at"], reverse=True)
