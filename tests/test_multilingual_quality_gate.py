import hashlib
import math
import unittest

from runtime.multilingual_quality_gate import (
    audit_chat_response,
    audit_dataset,
    audit_evaluation_groups,
    audit_sft_labels,
    audit_training_preflight,
)


class MultilingualQualityGateTests(unittest.TestCase):
    def samples(self):
        return [
            {"sample_id": "ar-1", "source_id": "SRC-AR", "transit_id": "Txt-000-000-001", "conversation_id": "D-AR", "split": "train", "language": "ar-SA", "text": "\u0644\u0627 \u062a\u062d\u0630\u0641 \u0627\u0644\u0623\u0635\u0644\u060c \u0627\u062d\u0641\u0638 \u0627\u0644\u0623\u062f\u0644\u0629\u064e."},
            {"sample_id": "en-1", "source_id": "SRC-EN", "split": "train", "language": "en-US", "text": "Do not delete the original; retain the evidence."},
            {"sample_id": "fr-1", "source_id": "SRC-FR", "split": "validation", "language": "fr-FR", "text": "L'\u00e9l\u00e8ve demande une r\u00e9ponse pr\u00e9cise."},
            {"sample_id": "es-1", "source_id": "SRC-ES", "split": "test", "language": "es-ES", "text": "\u00a1No borres el archivo original, conserva las pruebas!"},
        ]

    def package(self):
        return {
            "samples": self.samples(),
            "expected_split_counts": {"train": 2, "validation": 1, "test": 1},
            "train_labels": [[101, 51, 52], [101, 61, 62]],
            "required_languages": ["ar", "en", "fr", "es"],
        }

    def test_four_languages_are_structurally_supported_without_text_mutation(self):
        p = self.package()
        original_texts = [s["text"] for s in p["samples"]]
        result = audit_training_preflight(p)
        self.assertEqual(result["state"], "PASS", result)
        self.assertEqual(result["evidence_state"], "VERIFIED_BOUNDED")
        self.assertEqual(result["dataset"]["languages"], {"ar": 1, "en": 1, "fr": 1, "es": 1})
        self.assertEqual([s["text"] for s in p["samples"]], original_texts)
        self.assertEqual(result["dataset"]["sample_receipts"][0]["text_sha256"], hashlib.sha256(original_texts[0].encode("utf-8")).hexdigest())
        self.assertEqual(result["dataset"]["sample_receipts"][0]["transit_id"], "Txt-000-000-001")
        self.assertNotIn("text", result["dataset"]["sample_receipts"][0])

    def test_arbitrary_valid_language_tag_allowed(self):
        data = self.samples()
        data[0]["language"] = "de-DE"
        self.assertEqual(audit_dataset(data)["state"], "PASS")

    def test_source_cross_split_blocked(self):
        data = self.samples()
        data[2]["source_id"] = data[0]["source_id"]
        result = audit_dataset(data)
        self.assertEqual(result["state"], "HOLD")
        self.assertTrue(any(b.startswith("CROSS_SPLIT_SOURCE:") for b in result["blockers"]))

    def test_conversation_cross_split_blocked(self):
        data = self.samples()
        data[3]["conversation_id"] = data[0]["conversation_id"]
        result = audit_dataset(data)
        self.assertIn("CROSS_SPLIT_CONVERSATION:ar-1:es-1", result["blockers"])

    def test_family_cross_split_blocked(self):
        data = self.samples()
        data[0]["family_id"] = data[2]["family_id"] = "FAMILY-X"
        result = audit_dataset(data)
        self.assertIn("CROSS_SPLIT_FAMILY:ar-1:fr-1", result["blockers"])

    def test_exact_text_duplicate_blocked(self):
        data = self.samples()
        data[2]["text"] = data[0]["text"]
        result = audit_dataset(data)
        self.assertIn("CROSS_SPLIT_EXACT_TEXT:ar-1:fr-1", result["blockers"])

    def test_nfkc_casefold_leak_is_detection_only(self):
        data = self.samples()
        data[0]["text"] = "Full-width \uff21\uff22\uff23 and a phrase"
        data[2]["text"] = "full-width ABC and a phrase"
        result = audit_dataset(data)
        self.assertIn("CROSS_SPLIT_NORMALIZED_TEXT:ar-1:fr-1", result["blockers"])
        self.assertIn("\uff21", data[0]["text"])

    def test_near_duplicate_candidates_blocked(self):
        data = self.samples()
        data[0]["text"] = "one two three four five six seven eight nine ten eleven twelve"
        data[2]["text"] = "one two three four five six seven eight nine ten eleven twelve extra"
        result = audit_dataset(data)
        self.assertIn("CROSS_SPLIT_NEAR_DUPLICATE:ar-1:fr-1", result["blockers"])

    def test_pair_budget_never_passes_unverified(self):
        result = audit_dataset(self.samples(), max_pairs=0)
        self.assertEqual(result["state"], "NOT_VERIFIED")
        self.assertIn("NEAR_DUPLICATE_SCAN_INCOMPLETE", result["blockers"])

    def test_missing_or_mismatched_counts_hold(self):
        p = self.package()
        p["expected_split_counts"]["test"] = 2
        self.assertIn("SPLIT_COUNT_MISMATCH:test", audit_training_preflight(p)["blockers"])
        p.pop("expected_split_counts")
        self.assertEqual(audit_training_preflight(p)["state"], "HOLD")

    def test_zero_effective_sft_targets_are_not_learning(self):
        result = audit_sft_labels([[-100, -100, -100]], expected_train_samples=1)
        self.assertIn("ZERO_SUPERVISED_TARGETS:0", result["blockers"])
        self.assertEqual(result["supervised_targets"], 0)

    def test_shifted_target_validity_and_count(self):
        result = audit_sft_labels([[999, -100, 42], [999, 10, 11]], expected_train_samples=2)
        self.assertEqual(result["state"], "PASS")
        self.assertEqual(result["supervised_targets"], 3)

    def test_language_presence_required_only_when_requested(self):
        p = self.package()
        p["required_languages"] = ["ar", "ja"]
        self.assertIn("LANGUAGE_NOT_OBSERVED:ja", audit_training_preflight(p)["blockers"])

    def test_evaluation_groups_separate_with_finite_metrics(self):
        groups = {"validation_ar": {"expected": 2, "actual": 2, "metrics": {"loss": 1.1}},
                  "validation_fr": {"expected": 2, "actual": 2, "metrics": {"loss": 2.1}}}
        self.assertEqual(audit_evaluation_groups(groups)["state"], "PASS")
        groups["validation_fr"]["actual"] = 1
        self.assertIn("EVALUATION_COUNT_MISMATCH:validation_fr", audit_evaluation_groups(groups)["blockers"])
        groups["validation_ar"]["metrics"]["loss"] = math.nan
        self.assertIn("EVALUATION_METRIC_INVALID:validation_ar", audit_evaluation_groups(groups)["blockers"])

    def chat_request(self):
        return {"session_id": "SESSION-1", "model_sha256": "a" * 64,
                "tokenizer_sha256": "b" * 64,
                "messages": [{"role": "user", "content": "\u00bfPuedes responder en espa\u00f1ol?"}]}

    def chat_response(self):
        return {"session_id": "SESSION-1", "model_sha256": "a" * 64,
                "tokenizer_sha256": "b" * 64, "status_code": 200,
                "finish_reason": "stop", "content": "S\u00ed, puedo.",
                "stream_chunks": ["S\u00ed, ", "puedo."]}

    def test_chat_valid_reply_and_tool_boundary(self):
        result = audit_chat_response(self.chat_request(), self.chat_response())
        self.assertEqual(result["state"], "PASS")
        self.assertFalse(result["tool_execution_authorized"])

    def test_chat_empty_200_is_not_pass(self):
        data = self.chat_response()
        data["content"] = ""
        data["stream_chunks"] = []
        self.assertIn("CHAT_EMPTY_SUCCESS_RESPONSE", audit_chat_response(self.chat_request(), data)["blockers"])

    def test_chat_stream_truncation_detected(self):
        data = self.chat_response()
        data["stream_chunks"] = ["S\u00ed"]
        self.assertIn("CHAT_STREAM_CONTENT_MISMATCH", audit_chat_response(self.chat_request(), data)["blockers"])

    def test_chat_cache_model_mismatch_detected(self):
        data = self.chat_response()
        data["model_sha256"] = "c" * 64
        self.assertIn("CHAT_MODEL_SHA256_MISMATCH", audit_chat_response(self.chat_request(), data)["blockers"])

    def test_chat_truncated_length_not_pass(self):
        data = self.chat_response()
        data["finish_reason"] = "length"
        self.assertIn("CHAT_REPLY_INCOMPLETE", audit_chat_response(self.chat_request(), data)["blockers"])

    def test_chat_tool_parse_not_execution_grant(self):
        data = self.chat_response()
        data.update({"finish_reason": "tool_calls", "content": "", "stream_chunks": [],
                     "tool_calls": [{"name": "calculator", "arguments": "{}"}]})
        result = audit_chat_response(self.chat_request(), data)
        self.assertEqual(result["state"], "PASS")
        self.assertFalse(result["tool_execution_authorized"])


if __name__ == "__main__":
    unittest.main()
