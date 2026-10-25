# ghost
pro

## Readable file intake

`file_intake.py` is an independent, read-only intake tool. It scans one file or a
directory, extracts supported content without executing imported code, and writes
traceable JSON and Markdown results to a separate output directory.

```powershell
python file_intake.py "C:\path\to\files" --output "C:\path\to\intake-output"
```

The first implementation supports text and common structured text, Python
source inspection, CSV/TSV, XML/HTML, DOCX/XLSX/PPTX and ODF text, SQLite
metadata and bounded table previews, PDF text extraction, image metadata,
basic WAV metadata, video container metadata, and safe ZIP/TAR member
processing. XLSX requires the optional `openpyxl` package, PDF extraction
requires `pypdf`, and image metadata/OCR requires `Pillow` and optionally
`pytesseract` plus a Tesseract installation. Scanned PDF OCR, speech
transcription, and video-frame decoding are not implemented yet. OCR and other
unavailable capabilities are reported rather than represented as successful
extraction. Unsupported formats receive an explicit status; support can be
added through independent adapters.

Results are written to `intake-report.json` and the `readable` subdirectory.
Original files are not changed. Imported code, macros, and binaries are never
executed. Default limits are defined in `file_intake.py` and can be overridden
through the Python API.

### Nova, FSX and ONE_RUN runtime

`sovereign_runtime.py` provides a separate local runtime for source identity,
transit IDs, tickets, append-only FSX events, explicit ticket authorization,
ONE_RUN receipts, sequential stations, and Warehouse 35 settlement.
`runtime/universal_intake.py` connects that runtime to `file_intake.py` and
persists source-linked normalized packets. The standalone adapter entry point
is `tools/readable_extract.py`.

```powershell
python sovereign_runtime.py --status
python sovereign_runtime.py "C:\path\to\file.zip" --runtime-root "C:\path\to\runtime"
python tools/readable_extract.py --source "C:\path\to\file.pdf" --out-dir "C:\path\to\output"
```

Runtime data is stored under `.runtime_data/` by default; set
`NOVADESK_RUNTIME_ROOT` and `NOVADESK_ALLOWED_ROOTS` to control its location and
the paths it may inspect. `run_one` requires an authorized ticket and an
allowlisted executable, uses `shell=False`, copies the working directory to a
temporary Shadow workspace, limits captured output, and records a receipt.
This temporary copy is **not an operating-system sandbox**: authorized code can
still access host resources. Only run trusted code, and do not treat a passing
exit code as proof of correctness. The seven station transitions require
sequential PASS states and evidence; settlement verifies the ONE_RUN receipt
and evidence hash.
