# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

ROOT = Path(__file__).resolve().parent
DEFAULT_INTAKE_DB = ROOT / "out" / "_analysis" / "filescanner_intake.db"

HIGH_VALUE_CATEGORIES = {
    "capability_pack",
    "language_learning",
    "language",
    "learning",
    "patterns",
}

PROMOTE_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx",
    ".json", ".jsonl", ".md", ".txt", ".csv",
    ".sql", ".db", ".sqlite", ".pdf", ".docx",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".bat", ".cmd", ".ps1", ".exe",
}

UNSAFE_EXTENSIONS = {".bat", ".cmd", ".ps1", ".exe", ".dll", ".pkl", ".pickle"}


RISK_PATTERNS = {
    "subprocess": r"\bsubprocess\b",
    "os.system": r"\bos\s*\.\s*system\b",
    "shell=true": r"\bshell\s*=\s*true\b",
    "popen": r"\bpopen\s*\(",
    "powercfg": r"\bpowercfg\b",
    "taskkill": r"\btaskkill\b",
    "recursive_delete": r"\brm\s+-rf\b",
    "windows_delete": r"\bdel\s+/",
    "pip_install": r"\bpip\s+install\b",
    "api_key": r"\bapi[_-]?key\b",
    "secret": r"\bsecret\b",
    "token": r"\btoken\b",
    "password": r"\bpassword\b",
    "dotenv": r"(?<![\w])\.env(?:$|[\\/.\s])",
}

REQUIRED_COLUMNS = {
    "zip_intake_runs": {"intake_id", "created_at"},
    "zip_intake_entries": {
        "intake_id",
        "entry_name",
        "extension",
        "category",
        "tags_json",
        "indexed_content",
        "preview",
    },
    "zip_intake_contents": {"intake_id", "entry_name", "content"},
}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(f"Intake database not found: {path}")
    database = path.resolve().as_uri() + "?mode=ro" if readonly else str(path)
    con = sqlite3.connect(database, timeout=30, uri=readonly)
    if readonly:
        con.execute("PRAGMA query_only = ON")
    return con


def validate_source_schema(con: sqlite3.Connection) -> None:
    missing = []
    for table, required in REQUIRED_COLUMNS.items():
        columns = {
            row[1]
            for row in con.execute(f'PRAGMA table_info("{table}")')
        }
        if not columns:
            missing.append(f"table {table}")
            continue
        missing.extend(
            f"column {table}.{column}" for column in sorted(required - columns)
        )
    if missing:
        raise RuntimeError(
            "Intake database schema is incomplete: " + ", ".join(missing)
        )


def latest_intake_id(con: sqlite3.Connection) -> str:
    row = con.execute("""
        SELECT intake_id
        FROM zip_intake_runs
        ORDER BY created_at DESC, intake_id DESC
        LIMIT 1
    """).fetchone()
    if not row:
        raise RuntimeError("No zip_intake_runs found.")
    return str(row[0])


def ensure_review_tables(con: sqlite3.Connection) -> None:
    con.execute("""
    CREATE TABLE IF NOT EXISTS intake_review_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        intake_id TEXT NOT NULL,
        entry_name TEXT NOT NULL,
        extension TEXT,
        category TEXT,
        tags_json TEXT,
        target_layer TEXT NOT NULL,
        decision TEXT NOT NULL,
        reason TEXT NOT NULL,
        risk_level TEXT NOT NULL DEFAULT 'low',
        status TEXT NOT NULL DEFAULT 'pending_review',
        created_at TEXT NOT NULL,
        UNIQUE(intake_id, entry_name, target_layer)
    )
    """)
    con.execute("""
    CREATE TABLE IF NOT EXISTS intake_promotion_runs (
        promotion_id TEXT PRIMARY KEY,
        intake_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        promoted_count INTEGER NOT NULL,
        direct_execution INTEGER NOT NULL DEFAULT 0,
        gold_write INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending_review',
        report_json TEXT
    )
    """)
    con.execute("""
    CREATE TABLE IF NOT EXISTS intake_layer_counts (
        promotion_id TEXT NOT NULL,
        target_layer TEXT NOT NULL,
        item_count INTEGER NOT NULL,
        PRIMARY KEY (promotion_id, target_layer)
    )
    """)


