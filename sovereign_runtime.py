#!/usr/bin/env python3
"""Local, persistent Nova/FSX/ONE_RUN/stations runtime."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import tempfile
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO


class RuntimeErrorState(Exception):
    """A runtime operation could not safely complete."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _token(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeErrorState(f"STATE_FILE_CORRUPT:{path}") from exc


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _is_within(child: Path, root: Path) -> bool:
    try:
        child.relative_to(root)
        return True
    except ValueError:
        return False


class SovereignRuntime:
    """Filesystem-backed runtime primitives; execution is opt-in and ticket-gated."""

    def __init__(
        self,
        runtime_root: str | Path | None = None,
        allowed_roots: list[str | Path] | None = None,
        *,
        max_output_bytes: int = 1_000_000,
    ) -> None:
        root = Path(
            runtime_root
            or os.environ.get("NOVADESK_RUNTIME_ROOT", Path.cwd() / ".runtime_data")
        ).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve(strict=True)
        configured = allowed_roots
        if configured is None:
            env_roots = os.environ.get("NOVADESK_ALLOWED_ROOTS")
            configured = (
                [item for item in env_roots.split(os.pathsep) if item]
                if env_roots
                else [Path.cwd()]
            )
        self.allowed_roots = [Path(item).expanduser().resolve(strict=True) for item in configured]
        if not self.allowed_roots:
            raise ValueError("AT_LEAST_ONE_ALLOWED_ROOT_REQUIRED")
        if type(max_output_bytes) is not int or max_output_bytes < 1:
            raise ValueError("MAX_OUTPUT_BYTES_MUST_BE_POSITIVE")
        self.max_output_bytes = max_output_bytes
        self._lock = threading.RLock()
        self.paths = {
            "sources": self.root / "nova" / "sources.json",
            "tickets": self.root / "nova" / "tickets.json",
            "counters": self.root / "nova" / "transit_counters.json",
            "fsx_current": self.root / "fsx" / "current.json",
            "fsx_events": self.root / "fsx" / "events.jsonl",
            "one_run": self.root / "one_run",
            "evidence": self.root / "evidence",
            "warehouse": self.root / "warehouse35" / "registry.json",
        }
        for key in ("one_run", "evidence"):
            self.paths[key].mkdir(parents=True, exist_ok=True)
        for key in ("sources", "tickets", "counters", "fsx_current", "fsx_events", "warehouse"):
            self.paths[key].parent.mkdir(parents=True, exist_ok=True)

    def assert_allowed_path(self, target: str | Path, *, must_exist: bool = True) -> Path:
        requested = Path(target).expanduser()
        if requested.is_symlink():
            raise RuntimeErrorState("PATH_SYMLINK_NOT_ALLOWED")
        try:
            resolved = requested.resolve(strict=must_exist)
        except OSError as exc:
            raise RuntimeErrorState(f"PATH_NOT_FOUND:{requested}") from exc
        if not any(_is_within(resolved, root) for root in self.allowed_roots):
            raise RuntimeErrorState(f"PATH_NOT_ALLOWED:{resolved}")
        return resolved

    @staticmethod
    def _transit_prefix(extension: str) -> str:
        ext = extension.lower()
        if ext == ".pdf":
            return "Pdf"
        if ext in {".doc", ".docx", ".odt"}:
            return "Word"
        if ext in {".txt", ".md", ".rst"}:
            return "Txt"
        if ext in {".py", ".pyw"}:
            return "Py"
        if ext in {".xls", ".xlsx", ".csv", ".ods"}:
            return "Excel"
        if ext in {".wav", ".mp3", ".m4a", ".flac", ".ogg"}:
            return "Wav"
        if ext in {".mp4", ".mov", ".mkv", ".avi", ".webm"}:
            return "Mp4"
        if ext in {".sqlite", ".sqlite3", ".db"}:
            return "Sqlite"
        if ext in {".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz"}:
            return "NewSystem"
        return "File"

    @staticmethod
    def _transit_number(number: int) -> str:
        digits = str(number).zfill(9)
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"

    def _next_transit_id(self, extension: str) -> str:
        counters = _read_json(self.paths["counters"], {})
        prefix = self._transit_prefix(extension)
        counters[prefix] = int(counters.get(prefix, 0)) + 1
        _write_json_atomic(self.paths["counters"], counters)
        return f"{prefix}-{self._transit_number(counters[prefix])}"

    def _list(self, name: str) -> list[dict[str, Any]]:
        value = _read_json(self.paths[name], [])
        if not isinstance(value, list):
            raise RuntimeErrorState(f"STATE_FILE_INVALID:{name}")
        return value

    def intake_local(self, source_path: str | Path) -> dict[str, dict[str, Any]]:
        resolved = self.assert_allowed_path(source_path)
        if not resolved.is_file():
            raise RuntimeErrorState("SOURCE_MUST_BE_FILE")
        stat = resolved.stat()
        digest = sha256_file(resolved)
        identity = f"{resolved}|{stat.st_dev}|{stat.st_ino}|{stat.st_birthtime if hasattr(stat, 'st_birthtime') else stat.st_ctime}"
        source_id = "SRC-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24].upper()

        with self._lock:
            sources = self._list("sources")
            source = next((item for item in sources if item["source_id"] == source_id), None)
            if source is None:
                source = {
                    "source_id": source_id,
                    "transit_id": self._next_transit_id(resolved.suffix),
                    "source_name": resolved.name,
                    "source_path": str(resolved),
                    "extension": resolved.suffix.lower(),
                    "size_bytes": stat.st_size,
                    "sha256": digest,
                    "source_action": "READ_ONLY",
                    "state": "OBSERVED",
                    "created_at": _now(),
                }
                sources.append(source)
                _write_json_atomic(self.paths["sources"], sources)
            elif source["sha256"] != digest or source["size_bytes"] != stat.st_size:
                source.update(
                    sha256=digest,
                    size_bytes=stat.st_size,
                    state="OBSERVED",
                    updated_at=_now(),
                )
                _write_json_atomic(self.paths["sources"], sources)

            ticket = {
                "ticket_id": _token("TKT"),
                "source_id": source["source_id"],
                "transit_id": source["transit_id"],
                "operation": "READ_ONLY_INSPECTION",
                "capability": "FILESYSTEM_INSPECTION",
                "status": "CREATED",
                "created_at": _now(),
            }
            tickets = self._list("tickets")
            tickets.append(ticket)
            _write_json_atomic(self.paths["tickets"], tickets)

        self.emit(
            flow_id=_token("FLOW"),
            entity_id=source_id,
            source_id=source_id,
            transit_id=source["transit_id"],
            to_state="OBSERVED",
            to_station="NOVA",
            operation="NOVA_INTAKE",
            output_ref=str(resolved),
            sha256_after=digest,
            ticket_id=ticket["ticket_id"],
        )
        return {"source": source, "ticket": ticket}

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        return next((item for item in self._list("sources") if item["source_id"] == source_id), None)

    def get_ticket(self, ticket_id: str) -> dict[str, Any] | None:
        return next((item for item in self._list("tickets") if item["ticket_id"] == ticket_id), None)

    def create_ticket(
        self, source_id: str, operation: str, capability: str
    ) -> dict[str, Any]:
        source = self.get_source(source_id)
        if source is None:
            raise RuntimeErrorState("SOURCE_NOT_FOUND")
        allowed_capabilities = {
            "READ_ONLY_INSPECTION": "FILESYSTEM_INSPECTION",
            "ONE_RUN": "TERMINAL_EXECUTION",
        }
        if allowed_capabilities.get(operation) != capability:
            raise RuntimeErrorState("OPERATION_CAPABILITY_MISMATCH")
        ticket = {
            "ticket_id": _token("TKT"),
            "source_id": source_id,
            "transit_id": source["transit_id"],
            "operation": operation,
            "capability": capability,
            "status": "CREATED",
            "created_at": _now(),
        }
        with self._lock:
            tickets = self._list("tickets")
            tickets.append(ticket)
            _write_json_atomic(self.paths["tickets"], tickets)
        return ticket

    def authorize_ticket(self, ticket_id: str, authorized_by: str) -> dict[str, Any]:
        if not authorized_by.strip():
            raise RuntimeErrorState("AUTHORIZED_BY_REQUIRED")
        with self._lock:
            tickets = self._list("tickets")
            ticket = next((item for item in tickets if item["ticket_id"] == ticket_id), None)
            if ticket is None:
                raise RuntimeErrorState("TICKET_NOT_FOUND")
            if ticket["status"] != "CREATED":
                raise RuntimeErrorState(f"TICKET_CANNOT_BE_AUTHORIZED:{ticket['status']}")
            ticket.update(status="AUTHORIZED", authorized_at=_now(), authorized_by=authorized_by)
            _write_json_atomic(self.paths["tickets"], tickets)
        current = self.current(ticket["source_id"])
        self.emit(
            flow_id=current["flow_id"] if current else _token("FLOW"),
            entity_id=ticket["source_id"],
            source_id=ticket["source_id"],
            transit_id=ticket["transit_id"],
            from_state="OBSERVED",
            to_state="OBSERVED",
            operation="BOSS_TICKET_AUTHORIZED",
            ticket_id=ticket_id,
            agent_id="BOSS",
        )
        return ticket

    def emit(
        self,
        *,
        flow_id: str,
        entity_id: str,
        to_state: str,
        operation: str,
        source_id: str | None = None,
        transit_id: str | None = None,
        from_state: str | None = None,
        from_station: str | None = None,
        to_station: str | None = None,
        workspace_id: str | None = None,
        zone_id: str | None = None,
        agent_id: str | None = None,
        input_ref: str | None = None,
        output_ref: str | None = None,
        sha256_before: str | None = None,
        sha256_after: str | None = None,
        evidence_id: str | None = None,
        run_id: str | None = None,
        ticket_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            current = _read_json(self.paths["fsx_current"], {})
            previous = current.get(entity_id)
            event = {
                "event_id": _token("EVT"),
                "flow_id": flow_id,
                "entity_id": entity_id,
                "source_id": source_id or (previous or {}).get("source_id"),
                "transit_id": transit_id or (previous or {}).get("transit_id"),
                "sequence_no": (previous or {}).get("sequence_no", 0) + 1,
                "from_state": from_state or (previous or {}).get("current_state"),
                "to_state": to_state,
                "from_station": from_station,
                "to_station": to_station or (previous or {}).get("current_station"),
                "workspace_id": workspace_id or (previous or {}).get("workspace_id"),
                "zone_id": zone_id or (previous or {}).get("zone_id"),
                "agent_id": agent_id or (previous or {}).get("agent_id"),
                "operation": operation,
                "input_ref": input_ref,
                "output_ref": output_ref,
                "sha256_before": sha256_before,
                "sha256_after": sha256_after,
                "evidence_id": evidence_id,
                "run_id": run_id,
                "ticket_id": ticket_id,
                "timestamp": _now(),
            }
            current[entity_id] = {
                "entity_id": entity_id,
                "source_id": event["source_id"],
                "transit_id": event["transit_id"],
                "flow_id": flow_id,
                "sequence_no": event["sequence_no"],
                "current_state": to_state,
                "current_station": event["to_station"],
                "workspace_id": event["workspace_id"],
                "zone_id": event["zone_id"],
                "agent_id": event["agent_id"],
                "artifact_id": None,
                "unit_id": None,
                "payload_pointer": output_ref or (previous or {}).get("payload_pointer"),
                "sha256": sha256_after or (previous or {}).get("sha256"),
                "evidence_id": evidence_id or (previous or {}).get("evidence_id"),
                "run_id": run_id or (previous or {}).get("run_id"),
                "ticket_id": ticket_id or (previous or {}).get("ticket_id"),
                "updated_at": event["timestamp"],
            }
            _append_jsonl(self.paths["fsx_events"], event)
            _write_json_atomic(self.paths["fsx_current"], current)
            return event

    def current(self, entity_id: str | None = None) -> Any:
        records = _read_json(self.paths["fsx_current"], {})
        return records.get(entity_id) if entity_id else records

    def events(self, entity_id: str | None = None) -> list[dict[str, Any]]:
        try:
            lines = self.paths["fsx_events"].read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        events = []
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeErrorState("FSX_EVENT_LOG_CORRUPT") from exc
            if entity_id is None or event["entity_id"] == entity_id:
                events.append(event)
        return events

    def verify_ticket(
        self, *, ticket_id: str, source_id: str, operation: str, command: str, cwd: str | Path
    ) -> dict[str, Any]:
        blockers: list[str] = []
        ticket = self.get_ticket(ticket_id)
        if ticket is None:
            blockers.append("TICKET_NOT_FOUND")
        else:
            if ticket["source_id"] != source_id:
                blockers.append("SOURCE_TICKET_MISMATCH")
            if ticket["status"] != "AUTHORIZED":
                blockers.append("TICKET_NOT_AUTHORIZED")
        if not operation.strip():
            blockers.append("OPERATION_REQUIRED")
        elif ticket and ticket.get("operation") != operation:
            blockers.append("TICKET_OPERATION_MISMATCH")
        if operation == "ONE_RUN" and ticket and ticket.get("capability") != "TERMINAL_EXECUTION":
            blockers.append("TICKET_CAPABILITY_MISMATCH")
        try:
            self.assert_allowed_path(cwd)
        except RuntimeErrorState:
            blockers.append("WORKSPACE_NOT_ALLOWED")

        allowed = {
            item.strip().lower()
            for item in os.environ.get(
                "NOVADESK_ALLOWED_COMMANDS", "python,python3,pytest"
            ).split(",")
            if item.strip()
        }
        executable = Path(command).name.lower().removesuffix(".exe")
        if executable not in allowed:
            blockers.append(f"COMMAND_NOT_ALLOWED:{executable}")
        return {
            "state": "READY" if not blockers else "BLOCKED",
            "blockers": blockers,
            "ticket": ticket,
        }

    @staticmethod
    def _capture(stream: BinaryIO, limit: int) -> tuple[bytes, str, bool]:
        digest = hashlib.sha256()
        captured = bytearray()
        truncated = False
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            digest.update(chunk)
            remaining = limit - len(captured)
            if remaining > 0:
                captured.extend(chunk[:remaining])
            if len(chunk) > remaining:
                truncated = True
        return bytes(captured), digest.hexdigest(), truncated

    def _make_shadow_workspace(self, workspace: Path) -> Path:
        shadow_root = self.root / "shadow"
        shadow_root.mkdir(parents=True, exist_ok=True)
        shadow = Path(tempfile.mkdtemp(prefix="one_run_", dir=shadow_root))
        copied_files = 0
        copied_bytes = 0
        try:
            for current, dirs, names in os.walk(workspace, followlinks=False):
                base = Path(current)
                dirs[:] = sorted(
                    name
                    for name in dirs
                    if not (base / name).is_symlink()
                    and not _is_within((base / name).resolve(), self.root)
                )
                relative_dir = base.relative_to(workspace)
                (shadow / relative_dir).mkdir(parents=True, exist_ok=True)
                for name in sorted(names):
                    source = base / name
                    if source.is_symlink() or not source.is_file():
                        continue
                    size = source.stat().st_size
                    copied_files += 1
                    copied_bytes += size
                    if copied_files > 2_000 or copied_bytes > 100_000_000:
                        raise RuntimeErrorState("SHADOW_WORKSPACE_LIMIT_EXCEEDED")
                    destination = shadow / source.relative_to(workspace)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
            return shadow
        except (OSError, RuntimeErrorState):
            shutil.rmtree(shadow, ignore_errors=True)
            raise

    @staticmethod
    def _map_shadow_arguments(arguments: list[str], workspace: Path, shadow: Path) -> list[str]:
        mapped: list[str] = []
        for argument in arguments:
            candidate = Path(argument).expanduser()
            if not candidate.is_absolute():
                mapped.append(argument)
                continue
            resolved = candidate.resolve(strict=False)
            if not _is_within(resolved, workspace):
                raise RuntimeErrorState("ABSOLUTE_ARGUMENT_OUTSIDE_SHADOW")
            mapped.append(str(shadow / resolved.relative_to(workspace)))
        return mapped

    def run_one(
        self,
        *,
        ticket_id: str,
        source_id: str,
        command: str,
        args: list[str] | None = None,
        cwd: str | Path,
        timeout_seconds: int = 120,
        workspace_id: str | None = None,
        zone_id: str | None = None,
    ) -> dict[str, Any]:
        source = self.get_source(source_id)
        if source is None:
            raise RuntimeErrorState("SOURCE_NOT_FOUND")
        workspace = self.assert_allowed_path(cwd)
        if not workspace.is_dir():
            raise RuntimeErrorState("WORKSPACE_MUST_BE_DIRECTORY")
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 900:
            raise RuntimeErrorState("TIMEOUT_OUT_OF_RANGE")
        arguments = list(args or [])
        if len(arguments) > 100 or any("\0" in item for item in arguments):
            raise RuntimeErrorState("INVALID_COMMAND_ARGUMENTS")

        run_id, evidence_id = _token("RUN"), _token("EVD")
        started = _now()
        gate = self.verify_ticket(
            ticket_id=ticket_id,
            source_id=source_id,
            operation="ONE_RUN",
            command=command,
            cwd=workspace,
        )
        if gate["state"] != "READY":
            receipt = {
                "run_id": run_id,
                "source_id": source_id,
                "transit_id": source["transit_id"],
                "ticket_id": ticket_id,
                "command": command,
                "args": arguments,
                "cwd": str(workspace),
                "started_at": started,
                "ended_at": _now(),
                "one_agent_status": "BLOCKED",
                "boss_status": "BLOCKED",
                "shadow_status": "NOT_STARTED",
                "terminal_agent_status": "NOT_STARTED",
                "exit_code": None,
                "timed_out": False,
                "stdout_sha256": _sha256_bytes(b""),
                "stderr_sha256": _sha256_bytes("\n".join(gate["blockers"]).encode()),
                "evidence_id": evidence_id,
                "evidence_path": None,
                "readback_verified": False,
                "errors": gate["blockers"],
                "warnings": [],
                "final_state": "HOLD",
            }
            self.emit(
                flow_id=_token("FLOW"),
                entity_id=source_id,
                source_id=source_id,
                transit_id=source["transit_id"],
                to_state="HOLD",
                to_station="ONE_RUN",
                operation="ONE_RUN_BLOCKED",
                agent_id="SHADOW",
                run_id=run_id,
                ticket_id=ticket_id,
                evidence_id=evidence_id,
            )
            return receipt

        self.emit(
            flow_id=_token("FLOW"),
            entity_id=source_id,
            source_id=source_id,
            transit_id=source["transit_id"],
            to_state="RUNNING",
            to_station="ONE_RUN",
            operation="ONE_RUN_STARTED",
            workspace_id=workspace_id,
            zone_id=zone_id,
            agent_id="SHADOW",
            run_id=run_id,
            ticket_id=ticket_id,
        )

        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {
                "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR",
                "HOME", "USERPROFILE", "PATHEXT", "COMSPEC",
            }
        }
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        timed_out = False
        terminal_error = None
        shadow_workspace: Path | None = None
        exit_code = None
        stdout = b""
        stderr = b""
        stdout_hash = _sha256_bytes(b"")
        stderr_hash = _sha256_bytes(b"")
        stdout_truncated = stderr_truncated = False
        started_monotonic = time.monotonic()
        try:
            shadow_workspace = self._make_shadow_workspace(workspace)
            shadow_arguments = self._map_shadow_arguments(arguments, workspace, shadow_workspace)
            process = subprocess.Popen(
                [command, *shadow_arguments],
                cwd=shadow_workspace,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                close_fds=True,
                **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
            )
            assert process.stdout is not None and process.stderr is not None
            out_result: list[Any] = []
            err_result: list[Any] = []
            out_thread = threading.Thread(
                target=lambda: out_result.append(self._capture(process.stdout, self.max_output_bytes)),
                daemon=True,
            )
            err_thread = threading.Thread(
                target=lambda: err_result.append(self._capture(process.stderr, self.max_output_bytes)),
                daemon=True,
            )
            out_thread.start()
            err_thread.start()
            try:
                exit_code = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                exit_code = process.wait()
            out_thread.join()
            err_thread.join()
            stdout, stdout_hash, stdout_truncated = out_result[0]
            stderr, stderr_hash, stderr_truncated = err_result[0]
            process.stdout.close()
            process.stderr.close()
        except (OSError, RuntimeErrorState) as exc:
            terminal_error = f"{type(exc).__name__}:{exc}"
        finally:
            if shadow_workspace is not None:
                try:
                    shutil.rmtree(shadow_workspace)
                except OSError as exc:
                    terminal_error = terminal_error or f"SHADOW_CLEANUP_FAILED:{exc}"
        duration = round(time.monotonic() - started_monotonic, 3)

        errors = []
        if terminal_error:
            errors.append(terminal_error)
        if timed_out:
            errors.append("TIMEOUT")
        if exit_code != 0:
            errors.append(f"NON_ZERO_EXIT:{exit_code}")
        evidence = {
            "evidence_id": evidence_id,
            "run_id": run_id,
            "source_id": source_id,
            "transit_id": source["transit_id"],
            "ticket_id": ticket_id,
            "command": command,
            "args": arguments,
            "cwd": str(workspace),
            "shadow_workspace": str(shadow_workspace) if shadow_workspace else None,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "stdout_sha256": stdout_hash,
            "stderr_sha256": stderr_hash,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "terminal_error": terminal_error,
            "duration_seconds": duration,
            "captured_at": _now(),
        }
        evidence_path = self.paths["evidence"] / f"{evidence_id}.json"
        _write_json_atomic(evidence_path, evidence)
        evidence_file_hash = sha256_file(evidence_path)
        try:
            readback_verified = _read_json(evidence_path, None) == evidence
        except RuntimeErrorState:
            readback_verified = False
        if not readback_verified:
            errors.append("EVIDENCE_READBACK_FAILED")
        passed = exit_code == 0 and not timed_out and terminal_error is None and readback_verified
        final_state = "PASS" if passed else "MAINTENANCE_REQUIRED"
        receipt = {
            "run_id": run_id,
            "source_id": source_id,
            "transit_id": source["transit_id"],
            "ticket_id": ticket_id,
            "command": command,
            "args": arguments,
            "cwd": str(workspace),
            "started_at": started,
            "ended_at": _now(),
            "one_agent_status": "PASS",
            "boss_status": "AUTHORIZED",
            "shadow_status": "PASS" if passed else "FAIL",
            "terminal_agent_status": "PASS" if passed else "FAIL",
            "exit_code": exit_code,
            "timed_out": timed_out,
            "stdout_sha256": stdout_hash,
            "stderr_sha256": stderr_hash,
            "evidence_id": evidence_id,
            "evidence_path": str(evidence_path),
            "evidence_sha256": evidence_file_hash,
            "shadow_workspace": str(shadow_workspace) if shadow_workspace else None,
            "readback_verified": readback_verified,
            "errors": errors,
            "warnings": [
                warning
                for warning, truncated in (
                    ("STDOUT_TRUNCATED", stdout_truncated),
                    ("STDERR_TRUNCATED", stderr_truncated),
                )
                if truncated
            ],
            "final_state": final_state,
        }
        receipt_path = self.paths["one_run"] / f"{run_id}.json"
        _write_json_atomic(receipt_path, receipt)
        self.emit(
            flow_id=_token("FLOW"),
            entity_id=source_id,
            source_id=source_id,
            transit_id=source["transit_id"],
            from_state="RUNNING",
            to_state=final_state,
            from_station="ONE_RUN",
            to_station="STATION_01" if passed else "MAINTENANCE",
            workspace_id=workspace_id,
            zone_id=zone_id,
            agent_id="SHADOW",
            operation="ONE_RUN_PASS" if passed else "ONE_RUN_FAIL",
            input_ref=source["source_path"],
            output_ref=str(receipt_path),
            sha256_before=source["sha256"],
            sha256_after=source["sha256"],
            evidence_id=evidence_id,
            run_id=run_id,
            ticket_id=ticket_id,
        )
        return receipt

    def transition_station(
        self,
        *,
        source_id: str,
        station: int,
        state: str,
        operation: str,
        evidence_id: str | None = None,
        run_id: str | None = None,
        ticket_id: str | None = None,
        workspace_id: str | None = None,
        zone_id: str | None = None,
        agent_id: str | None = None,
        output_ref: str | None = None,
    ) -> dict[str, Any]:
        if type(station) is not int or not 1 <= station <= 7:
            raise RuntimeErrorState("STATION_MUST_BE_1_TO_7")
        if state not in {"RUNNING", "PASS", "FAIL", "HOLD", "NOT_VERIFIED", "NEEDS_CONTEXT", "MAINTENANCE_REQUIRED"}:
            raise RuntimeErrorState("INVALID_STATION_STATE")
        source = self.get_source(source_id)
        if source is None:
            raise RuntimeErrorState("SOURCE_NOT_FOUND")
        current = self.current(source_id)
        station_name = f"STATION_{station:02d}"
        if state == "RUNNING":
            if station == 1:
                if not current or current["current_station"] != "STATION_01" or current["current_state"] != "PASS":
                    raise RuntimeErrorState("STATION_01_REQUIRES_ONE_RUN_PASS")
            else:
                expected_previous = f"STATION_{station - 1:02d}"
                if not current or current["current_station"] != expected_previous or current["current_state"] != "PASS":
                    raise RuntimeErrorState(f"STATION_{station:02d}_REQUIRES_{expected_previous}_PASS")
        else:
            if not current or current["current_station"] != station_name or current["current_state"] != "RUNNING":
                raise RuntimeErrorState(f"{station_name}_REQUIRES_RUNNING_STATE")
        if state == "PASS" and not evidence_id:
            raise RuntimeErrorState("PASS_REQUIRES_EVIDENCE")
        if evidence_id and not (self.paths["evidence"] / f"{evidence_id}.json").is_file():
            raise RuntimeErrorState("EVIDENCE_NOT_FOUND")
        return self.emit(
            flow_id=(current or {}).get("flow_id") or _token("FLOW"),
            entity_id=source_id,
            source_id=source_id,
            transit_id=source["transit_id"],
            from_state=(current or {}).get("current_state", "OBSERVED"),
            to_state=state,
            from_station=(current or {}).get("current_station"),
            to_station=station_name,
            workspace_id=workspace_id,
            zone_id=zone_id,
            agent_id=agent_id,
            operation=operation,
            input_ref=source["source_path"],
            output_ref=output_ref,
            sha256_before=source["sha256"],
            sha256_after=source["sha256"],
            evidence_id=evidence_id,
            run_id=run_id,
            ticket_id=ticket_id,
        )

    def settle(
        self,
        *,
        source_id: str,
        unit_id: str,
        domain: str,
        payload_pointer: str,
        sha256: str,
        evidence_id: str,
        retrieval_point: str,
    ) -> dict[str, Any]:
        current = self.current(source_id)
        if not current or current["current_station"] != "STATION_07":
            raise RuntimeErrorState("SETTLEMENT_REQUIRES_STATION_07")
        if current["current_state"] not in {"PASS", "SETTLED"}:
            raise RuntimeErrorState("SETTLEMENT_REQUIRES_VERIFIED_STATE")
        if not all(value.strip() for value in (unit_id, domain, payload_pointer, retrieval_point)):
            raise RuntimeErrorState("SETTLEMENT_FIELDS_REQUIRED")
        evidence_path = self.paths["evidence"] / f"{evidence_id}.json"
        if not evidence_path.is_file():
            raise RuntimeErrorState("EVIDENCE_NOT_FOUND")
        if not current.get("run_id"):
            raise RuntimeErrorState("SETTLEMENT_REQUIRES_ONE_RUN")
        matching_receipt = self.paths["one_run"] / f"{current['run_id']}.json"
        if not matching_receipt.is_file():
            raise RuntimeErrorState("ONE_RUN_RECEIPT_NOT_FOUND")
        receipt = _read_json(matching_receipt, None)
        if receipt.get("evidence_id") != evidence_id or receipt.get("final_state") != "PASS":
            raise RuntimeErrorState("ONE_RUN_RECEIPT_NOT_PASS")
        if sha256_file(evidence_path) != receipt.get("evidence_sha256"):
            raise RuntimeErrorState("EVIDENCE_HASH_MISMATCH")
        evidence = _read_json(evidence_path, None)
        if evidence.get("source_id") != source_id:
            raise RuntimeErrorState("EVIDENCE_SOURCE_MISMATCH")
        if evidence.get("stdout_sha256") is None or evidence.get("exit_code") != 0 or evidence.get("timed_out"):
            raise RuntimeErrorState("EVIDENCE_NOT_PASS")
        registry = _read_json(self.paths["warehouse"], [])
        if not isinstance(registry, list):
            raise RuntimeErrorState("WAREHOUSE_REGISTRY_INVALID")
        record = {
            "settlement_id": _token("SET"),
            "source_id": source_id,
            "unit_id": unit_id,
            "domain": domain,
            "payload_pointer": payload_pointer,
            "sha256": sha256,
            "evidence_id": evidence_id,
            "retrieval_point": retrieval_point,
            "state": "SETTLED",
            "settled_at": _now(),
        }
        registry.append(record)
        _write_json_atomic(self.paths["warehouse"], registry)
        self.emit(
            flow_id=current["flow_id"],
            entity_id=source_id,
            source_id=source_id,
            transit_id=current.get("transit_id"),
            from_state=current["current_state"],
            to_state="SETTLED",
            from_station="STATION_07",
            to_station="WAREHOUSE_35",
            workspace_id=current.get("workspace_id"),
            zone_id=current.get("zone_id"),
            agent_id=current.get("agent_id"),
            operation="WAREHOUSE_SETTLEMENT",
            input_ref=payload_pointer,
            output_ref=retrieval_point,
            sha256_before=sha256,
            sha256_after=sha256,
            evidence_id=evidence_id,
            run_id=current.get("run_id"),
            ticket_id=current.get("ticket_id"),
        )
        return record

    def system_status(self) -> dict[str, Any]:
        return {
            "hostname": platform.node(),
            "platform": sys.platform,
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "runtime_root": str(self.root),
            "timestamp": _now(),
        }

    def scan_filesystem(self, root: str | Path, *, max_files: int = 20_000) -> dict[str, Any]:
        if type(max_files) is not int or not 1 <= max_files <= 100_000:
            raise RuntimeErrorState("MAX_FILES_OUT_OF_RANGE")
        resolved = self.assert_allowed_path(root)
        if not resolved.is_dir():
            raise RuntimeErrorState("SCAN_ROOT_MUST_BE_DIRECTORY")
        files = []
        truncated = False
        for current, dirs, names in os.walk(resolved, followlinks=False):
            base = Path(current)
            dirs[:] = sorted(name for name in dirs if not (base / name).is_symlink())
            dirs[:] = [
                name
                for name in dirs
                if not _is_within((base / name).resolve(), self.root)
            ]
            for name in sorted(names):
                item = base / name
                if item.is_symlink() or not item.is_file():
                    continue
                if len(files) >= max_files:
                    truncated = True
                    break
                result = self.intake_local(item)
                stat = item.stat()
                files.append(
                    {
                        "name": result["source"]["source_path"],
                        "size_bytes": result["source"]["size_bytes"],
                        "extension": result["source"]["extension"],
                        "sha256": result["source"]["sha256"],
                        "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                        "source_id": result["source"]["source_id"],
                        "transit_id": result["source"]["transit_id"],
                        "ticket_id": result["ticket"]["ticket_id"],
                    }
                )
            if truncated:
                break
        return {"success": True, "root": str(resolved), "total_files": len(files), "truncated": truncated, "files": files}


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Create a local Nova source record and inspection ticket.")
    parser.add_argument("source", nargs="?", help="File or directory to inspect.")
    parser.add_argument("--runtime-root", default=None)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)
    try:
        runtime = SovereignRuntime(args.runtime_root)
        if args.status:
            result = runtime.system_status()
        elif args.source:
            path = Path(args.source).expanduser()
            if path.is_dir():
                result = runtime.scan_filesystem(path)
            else:
                result = runtime.intake_local(path)
        else:
            parser.error("provide a source path or --status")
            return 2
    except (OSError, RuntimeErrorState, ValueError) as exc:
        print(f"Runtime operation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
