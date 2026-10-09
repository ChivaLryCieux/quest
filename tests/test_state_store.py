"""Tests for runtime state persistence (StateStore)."""

import json
import os
import shutil
import tempfile
import unittest

from core.engine.state_store import StateStore


class StateStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="quest_state_")
        self.store = StateStore(self.tmp, "state.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_file_returns_empty(self):
        self.assertEqual(self.store.load(), {})
        self.assertFalse(self.store.exists)
        self.assertIsNone(self.store.snapshot_meta())

    def test_save_and_load_roundtrip(self):
        state = {
            "balance": 123.45,
            "position": {"size": 1.0, "entry_price": 100.0, "leverage": 5.0},
            "trade_history": [{"pnl": 1.5, "duration_min": 10.0}],
        }
        self.assertTrue(self.store.save(state))
        self.assertTrue(self.store.exists)

        loaded = self.store.load()
        self.assertAlmostEqual(loaded["balance"], 123.45)
        self.assertEqual(loaded["position"]["size"], 1.0)
        self.assertEqual(len(loaded["trade_history"]), 1)
        self.assertIn("saved_at", loaded)
        self.assertIn("schema_version", loaded)

        meta = self.store.snapshot_meta()
        self.assertAlmostEqual(meta["balance"], 123.45)

    def test_corrupted_file_does_not_crash(self):
        with open(self.store.path, "w", encoding="utf-8") as fh:
            fh.write("{ not valid json")
        self.assertEqual(self.store.load(), {})

    def test_overwrite_is_atomic(self):
        self.store.save({"balance": 10.0})
        self.store.save({"balance": 20.0})
        self.assertAlmostEqual(self.store.load()["balance"], 20.0)
        # 临时文件不应残留
        self.assertFalse(os.path.exists(self.store.path + ".tmp"))
        # 文件必须是合法 JSON
        with open(self.store.path, "r", encoding="utf-8") as fh:
            json.load(fh)


if __name__ == "__main__":
    unittest.main()
