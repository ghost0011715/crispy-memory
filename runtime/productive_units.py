"""Contracts and stable identifiers for warehouse-ready productive units."""

from __future__ import annotations

import hashlib
import re
from typing import Any, TypedDict


class ProductiveUnit(TypedDict, total=False):
    unit_id: str
    source_id: str
    domain: str
    unit_type: str
    input_contract: Any
    output_contract: Any
    produces: list[str]
    consumes: list[str]
    payload_pointer: str
    content_sha256: str
    evidence_id: str
    lineage_id: str
    retrieval_point: str
    retrieval_keys: list[str]
    usage_conditions: list[str]
    context_requirements: list[str]
    verification_state: str
    version: str


def validate_productive_unit(unit: Any) -> dict[str, Any]:
    blockers: list[str] = []
    if not isinstance(unit, dict):
        return {"valid": False, "blockers": ["UNIT_MUST_BE_AN_OBJECT"]}

    for field, code in (
        ("unit_id", "UNIT_ID_REQUIRED"),
        ("source_id", "SOURCE_ID_REQUIRED"),
        ("domain", "DOMAIN_REQUIRED"),
        ("unit_type", "UNIT_TYPE_REQUIRED"),
        ("payload_pointer", "PAYLOAD_POINTER_REQUIRED"),
        ("evidence_id", "EVIDENCE_ID_REQUIRED"),
        ("retrieval_point", "RETRIEVAL_POINT_REQUIRED"),
    ):
        value = unit.get(field)
        if not isinstance(value, str) or not value.strip():
            blockers.append(code)

    digest = unit.get("content_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
        blockers.append("VALID_CONTENT_SHA256_REQUIRED")
    if unit.get("verification_state") != "PASS":
        blockers.append("UNIT_NOT_VERIFIED")

    return {"valid": not blockers, "blockers": blockers}


def stable_unit_id(*, domain: str, unit_type: str, content_sha256: str) -> str:
    if not isinstance(domain, str) or not domain.strip():
        raise ValueError("DOMAIN_REQUIRED")
    if not isinstance(unit_type, str) or not unit_type.strip():
        raise ValueError("UNIT_TYPE_REQUIRED")
    if not isinstance(content_sha256, str) or not re.fullmatch(
        r"[a-fA-F0-9]{64}", content_sha256
    ):
        raise ValueError("VALID_CONTENT_SHA256_REQUIRED")
    material = "|".join((domain, unit_type, content_sha256.lower()))
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24].upper()
    return f"UNIT-{digest}"
