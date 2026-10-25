"""Built-in and optional format-reading capabilities."""

from __future__ import annotations

from typing import Any


CAPABILITIES: tuple[dict[str, Any], ...] = (
    {
        "capability_id": "TEXT_READ",
        "formats": (
            "txt", "md", "rst", "log", "py", "js", "jsx", "ts", "tsx",
            "java", "c", "h", "cpp", "hpp", "cs", "go", "rs", "php",
            "rb", "swift", "kt", "scala", "lua", "pl", "r", "html",
            "htm", "css", "xml", "json", "jsonl", "yaml", "yml", "toml",
            "ini", "cfg", "sql", "csv", "tsv",
        ),
        "provider": "PYTHON_BUILTINS",
        "mode": "LOCAL_NATIVE",
    },
    {
        "capability_id": "OFFICE_TEXT_READ",
        "formats": ("docx", "xlsx", "pptx", "odt", "ods", "odp"),
        "provider": "OOXML_ODF_ADAPTERS",
        "mode": "LOCAL_NATIVE",
    },
    {
        "capability_id": "PDF_TEXT_READ",
        "formats": ("pdf",),
        "provider": "PYPDF",
        "mode": "OPTIONAL_LIBRARY",
    },
    {
        "capability_id": "IMAGE_READ",
        "formats": ("png", "jpg", "jpeg", "bmp", "tif", "tiff", "webp", "gif"),
        "provider": "PILLOW",
        "mode": "OPTIONAL_LIBRARY",
    },
    {
        "capability_id": "IMAGE_OCR",
        "formats": ("png", "jpg", "jpeg", "bmp", "tif", "tiff", "webp"),
        "provider": "PYTESSERACT_AND_TESSERACT",
        "mode": "OPTIONAL_LOCAL_TOOL",
    },
    {
        "capability_id": "SQLITE_READ",
        "formats": ("sqlite", "sqlite3", "db"),
        "provider": "PYTHON_SQLITE3",
        "mode": "LOCAL_READ_ONLY",
    },
    {
        "capability_id": "ARCHIVE_INVENTORY",
        "formats": ("zip", "tar", "tgz", "gz", "bz2", "xz"),
        "provider": "PYTHON_ARCHIVE_READERS",
        "mode": "LOCAL_NATIVE",
    },
    {
        "capability_id": "AUDIO_METADATA",
        "formats": ("wav", "mp3", "m4a", "flac", "ogg"),
        "provider": "PYTHON_WAVE_OR_CONTAINER_PROBE",
        "mode": "LOCAL_PARTIAL",
    },
    {
        "capability_id": "VIDEO_METADATA",
        "formats": ("mp4", "mkv", "mov", "avi", "webm"),
        "provider": "CONTAINER_PROBE",
        "mode": "LOCAL_PARTIAL",
    },
    {
        "capability_id": "SPEECH_TRANSCRIPTION",
        "formats": ("wav", "mp3", "m4a", "flac", "ogg"),
        "provider": None,
        "mode": "NOT_IMPLEMENTED",
    },
    {
        "capability_id": "VIDEO_FRAME_EXTRACTION",
        "formats": ("mp4", "mkv", "mov", "avi", "webm"),
        "provider": None,
        "mode": "NOT_IMPLEMENTED",
    },
)


def capabilities_for(extension: str) -> list[dict[str, Any]]:
    normalized = extension.lower().lstrip(".")
    return [
        dict(capability)
        for capability in CAPABILITIES
        if normalized in capability["formats"]
    ]
