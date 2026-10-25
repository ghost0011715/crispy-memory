import json
import gzip
import hashlib
import tarfile
import tempfile
import unittest
import wave
import zipfile
from io import BytesIO
from pathlib import Path

from file_intake import FileIntake, IntakeError, Limits


class FileIntakeTests(unittest.TestCase):
    def test_text_and_python_are_read_without_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.py"
            marker = root / "executed"
            source.write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n",
                encoding="utf-8",
            )
            original = source.read_bytes()

            report = FileIntake(root / "out").process(source)

            record = report["records"][0]
            self.assertEqual(record["status"], "EXTRACTED")
            self.assertEqual(record["metadata"]["python_syntax"], "valid")
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(marker.exists())
            self.assertTrue((root / "out" / record["readable_output_path"]).is_file())

    def test_csv_and_json_have_readable_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "table.csv").write_text("name,value\nA,1\n", encoding="utf-8")
            (root / "data.json").write_text('{"answer": 42}', encoding="utf-8")

            report = FileIntake(root / "out").process(root)

            records = {row["original_name"]: row for row in report["records"]}
            self.assertIn("| A | 1 |", records["table.csv"]["readable_output"])
            self.assertIn('"answer": 42', records["data.json"]["readable_output"])
            self.assertEqual(report["summary"]["extracted"], 2)

    def test_zip_members_are_processed_without_extraction_to_disk(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "bundle.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("notes/readme.txt", "Hello from archive")
                archive.writestr("../outside.txt", "must not escape")

            report = FileIntake(root / "out").process(archive_path)

            self.assertEqual(report["records"][0]["detected_format"], "zip")
            member = next(row for row in report["records"] if row["original_name"] == "readme.txt")
            self.assertEqual(member["status"], "EXTRACTED")
            self.assertTrue(report["records"][0]["warnings"])
            self.assertFalse((root / "outside.txt").exists())

    def test_gzip_wrapped_text_is_decompressed_and_linked_to_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "notes.txt.gz"
            source.write_bytes(gzip.compress(b"compressed readable text"))

            report = FileIntake(root / "out").process(source)

            container, member = report["records"]
            self.assertEqual(container["detected_format"], "gzip")
            self.assertEqual(container["status"], "EXTRACTED")
            self.assertEqual(member["container_source_id"], container["source_id"])
            self.assertEqual(member["readable_output"], "compressed readable text")

    def test_tar_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "bundle.tar"
            buffer = BytesIO()
            with tarfile.open(fileobj=buffer, mode="w") as archive:
                link = tarfile.TarInfo("link")
                link.type = tarfile.SYMTYPE
                link.linkname = "../../outside"
                archive.addfile(link)
                text = b"safe"
                member = tarfile.TarInfo("safe.txt")
                member.size = len(text)
                archive.addfile(member, BytesIO(text))
            archive_path.write_bytes(buffer.getvalue())

            report = FileIntake(root / "out").process(archive_path)

            self.assertEqual(report["records"][0]["status"], "PARTIAL")
            self.assertIn("Non-regular tar member skipped", report["records"][0]["warnings"][0])
            self.assertTrue(any(row["original_name"] == "safe.txt" for row in report["records"]))

    def test_docx_text_is_extracted_with_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "document.docx"
            document_xml = (
                b'<?xml version="1.0" encoding="UTF-8"?>'
                b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                b"<w:body><w:p><w:r><w:t>Readable paragraph</w:t></w:r></w:p></w:body></w:document>"
            )
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("word/document.xml", document_xml)

            report = FileIntake(root / "out").process(source)

            record = report["records"][0]
            self.assertEqual(record["detected_format"], "docx")
            self.assertIn("Readable paragraph", record["readable_output"])
            self.assertEqual(record["units"][0]["quality_status"], "UNREVIEWED")
            self.assertEqual(record["status"], "EXTRACTED")

    def test_xlsx_adapter_reads_sheet_values_when_available(self):
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest("openpyxl is not installed.")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "book.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Facts"
            sheet.append(["name", "value"])
            sheet.append(["answer", 42])
            workbook.save(source)
            workbook.close()

            report = FileIntake(root / "out").process(source)

            record = report["records"][0]
            self.assertEqual(record["detected_format"], "xlsx")
            self.assertIn("answer", record["readable_output"])
            self.assertIn("42", record["readable_output"])

    def test_sqlite_is_read_without_mutation(self):
        import sqlite3

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "data.sqlite"
            connection = sqlite3.connect(source)
            connection.execute("CREATE TABLE facts (name TEXT, value INTEGER)")
            connection.execute("INSERT INTO facts VALUES ('answer', 42)")
            connection.commit()
            connection.close()
            original_hash = hashlib.sha256(source.read_bytes()).hexdigest()

            report = FileIntake(root / "out").process(source)

            record = report["records"][0]
            self.assertEqual(record["status"], "EXTRACTED")
            self.assertIn("answer", record["readable_output"])
            self.assertEqual(record["content_sha256"], original_hash)

    def test_wav_metadata_is_read_and_transcription_limit_is_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "audio.wav"
            with wave.open(str(source), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8_000)
                audio.writeframes(b"\0\0" * 80)

            report = FileIntake(root / "out").process(source)

            record = report["records"][0]
            self.assertEqual(record["status"], "PARTIAL")
            self.assertEqual(record["metadata"]["sample_rate_hz"], 8_000)
            self.assertIn("Speech transcription is not configured.", record["warnings"])

    def test_pdf_pages_are_reported_even_without_embedded_text(self):
        try:
            from pypdf import PdfWriter
        except ImportError:
            self.skipTest("pypdf is not installed.")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "blank.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=72, height=72)
            with source.open("wb") as output:
                writer.write(output)

            report = FileIntake(root / "out").process(source)

            record = report["records"][0]
            self.assertEqual(record["detected_format"], "pdf")
            self.assertEqual(record["metadata"]["page_count"], 1)
            self.assertEqual(record["status"], "PARTIAL")
            self.assertTrue(any(unit["source_location"] == {"page": 1} for unit in record["units"]))

    def test_image_metadata_is_read_and_missing_ocr_is_explicit(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is not installed.")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "pixel.png"
            Image.new("RGB", (2, 3), color="white").save(source)

            report = FileIntake(root / "out").process(source)

            record = report["records"][0]
            self.assertEqual(record["detected_format"], "image")
            self.assertEqual(record["metadata"]["width"], 2)
            self.assertIn("Image metadata", record["readable_output"])
            self.assertEqual(record["status"], "PARTIAL")

    def test_malformed_json_is_failed_not_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "bad.json"
            source.write_text("{broken", encoding="utf-8")

            report = FileIntake(root / "out").process(source)

            self.assertEqual(report["records"][0]["status"], "FAILED")
            self.assertTrue(report["records"][0]["errors"])

    def test_oversized_source_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "large.txt"
            source.write_text("123456", encoding="utf-8")
            intake = FileIntake(root / "out", Limits(max_file_bytes=4))

            report = intake.process(source)

            self.assertEqual(report["records"][0]["status"], "FAILED")
            self.assertIn("FILE_SIZE_LIMIT_EXCEEDED", report["records"][0]["errors"][0])

    def test_report_is_valid_json_and_contains_fingerprints(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "note.txt"
            source.write_text("readable", encoding="utf-8")
            output = root / "out"

            report = FileIntake(output).process(source)

            saved = json.loads((output / "intake-report.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["records"][0]["content_sha256"], report["records"][0]["content_sha256"])
            self.assertEqual(len(saved["records"][0]["content_sha256"]), 64)

    def test_rejects_symlink_source_when_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "source.txt"
            target.write_text("data", encoding="utf-8")
            link = root / "link.txt"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("Symlink creation is not available.")

            with self.assertRaisesRegex(IntakeError, "SOURCE_SYMLINK_NOT_ALLOWED"):
                FileIntake(root / "out").process(link)


if __name__ == "__main__":
    unittest.main()
