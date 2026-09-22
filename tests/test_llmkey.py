"""v11: LLM key resolution — env var precedence, inline config fallback,
graceful absence (tests/test_llmkey.py)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, ".")

from jarvis.brain.llm import LLMBrain


def _cfg(key="", provider="openai"):
    return {"llm": {"provider": provider, "openai_base_url":
                    "https://tokenharbor.ai/v1",
                    "openai_model": "deepseek-v4.1-flash:free",
                    "openai_api_key_env": "OPENAI_API_KEY",
                    "openai_api_key": key, "ollama_base_url":
                    "http://127.0.0.1:1/v1"},   # nothing there
            "user": {"name": "Boss"}}


class TestKeyResolution(unittest.TestCase):
    def test_inline_key_activates_brain(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            b = LLMBrain(_cfg("thk_live_xyz"))
        self.assertTrue(b.available)
        self.assertEqual(b.label, "deepseek-v4.1-flash:free")
        self.assertEqual(b._headers()["Authorization"], "Bearer thk_live_xyz")

    def test_env_beats_inline(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "env-key"}):
            b = LLMBrain(_cfg("inline-key"))
            self.assertEqual(b._headers()["Authorization"], "Bearer env-key")

    def test_no_key_never_claims_a_brain(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            b = LLMBrain(_cfg(""))
        self.assertFalse(b.available)
        self.assertEqual(b.label, "rule brain")


if __name__ == "__main__":
    unittest.main(verbosity=2)