def normalize_path(value: str) -> str:
    return unicodedata.normalize("NFC", value or "").replace("\\", "/").strip("/").casefold()


def normalize_extension(entry_name: str, extension: Optional[str]) -> str:
    declared = (extension or "").strip().casefold()
    if declared and not declared.startswith("."):
        declared = f".{declared}"
    filename_extension = Path(entry_name.replace("\\", "/")).suffix.casefold()
    if filename_extension and filename_extension != declared:
        return filename_extension
    return declared or filename_extension


def parse_tags(tags_json: Optional[str]) -> Tuple[List[str], bool]:
    if not tags_json:
        return [], True
    try:
        value = json.loads(tags_json)
    except (json.JSONDecodeError, TypeError):
        return [], False
    if not isinstance(value, list) or not all(isinstance(tag, str) for tag in value):
        return [], False
    return [tag.casefold() for tag in value], True


def indexed_content_flag(value: object) -> Tuple[bool, bool]:
    if isinstance(value, bool):
        return value, True
    if isinstance(value, int) and value in (0, 1):
        return bool(value), True
    if value is None:
        return False, True
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true"}:
            return True, True
        if normalized in {"", "0", "false"}:
            return False, True
    return False, False


def risk_signals(text: str) -> List[str]:
    normalized = unicodedata.normalize("NFC", text or "").casefold()
    return [
        name
        for name, pattern in RISK_PATTERNS.items()
        if re.search(pattern, normalized)
    ]


def has_any(text: str, words: Union[List[str], Tuple[str, ...], set]) -> bool:
    normalized = unicodedata.normalize("NFC", text or "").casefold()
    return any(str(word).casefold() in normalized for word in words)


def _classification(
    target_layer: str, decision: str, reason: str, risk_level: str
) -> Dict[str, str]:
    return {
        "target_layer": target_layer,
        "decision": decision,
        "reason": reason,
        "risk_level": risk_level,
    }


