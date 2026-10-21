# Windows 98 intake promotion

`promote_windows98_intake.py` classifies one intake from the FileScanner
SQLite database into a human-review queue. It does not execute imported files
or write to a gold dataset.

## Run

```powershell
python promote_windows98_intake.py --db "C:\Projects\MyBrain_System\FileScannerSystem\out\_analysis\filescanner_intake.db" --dry-run
python promote_windows98_intake.py --db "C:\Projects\MyBrain_System\FileScannerSystem\out\_analysis\filescanner_intake.db"
python promote_windows98_intake.py --db "C:\Projects\MyBrain_System\FileScannerSystem\out\_analysis\filescanner_intake.db" --intake-id windows98_zip_intake_20260707_100444
```

The default database is `out\_analysis\filescanner_intake.db` beside the
script. `--dry-run` opens the database read-only and reports candidates,
existing queue entries, data-quality warnings, and the number of entries that
would be queued. It does not create tables or write a promotion-run record.

## Data handling

- Skips entries categorized as `skipped_noise`; build/vendor paths stay
  metadata-only.
- Normalizes path separators and case for duplicate detection and queue
  idempotency. When the stored extension conflicts with the filename, the
  filename extension is used and a warning is recorded.
- Promotes unsafe file types to quarantine even when their extension is not in
  the ordinary promotion allowlist.
- Preserves the no-copy policy for PDF/DOCX and the review-only policy for
  religious-text matches. Imported code is classified for review; it is never
  executed.
- Replaces malformed tag JSON with an empty list in the review queue and
  reports the source-data issue.
- Inserts queue entries and their run summary atomically. Repeated runs report
  existing items instead of inserting duplicate normalized paths.

Reports include candidate and queue counts, layer/action counts, skipped-noise
and duplicate-path counts, and up to 100 data-quality warnings.

## Tests

```powershell
python -m unittest discover -s tests -p "test_promotion.py" -v
```
