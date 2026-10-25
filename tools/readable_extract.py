#!/usr/bin/env python3
"""CLI adapter for converting one source into readable output and a manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from file_intake import FileIntake, IntakeError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract readable content without executing the source."
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)

    output = Path(args.out_dir).expanduser().resolve()
    try:
        report = FileIntake(output).process(args.source)
    except (OSError, IntakeError, ValueError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}), file=sys.stderr)
        return 2

    records = report["records"]
    record = records[0] if records else None
    statuses = {item["status"] for item in records}
    if not record or "FAILED" in statuses:
        status = "NOT_VERIFIED"
    elif statuses == {"EXTRACTED"}:
        status = "PASS"
    elif "PARTIAL" in statuses or "UNSUPPORTED" in statuses:
        status = "HOLD"
    else:
        status = "NOT_VERIFIED"

    readable_path = (
        output / record["readable_output_path"]
        if record and record.get("readable_output_path")
        else None
    )
    structured_path = output / "intake-report.json"
    manifest_path = output / "manifest.json"
    manifest = {
        "schema_version": "1.0",
        "source_id": record["source_id"] if record else None,
        "result": {
            "status": status,
            "content_kind": record["detected_format"] if record else "UNKNOWN",
            "extractor": record.get("adapter_id") if record else None,
            "artifacts": {
                "text": str(readable_path) if readable_path else None,
                "structured": str(structured_path),
            },
            "provider_required": None,
            "warnings": [
                warning for item in records for warning in item["warnings"]
            ],
            "errors": [error for item in records for error in item["errors"]],
        },
        "source_count": len(records),
        "summary": report["summary"],
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"success": status == "PASS", "manifest": str(manifest_path), **manifest["result"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
