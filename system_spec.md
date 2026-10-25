# Universal File Intake and Readable Extraction

## Purpose

Build one independent system that accepts files from an extensible set of formats, identifies what each file actually contains, and produces a readable, traceable representation that can be reviewed and used by other systems.

This specification defines the file-ingestion idea only. It does not require Chat, Nova, ONE_RUN, the stations, or a warehouse to exist or be connected. Those systems may integrate later through documented inputs and outputs.

## Goals

- Accept individual files, folders, and archives without changing the originals.
- Identify file format from content as well as extension; retain the original name and extension.
- Extract readable text, tables, metadata, source structure, and media references using format-specific adapters.
- Use OCR or speech transcription when a document contains image or audio data rather than extractable text.
- Preserve provenance so every extracted item points back to its source and location.
- Keep useful ideas, code, inputs, outputs, explanations, and broken or incomplete material; extraction is not approval or execution.
- Allow each format adapter to be developed and tested independently.
- Make adding support for another format an adapter change, not a rewrite of the intake system.

## Non-goals

- Do not execute imported code, macros, scripts, or binaries during intake.
- Do not silently repair, rewrite, rename, or delete source files.
- Do not claim that unsupported or encrypted content was successfully understood.
- Do not force all content into fixed-size chunks. A useful unit may be a sentence, function, table, image, or larger coherent section.
- Do not require a single database, agent framework, OCR engine, or cloud provider.

## System boundary

```text
File / Folder / Archive
        |
        v
Intake Record + Source Fingerprint
        |
        v
Format Detection
        |
        v
Adapter Selection
        |
        +--> Text / Documents / PDF / OCR
        +--> Source Code / Configuration
        +--> Tables / Spreadsheets / Databases
        +--> Images / Audio / Video
        +--> Archives / System Packages
        |
        v
Normalized Readable Output + Evidence + Warnings
        |
        v
Reviewable, Reusable Candidate Units
```

Each adapter is an independent component with a stable contract. The intake runner coordinates adapters and records results; it does not contain format-specific extraction logic.

## Intake record

Every submitted source receives a record containing:

- `source_id`: stable identifier for the source record.
- `content_sha256`: fingerprint of the original bytes.
- `original_name`, `original_extension`, `detected_format`.
- `source_path` or caller-provided source reference.
- `size_bytes`, `media_type`, and intake timestamp.
- `container_source_id` and member path when the source came from an archive.
- `status`: `RECEIVED`, `PROCESSING`, `EXTRACTED`, `PARTIAL`, `UNSUPPORTED`, or `FAILED`.
- `adapter_id` and adapter version.
- Output references, warnings, and error details.

An extension is evidence, not authority. A ZIP file containing an application remains a ZIP container in the source record; its contents may separately be classified as code, documents, data, or a system.

## Adapter contract

Each adapter accepts a read-only source reference plus explicit limits and returns a structured result:

```json
{
  "status": "EXTRACTED",
  "format": "pdf",
  "readable_output": "extracted text or a reference to a generated output",
  "units": [],
  "evidence": [],
  "warnings": [],
  "errors": [],
  "metadata": {}
}
```

Adapters must:

1. Declare the formats and capabilities they support.
2. Never modify the source.
3. Return partial results and explicit warnings when only part of a source can be read.
4. Identify locations where possible: page, sheet/cell, table/row, code symbol/line, archive member, image region, or media time range.
5. Record the tool/library and version used for extraction.
6. Enforce resource limits and return a bounded, explicit error when a limit is reached.
7. Never turn extraction failure into an empty success result.

## Format families

Format support is extensible and capability-based; this list is an initial target, not a claim that every format is already implemented.

| Family | Examples | Readable result |
|---|---|---|
| Plain text and structured text | TXT, Markdown, CSV, JSON, XML, YAML, logs | Text, records, tables, parse warnings |
| Office documents | DOCX, XLSX, PPTX, ODT and compatible formats | Paragraphs, tables, sheets/cells, slide text, media references |
| PDF | Text PDFs and scanned PDFs | Page text, tables where available, OCR text with page evidence |
| Source code and configuration | Python and other supported languages, SQL, INI, TOML, configuration files | Source text, symbols, imports, syntax/parse status; never execute |
| Databases | SQLite and supported database exports | Schema, table/column metadata, queryable data only with explicit limits and access policy |
| Images | Common raster formats and supported vector formats | Metadata, OCR text, image reference, optional descriptions from an explicitly configured model |
| Audio | Common audio formats | Metadata, transcript and time ranges when a speech adapter is available |
| Video | Common video formats | Metadata, timestamps, sampled-frame references, optional OCR/transcript |
| Archives and packages | ZIP, TAR, 7z and supported containers | Safe member inventory followed by independent intake of eligible members |
| Unknown or proprietary | Any unrecognized or unavailable format | Fingerprint, metadata, `UNSUPPORTED` status, and an adapter-needed report |

An adapter must report the exact capabilities used. For example, extracting embedded PDF text is not equivalent to OCR, and extracting a video file's metadata is not equivalent to understanding its audio or frames.

## Readable output and candidate units

Outputs are separated from originals and use a documented, stable representation such as UTF-8 text plus JSON metadata. Large outputs may be stored as files and referenced by path or object identifier.