def classify_target(entry: dict, content: str) -> dict:
    name = normalize_path(str(entry.get("entry_name") or ""))
    path_parts = set(name.split("/"))
    basename = name.rsplit("/", 1)[-1]
    ext = normalize_extension(str(entry.get("entry_name") or ""), entry.get("extension"))
    category = str(entry.get("category") or "").casefold()
    preview = str(entry.get("preview") or "")
    tags, _ = parse_tags(entry.get("tags_json"))
    combined = "\n".join((name, category, preview, content[:8000]))
    signals = risk_signals(combined)
    unsafe_extension = ext in UNSAFE_EXTENSIONS
    risk_hit = unsafe_extension or bool(signals) or "unsafe_candidate" in tags

    if path_parts.intersection({"node_modules", "dist", "build", "vendor"}):
        return _classification(
            "vendor_metadata_only", "skip_content", "dependency_or_build_output", "low"
        )

    sacred_terms = [
        "quran", "قرآن", "قران", "hadith", "حديث", "اذكار", "أذكار",
        "دعاء", "فتوى", "تفسير",
    ]
    if has_any(name, sacred_terms):
        return _classification(
            "sacred_review", "reference_match_only", "sacred_or_religious_text", "medium"
        )

    if ext in {".pdf", ".docx"} or has_any(name, ["ocr", "pdf_extraction"]):
        return _classification(
            "pdf_ocr_source", "direct_extract_no_copy", "pdf_doc_or_ocr_source", "low"
        )

    if ext in UNSAFE_EXTENSIONS:
        return _classification(
            "unsafe_quarantine", "hold", "unsafe_file_type", "high"
        )

    is_controller = basename == "go.py"
    is_filescanner = any(
        "filescanner" in part or "file_scanner" in part or part == "fsx"
        for part in path_parts
    )
    if is_controller or is_filescanner:
        layer = "go_runtime" if is_controller else "filescanner"
        label = "runtime_controller_entry" if is_controller else "filescanner_component"
        if risk_hit:
            return _classification(
                layer,
                "review_controller_wrapper",
                f"{label}_with_risk_scan",
                "high",
            )
        risk_level = "medium" if ext == ".py" else "low"
        return _classification(layer, "review_controller", label, risk_level)

    if risk_hit:
        reason = "unsafe_candidate_tag" if "unsafe_candidate" in tags else "risk_keyword"
        return _classification("unsafe_quarantine", "hold", reason, "high")

    if has_any(name, ["agent_loader", "factory_shadow", "shadow", "agent_logger", "create_agents", "run_local_agent"]):
        return _classification("agent_shadow", "review_no_apply", "agent_or_shadow_component", "medium")

    if has_any(name, ["maintenance", "repair", "fix", "صيانة", "اصلاح", "إصلاح", "review_queue"]):
        return _classification("maintenance_ops", "index_to_review", "maintenance_or_repair_content", "low")

    if ext in {".db", ".sqlite", ".sql"} or has_any(name, ["schema", "sqlite", "database", "db.py"]):
        risk_level = "medium" if ext in {".db", ".sqlite"} else "low"
        return _classification("database", "schema_review_only", "database_or_schema", risk_level)

    if has_any(name, ["brain_food", "runtime_decision", "memory", "pattern", "patterns", "learned_patterns", "registry"]):
        return _classification("agent_feed", "review_memory_candidate", "agent_memory_pattern_or_feed", "low")

    if has_any(name, ["chat", "dialogue", "conversation", "greetings", "raw_dialogues"]):
        return _classification("text_chat", "index_to_chat_db", "chat_or_dialogue_source", "low")

    if has_any(name, ["dialect", "لهجة", "اللهجات", "lexicon", "nlp", "language", "arabic", "عربي", "العربية"]):
        return _classification("dialect_language", "index_to_language_dataset", "language_or_dialect_source", "low")

    if has_any(name, ["src/components", ".tsx", "dashboard", "terminalapp", "wordapp", "excelapp", "browserapp"]):
        return _classification("ui_candidate", "ui_review", "frontend_ui_component", "low")

    if category in HIGH_VALUE_CATEGORIES:
        return _classification("patterns_learning", "review_learning_candidate", "high_value_category", "low")

    if ext in {".py", ".ts", ".tsx", ".js", ".jsx"}:
        risk_level = "medium" if ext == ".py" else "low"
        return _classification("code", "parse_symbols_no_execute", "source_code", risk_level)

    if ext in {".md", ".txt", ".json", ".jsonl", ".csv", ".yaml", ".yml"}:
        return _classification("package_docs", "index_to_chat_db", "text_or_data_doc", "low")

    return _classification("general_text", "index_metadata_only", "general_or_unknown", "low")


def should_promote(row: dict) -> bool:
    ext = normalize_extension(
        str(row.get("entry_name") or ""), row.get("extension")
    )
    category = str(row.get("category") or "").casefold()
    indexed_content, _ = indexed_content_flag(row.get("indexed_content"))
    tags, _ = parse_tags(row.get("tags_json"))

    # noisy/vendor/build files stay only in zip_intake_entries as metadata.
    # They must not enter review_queue.
    if category == "skipped_noise":
        return False

    if indexed_content:
        return True
    if category in HIGH_VALUE_CATEGORIES:
        return True
    if ext in PROMOTE_EXTENSIONS or ext in UNSAFE_EXTENSIONS:
        return True

    if "unsafe_candidate" in tags:
        return True

    return False


