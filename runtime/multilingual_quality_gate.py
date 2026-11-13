"""Bounded, provider-free multilingual training and Chat QA.

Only checks structural contracts. Does not approve semantics, train models, write
project data, or certify that a whole corpus is leakage-free.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter
from typing import Any

SPLITS = ("train", "validation", "test")
LANGUAGE_TAG = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
WORDS = re.compile(r"\w+", re.UNICODE)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _search_view(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _finish(blockers: list[str], **details: Any) -> dict[str, Any]:
    return {
        "state": "HOLD" if blockers else "PASS",
        "evidence_state": "UNPROVEN" if blockers else "VERIFIED_BOUNDED",
        "blockers": sorted(set(blockers)),
        **details,
    }


def audit_dataset(
    samples: Any,
    *,
    expected_counts: Any = None,
    max_records: int = 1000,
    max_pairs: int = 20000,
) -> dict[str, Any]:
    """Check exact/normalized/near split overlap and source lineage.

    Raw text is never returned. This is bounded; a truncated pair scan cannot
    produce PASS, and no full-corpus certification is implied.
    """
    if not isinstance(samples, list) or not samples:
        return _finish(["SAMPLES_REQUIRED"], observed_counts={}, languages={})
    if len(samples) > max_records:
        return {
            "state": "NOT_VERIFIED", "evidence_state": "UNPROVEN",
            "blockers": ["DATASET_BOUND_EXCEEDED"], "sample_count": len(samples),
            "max_records": max_records,
        }

    problems: list[str] = []
    observed = Counter({name: 0 for name in SPLITS})
    languages: Counter[str] = Counter()
    identities: set[str] = set()
    groups: dict[tuple[str, str], tuple[str, str]] = {}
    normalized: dict[str, tuple[str, str, str]] = {}
    valid: list[tuple[str, str, set[str]]] = []
    records: list[dict[str, Any]] = []

    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            problems.append(f"SAMPLE_NOT_OBJECT:{index}")
            continue
        sample_id, source_id, text = (
            sample.get("sample_id"), sample.get("source_id"), sample.get("text")
        )
        split = sample.get("split")
        language = sample.get("language", "und")
        if not isinstance(sample_id, str) or not sample_id.strip():
            problems.append(f"SAMPLE_ID_REQUIRED:{index}")
            continue
        if sample_id in identities:
            problems.append(f"DUPLICATE_SAMPLE_ID:{sample_id}")
        identities.add(sample_id)
        if not isinstance(source_id, str) or not source_id.strip():
            problems.append(f"SOURCE_ID_REQUIRED:{sample_id}")
            continue
        if split not in SPLITS:
            problems.append(f"SPLIT_INVALID:{sample_id}")
            continue
        if not isinstance(language, str) or not LANGUAGE_TAG.fullmatch(language):
            problems.append(f"LANGUAGE_TAG_INVALID:{sample_id}")
            continue
        if not isinstance(text, str) or not text.strip():
            problems.append(f"TEXT_REQUIRED:{sample_id}")
            continue
        for field in ("conversation_id", "family_id", "transit_id"):
            value = sample.get(field)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                problems.append(f"{field.upper()}_INVALID:{sample_id}")
        observed[split] += 1
        languages[language.split("-")[0]] += 1
        for kind, value in (
            ("source", source_id),
            ("conversation", sample.get("conversation_id")),
            ("family", sample.get("family_id")),
        ):
            if value is None or not isinstance(value, str) or not value.strip():
                continue
            key = (kind, value)
            previous = groups.setdefault(key, (split, sample_id))
            if previous[0] != split:
                problems.append(f"CROSS_SPLIT_{kind.upper()}:{previous[1]}:{sample_id}")

        view = _search_view(text)
        view_hash, raw_hash = _hash(view), _hash(text)
        prior = normalized.setdefault(view_hash, (split, sample_id, raw_hash))
        if prior[0] != split:
            kind = "EXACT" if prior[2] == raw_hash else "NORMALIZED"
            problems.append(f"CROSS_SPLIT_{kind}_TEXT:{prior[1]}:{sample_id}")
        valid.append((split, sample_id, set(WORDS.findall(view))))
        records.append({
            "sample_id": sample_id, "source_id": source_id,
            "transit_id": sample.get("transit_id"), "split": split,
            "language": language, "text_sha256": raw_hash,
            "text_length": len(text),
        })

    if expected_counts is not None:
        if (not isinstance(expected_counts, dict)
            or set(expected_counts) != set(SPLITS)
            or any(type(expected_counts[name]) is not int or expected_counts[name] < 1 for name in SPLITS)):
            problems.append("EXPECTED_SPLIT_COUNTS_INVALID")
        else:
            for name in SPLITS:
                if observed[name] != expected_counts[name]:
                    problems.append(f"SPLIT_COUNT_MISMATCH:{name}")

    pairs_scanned = 0
    for index, (split, sample_id, words) in enumerate(valid):
        for other_split, other_id, other_words in valid[index + 1:]:
            if split == other_split or len(words) < 5 or len(other_words) < 5:
                continue
            pairs_scanned += 1
            if pairs_scanned > max_pairs:
                return {
                    "state": "NOT_VERIFIED", "evidence_state": "UNPROVEN",
                    "blockers": sorted(set(problems + ["NEAR_DUPLICATE_SCAN_INCOMPLETE"])),
                    "observed_counts": dict(observed), "languages": dict(languages),
                    "pairs_scanned": pairs_scanned, "sample_receipts": records,
                }
            overlap = len(words & other_words) / len(words | other_words)
            if overlap >= 0.88:
                problems.append(f"CROSS_SPLIT_NEAR_DUPLICATE:{sample_id}:{other_id}")

    return _finish(
        problems, observed_counts=dict(observed), languages=dict(languages),
        pairs_scanned=pairs_scanned, sample_receipts=records,
        scope="OBSERVED_BATCH_ONLY",
        completeness="COUNTS_COMPARED" if expected_counts is not None else "NOT_VERIFIED",
    )


def audit_sft_labels(labels: Any, *, expected_train_samples: int) -> dict[str, Any]:
    """Check causal-LM targets after the one-token shift, without PyTorch."""
    if not isinstance(labels, list) or len(labels) != expected_train_samples:
        return _finish(["TRAIN_LABEL_COUNT_MISMATCH"], supervised_targets=0)
    problems: list[str] = []
    supervised = 0
    for index, sequence in enumerate(labels):
        if (not isinstance(sequence, list) or len(sequence) < 2
            or any(type(value) is not int for value in sequence)):
            problems.append(f"TRAIN_LABELS_INVALID:{index}")
            continue
        usable = sum(value != -100 for value in sequence[1:])
        supervised += usable
        if usable == 0:
            problems.append(f"ZERO_SUPERVISED_TARGETS:{index}")
    return _finish(problems, supervised_targets=supervised, checked_sequences=len(labels))


def audit_training_preflight(package: Any) -> dict[str, Any]:
    """Optional, bounded pre-execution quality gate for the existing pipeline."""
    if not isinstance(package, dict) or "expected_split_counts" not in package:
        return _finish(["PREFLIGHT_EXPECTED_COUNTS_REQUIRED"])
    dataset = audit_dataset(
        package.get("samples"), expected_counts=package["expected_split_counts"]
    )
    labels = audit_sft_labels(
        package.get("train_labels"),
        expected_train_samples=dataset.get("observed_counts", {}).get("train", 0),
    )
    problems = dataset["blockers"] + labels["blockers"]
    required = package.get("required_languages", [])
    if not isinstance(required, list) or any(
        not isinstance(code, str) or not LANGUAGE_TAG.fullmatch(code) for code in required
    ):
        problems.append("REQUIRED_LANGUAGES_INVALID")
    else:
        covered = dataset.get("languages", {})
        for code in required:
            if covered.get(code.split("-")[0], 0) == 0:
                problems.append(f"LANGUAGE_NOT_OBSERVED:{code}")
    if dataset["state"] == "NOT_VERIFIED":
        return {
            "state": "NOT_VERIFIED", "evidence_state": "UNPROVEN",
            "blockers": sorted(set(problems)), "dataset": dataset, "sft_labels": labels,
        }
    return _finish(problems, dataset=dataset, sft_labels=labels)


def audit_evaluation_groups(groups: Any) -> dict[str, Any]:
    """Ensure each named evaluation group has complete, finite metrics."""
    if not isinstance(groups, dict) or not groups:
        return _finish(["EVALUATION_GROUPS_REQUIRED"])
    problems: list[str] = []
    for name, group in groups.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(group, dict):
            problems.append("EVALUATION_GROUP_INVALID")
            continue
        expected, actual, metrics = group.get("expected"), group.get("actual"), group.get("metrics")
        if type(expected) is not int or type(actual) is not int or expected < 1 or expected != actual:
            problems.append(f"EVALUATION_COUNT_MISMATCH:{name}")
        if not isinstance(metrics, dict) or not metrics:
            problems.append(f"EVALUATION_METRICS_REQUIRED:{name}")
        else:
            for key, value in metrics.items():
                if not isinstance(key, str) or not key.strip() or not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                    problems.append(f"EVALUATION_METRIC_INVALID:{name}")
                    break
    return _finish(problems, checked_groups=list(groups))


def audit_chat_response(request: Any, response: Any) -> dict[str, Any]:
    """Check reply completeness and cache identity, never tool authorization."""
    if not isinstance(request, dict) or not isinstance(response, dict):
        return _finish(["CHAT_REQUEST_AND_RESPONSE_REQUIRED"], tool_execution_authorized=False)
    problems: list[str] = []
    for field in ("session_id", "model_sha256", "tokenizer_sha256"):
        value = request.get(field)
        if not isinstance(value, str) or not value:
            problems.append(f"CHAT_{field.upper()}_REQUIRED")
        elif response.get(field) != value:
            problems.append(f"CHAT_{field.upper()}_MISMATCH")
    messages = request.get("messages")
    if not isinstance(messages, list) or not messages or any(
        not isinstance(item, dict) or item.get("role") not in {"system", "user", "assistant", "tool"}
        or not isinstance(item.get("content"), str) for item in messages
    ):
        problems.append("CHAT_MESSAGES_INVALID")
    if response.get("status_code") != 200:
        problems.append("CHAT_REQUEST_NOT_SUCCESSFUL")
    finish = response.get("finish_reason")
    if finish not in ("stop", "tool_calls"):
        problems.append("CHAT_REPLY_INCOMPLETE")
    content = response.get("content")
    calls = response.get("tool_calls")
    if not isinstance(content, str):
        problems.append("CHAT_CONTENT_INVALID")
    elif not content and not (finish == "tool_calls" and isinstance(calls, list) and calls):
        problems.append("CHAT_EMPTY_SUCCESS_RESPONSE")
    if "stream_chunks" in response:
        chunks = response["stream_chunks"]
        if not isinstance(chunks, list) or any(not isinstance(c, str) for c in chunks):
            problems.append("CHAT_STREAM_INVALID")
        elif isinstance(content, str) and "".join(chunks) != content:
            problems.append("CHAT_STREAM_CONTENT_MISMATCH")
    return _finish(problems, tool_execution_authorized=False, scope="CHAT_STRUCTURE_ONLY")
