# FileScanner

A dependency-free Python command-line tool for scanning local directories,
summarizing file sizes and extensions, and finding identical files by SHA-256.
Scanned file contents are not uploaded or executed.

## Requirements

- Python 3.9 or newer
- No third-party packages

## Usage

```powershell
python cli.py --help
python cli.py --scan .
python cli.py --scan "C:\Users\you\Documents" --find-duplicates
python cli.py --scan . --filter-ext ".py,.md" --analyze --output report.json
python cli.py --interactive
```

Hidden files and directories are excluded by default. Add `--include-hidden` to
include them. Python `__pycache__` directories and `.pyc`/`.pyo` bytecode are
always excluded. `--analyze` prints a local summary; it does not use ChatGPT or
send files to an external service. JSON reports are written as UTF-8.

## Run tests

```powershell
python -m unittest discover -s tests -v
```