Candidate units are formed by meaning and reuse potential, not by a fixed character, line, or token count. A unit can remain large when its context is necessary. Each candidate unit should include:

- `unit_id` and `source_id`.
- `kind` and `content` or a content reference.
- `source_location` and extraction evidence.
- Optional `input`, `output`, `capability`, and relationships when supported by the content.
- `quality_status`: `UNREVIEWED`, `VERIFIED`, or `REJECTED`.

Extraction alone does not make a candidate verified knowledge. Verification and later warehouse settlement belong to a separate workflow.

## Failure and partial-result behavior

- Unsupported, encrypted, corrupt, password-protected, or truncated inputs receive explicit statuses and actionable diagnostics.
- If one archive member fails, preserve successful member results and report the failed member; do not discard the whole archive result.
- If OCR, transcription, or an optional library is unavailable, report the missing capability and retain any other extracted content.
- Preserve source locations and hashes for partial results.
- Do not silently substitute an empty string, fabricated text, or a successful status.

## Safety and resource limits

- Treat all incoming files as untrusted data.
- Never execute imported programs, macros, embedded scripts, or package hooks during extraction.
- Keep extraction read-only and write generated outputs only to a designated output directory.
- Enforce configurable limits for file size, archive expansion, member count, recursion depth, processing time, and memory where available.
- Reject or explicitly skip archive path traversal, unsafe links, and members that escape the extraction workspace.
- Avoid loading entire large files into memory when streaming is supported.
- Keep secrets and credentials out of outputs and logs; apply configured redaction before exposing content.
- Optional external services must be disabled unless explicitly configured and must disclose what data leaves the machine.

## Extensibility

Adapters are registered by stable identifier and capability declaration. A new adapter must not require changes to unrelated adapters. Optional dependencies are loaded only for the formats that need them. Adapter selection may use extension, media type, signature detection, and a safe content probe; conflicts are recorded rather than hidden.

The core runner, each adapter, and output serializers are independently testable. Adding a format must include fixtures for success, partial extraction, malformed input, and limit enforcement.

## Acceptance criteria

The first usable release is complete when:

1. A caller can submit one file or a folder and receive a result for every discovered source.
2. Every result preserves the original source identity, fingerprint, detected format, and adapter version.
3. Supported input produces readable output with source locations or a documented reason locations are unavailable.
4. Unknown or failed inputs are reported as `UNSUPPORTED`, `PARTIAL`, or `FAILED`, never as a false success.
5. Archive members are inventoried and processed without escaping the output workspace.
6. Source files remain byte-for-byte unchanged after extraction.
7. Code, macros, and binaries are never executed during intake.
8. Each adapter passes success, malformed-input, partial-result, and resource-limit tests.
9. The output can be reviewed and reused independently of the intake runner.
10. New format support can be added without coupling unrelated system ideas.

## Initial implementation sequence

1. Define and test the intake record, adapter contract, and output layout.
2. Implement plain text, Markdown, JSON, CSV, and a safe archive inventory adapter.
3. Add document and PDF extraction, then OCR as an optional capability.
4. Add source-code and configuration analysis without execution.
5. Add spreadsheet, database, image, audio, and video adapters independently.
6. Measure coverage by format and extraction capability; publish unsupported cases and limitations.
7. Add integrations with other systems only through the documented records and outputs.

## Current implementation status

The first working implementation is `file_intake.py`. It writes `intake-report.json` and one Markdown file per readable source under `readable/`. Candidate units are marked `UNREVIEWED`; extraction does not promote knowledge or execute code.

| Capability | Current behavior |
|---|---|
| Text, Markdown, YAML/TOML/INI, SQL, JSON/JSONL, CSV/TSV, XML/HTML | Local extraction; Python is parsed for syntax and symbols but never executed |
| ZIP/TAR | Recursive in-memory member processing with path, depth, member-count, and size checks |
| DOCX/PPTX/ODF | Text extraction from document/slide/package XML; embedded media is reported, not OCR'd |
| XLSX | Sheet and cell extraction when optional `openpyxl` is installed |
| PDF | Embedded page text when optional `pypdf` is installed; scanned-page OCR is not implemented |
| SQLite | Read-only schema and bounded table previews for standalone database files |
| Images | Metadata when optional `Pillow` is installed; OCR only when `pytesseract` and Tesseract are configured |
| Audio/video | Basic WAV and container metadata only; transcription and video-frame decoding are not implemented |
| Other formats | Explicit unsupported/partial status; no false claim of successful extraction |

This is a usable foundation, not literal support for every proprietary or media format. Add each missing capability as an independently tested adapter; the report must continue to distinguish extracted content, metadata-only results, partial processing, and unsupported formats.

The attached runtime design is implemented in `sovereign_runtime.py`, with
`runtime/universal_intake.py` joining source registration to normalized output.
The runtime persists source records, transit counters, tickets, FSX event
history/current state, ONE_RUN evidence and receipts, and the Warehouse 35
registry under its configured runtime root. `run_one` is explicitly
ticket-gated and uses a temporary copy of the working directory, but that copy
is not a security sandbox. A successful process exit proves only that the
process exited successfully; it is not a substitute for domain tests or review.
