"""Offline checks of Qwen request construction and safe failure diagnostics."""
import json
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloud_demo"))
import remote_inference as r

EVIDENCE = {
    "patient": {"patient_id": "DEMO-P001", "full_name": "Invented Person"},
    "observations": [{"source_marker": "[SQL:DEMO-0001]", "value": 78}],
    "medications": [], "notes": [], "conditions": [], "limitations": "Fictional fixture"
}


class DiagnosticsTests(unittest.TestCase):
    def test_url_from_mixlayer_docs(self):
        self.assertEqual(r.chat_completion_url("https://mixlayer.ai/v1"), "https://mixlayer.ai/v1/chat/completions")

    def test_local_endpoint_still_blocked(self):
        for url in ("http://mixlayer.ai/v1", "https://localhost:11434/v1", "https://10.1.1.1/v1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                r.chat_completion_url(url)

    def test_non_thinking_mode_and_exact_citation_prompt(self):
        captured = {}
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self, n):
                return b'{"choices": [{"message": {"content": "78 [SQL:DEMO-0001]"}}]}'
        def fake_open(req, timeout):
            captured["request"] = req
            captured["timeout"] = timeout
            return Response()
        with patch.object(r, "urlopen", side_effect=fake_open):
            answer = r.remote_qwen_answer(evidence=EVIDENCE, question="What measurement?", api_base="https://mixlayer.ai/v1", model_id="qwen/qwen3.5-4b-free", api_key="SECRET")
        self.assertEqual(answer, "78 [SQL:DEMO-0001]")
        payload = json.loads(captured["request"].data)
        self.assertEqual(payload["reasoning_effort"], "none")
        self.assertGreaterEqual(payload["max_tokens"], 650)
        self.assertIn("[SQL:DEMO-0001]", payload["messages"][1]["content"])

    def test_safe_http_status(self):
        with patch.object(r, "urlopen", side_effect=HTTPError("https://mixlayer.ai/v1/chat/completions", 401, "authorization SECRET", {}, None)):
            with self.assertRaises(r.RemoteInferenceError) as err:
                r.remote_qwen_answer(evidence=EVIDENCE, question="A", api_base="https://mixlayer.ai/v1", model_id="qwen/qwen3.5-4b-free", api_key="SECRET")
        self.assertEqual(err.exception.code, "AUTHENTICATION_FAILED")
        self.assertNotIn("SECRET", str(err.exception))

    def test_empty_model_content(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self, n): return b'{"choices": [{"message": {"content": ""}}]}'
        with patch.object(r, "urlopen", return_value=Response()):
            with self.assertRaises(r.RemoteInferenceError) as err:
                r.remote_qwen_answer(evidence=EVIDENCE, question="A", api_base="https://mixlayer.ai/v1", model_id="qwen/qwen3.5-4b-free", api_key="SECRET")
        self.assertEqual(err.exception.code, "EMPTY_MODEL_CONTENT")

    def test_ui_has_safe_diagnostics(self):
        source = (ROOT / "cloud_demo" / "streamlit_app.py").read_text()
        self.assertIn('fallback_reason = "CITATION_CHECK_FAILED"', source)
        self.assertIn('fallback_reason = exc.code', source)
        self.assertIn('"fallback_reason":fallback_reason', source)
        self.assertEqual(source.count('Hosted-model diagnostic:'), 2)

if __name__ == "__main__":
    unittest.main()
