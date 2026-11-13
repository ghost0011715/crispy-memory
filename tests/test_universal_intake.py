import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from runtime.capability_registry import capabilities_for
from runtime.universal_intake import UniversalIntake
from sovereign_runtime import SovereignRuntime


class UniversalIntakeTests(unittest.TestCase):
    def test_normalization_writes_packet_manifest_and_flow_events(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            allowed = root / "allowed"
            allowed.mkdir()
            source = allowed / "idea.txt"
            source.write_text("A reusable idea.", encoding="utf-8")
            runtime = SovereignRuntime(root / "runtime", allowed_roots=[allowed])
            intake = UniversalIntake(runtime)

            packet = intake.ingest(source)

            self.assertEqual(packet["state"], "PASS")
            self.assertEqual(packet["detected_kind"], "text")
            self.assertTrue(Path(packet["derived_manifest"]).is_file())
            self.assertTrue(Path(packet["text_ref"]).is_file())
            saved = json.loads(Path(packet["derived_manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(saved["records"][0]["content_sha256"], packet["source_sha256"])
            self.assertEqual(intake.read_normalized(packet["source_id"])[0]["packet_id"], packet["packet_id"])
            events = runtime.events(packet["source_id"])
            self.assertEqual(events[-1]["operation"], "READABLE_NORMALIZATION_PASS")
            self.assertEqual(events[-1]["to_state"], "PASS")

    def test_missing_optional_provider_is_reported_as_hold(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            allowed = root / "allowed"
            allowed.mkdir()
            source = allowed / "picture.png"
            source.write_bytes(b"\x89PNG\r\n\x1a\ninvalid image")
            runtime = SovereignRuntime(root / "runtime", allowed_roots=[allowed])

            original_import = __import__

            def without_pillow(name, *args, **kwargs):
                if name == "PIL" or name.startswith("PIL."):
                    raise ImportError("Pillow intentionally unavailable in this test")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=without_pillow):
                packet = UniversalIntake(runtime).ingest(source)

            capability_ids = [item["capability_id"] for item in packet["capabilities"]]
            self.assertEqual(packet["state"], "HOLD")
            self.assertIn("IMAGE_READ", capability_ids)
            self.assertIn("IMAGE_OCR", capability_ids)
            self.assertIn("PILLOW", packet["provider_required"])
            self.assertTrue(any("Install Pillow" in item for item in packet["warnings"]))

    def test_capability_registry_reports_partial_media_support(self):
        audio = capabilities_for(".wav")
        transcription = next(item for item in audio if item["capability_id"] == "SPEECH_TRANSCRIPTION")
        self.assertEqual(transcription["mode"], "NOT_IMPLEMENTED")


if __name__ == "__main__":
    unittest.main()