def promote(
    db_path: Path, intake_id: Optional[str] = None, dry_run: bool = False
) -> dict:
    con = connect(db_path, readonly=dry_run)
    con.row_factory = sqlite3.Row
    try:
        validate_source_schema(con)
        selected_intake_id = intake_id or latest_intake_id(con)
        intake_exists = con.execute(
            "SELECT 1 FROM zip_intake_runs WHERE intake_id = ?",
            (selected_intake_id,),
        ).fetchone()
        if not intake_exists:
            raise RuntimeError(f"Unknown intake ID: {selected_intake_id}")

        rows = con.execute("""
            SELECT
                e.intake_id,
                e.entry_name,
                e.extension,
                e.size_bytes,
                e.category,
                e.tags_json,
                e.indexed_content,
                e.content_status,
                e.content_sha256,
                e.preview,
                c.content AS indexed_text,
                c.content_sha256 AS indexed_sha256
            FROM zip_intake_entries AS e
            LEFT JOIN zip_intake_contents AS c
                ON c.intake_id = e.intake_id
                AND c.entry_name = e.entry_name
            WHERE e.intake_id = ?
            ORDER BY e.entry_name
        """, (selected_intake_id,)).fetchall()

        promotion_id = (
            f"promote_{selected_intake_id}_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        )
        created_at = now()
        promoted = []
        seen_normalized_paths = set()
        skipped_noise_count = 0
        duplicate_path_count = 0
        candidate_layer_counts: Dict[str, int] = {}
        candidate_decision_counts: Dict[str, int] = {}
        quality_warnings = []

        for row in rows:
            entry = dict(row)
            entry_name = str(entry["entry_name"])
            if not entry_name.strip():
                quality_warnings.append({
                    "entry_name": entry_name,
                    "issue": "empty_entry_name",
                })
                continue
            if (entry.get("category") or "").casefold() == "skipped_noise":
                skipped_noise_count += 1
                continue

            normalized_name = normalize_path(entry_name)
            if normalized_name in seen_normalized_paths:
                duplicate_path_count += 1
                quality_warnings.append({
                    "entry_name": entry_name,
                    "issue": "duplicate_normalized_path",
                })
                continue
            seen_normalized_paths.add(normalized_name)

            indexed, indexed_valid = indexed_content_flag(entry.get("indexed_content"))
            tags, tags_valid = parse_tags(entry.get("tags_json"))
            if not indexed_valid:
                quality_warnings.append({
                    "entry_name": entry_name,
                    "issue": "invalid_indexed_content_flag",
                })
            if not tags_valid:
                quality_warnings.append({
                    "entry_name": entry_name,
                    "issue": "invalid_tags_json",
                })
                entry["tags_json"] = "[]"

            source_extension = str(entry.get("extension") or "")
            normalized_extension = normalize_extension(entry_name, source_extension)
            if source_extension.strip().casefold().lstrip(".") != normalized_extension.lstrip("."):
                quality_warnings.append({
                    "entry_name": entry_name,
                    "issue": "extension_mismatch",
                })
            entry["extension"] = normalized_extension

            content = entry.get("indexed_text") or ""
            if indexed and entry.get("indexed_text") is None:
                quality_warnings.append({
                    "entry_name": entry_name,
                    "issue": "indexed_content_missing",
                })
            source_hash = entry.get("content_sha256")
            indexed_hash = entry.get("indexed_sha256")
            if indexed and source_hash and indexed_hash and source_hash != indexed_hash:
                quality_warnings.append({
                    "entry_name": entry_name,
                    "issue": "indexed_content_hash_mismatch",
                })

            if not should_promote(entry):
                continue

            decision = classify_target(entry, content)
            item = {
                "intake_id": selected_intake_id,
                "entry_name": entry_name,
                "extension": entry.get("extension"),
                "category": entry.get("category"),
                "tags_json": entry["tags_json"],
                "target_layer": decision["target_layer"],
                "decision": decision["decision"],
                "reason": decision["reason"],
                "risk_level": decision["risk_level"],
                "status": "pending_review",
                "created_at": created_at,
            }
            promoted.append(item)
            layer = item["target_layer"]
            action = item["decision"]
            candidate_layer_counts[layer] = candidate_layer_counts.get(layer, 0) + 1
            candidate_decision_counts[action] = candidate_decision_counts.get(action, 0) + 1

        def build_report(
            newly_queued: List[dict],
            already_queued_count: int,
            dry_run: bool,
        ) -> dict:
            queued_layer_counts: Dict[str, int] = {}
            for item in newly_queued:
                layer = item["target_layer"]
                queued_layer_counts[layer] = queued_layer_counts.get(layer, 0) + 1

            return {
                "promotion_id": promotion_id,
                "intake_id": selected_intake_id,
                "created_at": created_at,
                "source_db": str(db_path),
                "source_entry_count": len(rows),
                "skipped_noise_count": skipped_noise_count,
                "duplicate_normalized_path_count": duplicate_path_count,
                "promoted_count": len(promoted),
                "candidate_count": len(promoted),
                "newly_queued_count": 0 if dry_run else len(newly_queued),
                "would_queue_count": len(newly_queued) if dry_run else 0,
                "already_queued_count": already_queued_count,
                "target_layer_counts": dict(sorted(candidate_layer_counts.items(), key=lambda x: (-x[1], x[0]))),
                "decision_counts": dict(sorted(candidate_decision_counts.items(), key=lambda x: (-x[1], x[0]))),
                "queued_layer_counts": dict(sorted(queued_layer_counts.items())),
                "data_quality_warning_count": len(quality_warnings),
                "data_quality_warnings": quality_warnings[:100],
                "status": "pending_review",
                "gold_write": 0,
                "direct_execution": 0,
                "dry_run": dry_run,
                "items": promoted[:200],
            }

        if dry_run:
            queue_table = con.execute("""
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'intake_review_queue'
            """).fetchone()
            existing_keys = set()
            if queue_table:
                queue_columns = {
                    row[1]
                    for row in con.execute(
                        'PRAGMA table_info("intake_review_queue")'
                    )
                }
                required_queue_columns = {"intake_id", "entry_name", "target_layer"}
                if not required_queue_columns.issubset(queue_columns):
                    missing = ", ".join(sorted(required_queue_columns - queue_columns))
                    raise RuntimeError(
                        f"Review queue schema is incomplete; missing columns: {missing}"
                    )
                existing_keys = {
                    (normalize_path(row["entry_name"]), row["target_layer"])
                    for row in con.execute("""
                        SELECT entry_name, target_layer
                        FROM intake_review_queue
                        WHERE intake_id = ?
                    """, (selected_intake_id,))
                }
            would_queue = [
                item for item in promoted
                if (normalize_path(item["entry_name"]), item["target_layer"]) not in existing_keys
            ]
            report = build_report(
                would_queue,
                len(promoted) - len(would_queue),
                dry_run=True,
            )
        else:
            with con:
                con.execute("BEGIN IMMEDIATE")
                ensure_review_tables(con)
                newly_queued = []
                already_queued_count = 0
                existing_keys = {
                    (normalize_path(row["entry_name"]), row["target_layer"])
                    for row in con.execute("""
                        SELECT entry_name, target_layer
                        FROM intake_review_queue
                        WHERE intake_id = ?
                    """, (selected_intake_id,))
                }
                for item in promoted:
                    item_key = (normalize_path(item["entry_name"]), item["target_layer"])
                    if item_key in existing_keys:
                        already_queued_count += 1
                        continue

                    con.execute("""
                        INSERT INTO intake_review_queue (
                            intake_id, entry_name, extension, category, tags_json,
                            target_layer, decision, reason, risk_level, status, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        item["intake_id"],
                        item["entry_name"],
                        item["extension"],
                        item["category"],
                        item["tags_json"],
                        item["target_layer"],
                        item["decision"],
                        item["reason"],
                        item["risk_level"],
                        item["status"],
                        item["created_at"],
                    ))
                    newly_queued.append(item)
                    existing_keys.add(item_key)

                report = build_report(
                    newly_queued,
                    already_queued_count,
                    dry_run=False,
                )
                con.execute("""
                    INSERT INTO intake_promotion_runs (
                        promotion_id, intake_id, created_at, promoted_count,
                        direct_execution, gold_write, status, report_json
                    )
                    VALUES (?, ?, ?, ?, 0, 0, 'pending_review', ?)
                """, (
                    promotion_id,
                    selected_intake_id,
                    created_at,
                    len(promoted),
                    json.dumps(report, ensure_ascii=False),
                ))
                for layer, count in report["queued_layer_counts"].items():
                    con.execute("""
                        INSERT INTO intake_layer_counts (
                            promotion_id, target_layer, item_count
                        )
                        VALUES (?, ?, ?)
                    """, (promotion_id, layer, count))

        return report
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_INTAKE_DB))
    parser.add_argument("--intake-id", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    report = promote(Path(args.db), intake_id=args.intake_id, dry_run=args.dry_run)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
