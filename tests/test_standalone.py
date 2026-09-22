"""Unit tests for standalone binary release pipeline (jarvis.spec & build_standalone.py)."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.build_standalone import default_asset_name
from jarvis.server import UI_DIR


class TestStandalonePipeline(unittest.TestCase):

    def test_spec_file_exists(self) -> None:
        self.assertTrue(os.path.exists("jarvis.spec"), "jarvis.spec must exist")

    def test_default_asset_name(self) -> None:
        name = default_asset_name()
        self.assertTrue(name.startswith("jarvis-"), f"Unexpected asset name: {name}")

    def test_ui_dir_valid(self) -> None:
        self.assertTrue(os.path.isdir(UI_DIR), f"UI_DIR {UI_DIR} must be a directory")


if __name__ == "__main__":
    unittest.main()
