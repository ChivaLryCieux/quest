"""Tests for the unified Position model."""

import unittest

from core.models.position import Position


class PositionModelTest(unittest.TestCase):
    def test_flat_by_default(self):
        pos = Position()
        self.assertTrue(pos.is_flat)
        self.assertEqual(pos.direction, 0)
        self.assertEqual(pos.raw_pnl_pct(100.0), 0.0)
        self.assertEqual(pos.unrealized_pnl(100.0), 0.0)

    def test_long_short_math(self):
        long = Position(size=2.0, entry_price=100.0, leverage=10.0)
        self.assertTrue(long.is_long)
        self.assertAlmostEqual(long.raw_pnl_pct(101.0), 0.01)
        self.assertAlmostEqual(long.unrealized_pnl(101.0), 2.0)
        self.assertAlmostEqual(long.margin_used(), 20.0)

        short = Position(size=-2.0, entry_price=100.0, leverage=10.0)
        self.assertEqual(short.direction, -1)
        self.assertAlmostEqual(short.raw_pnl_pct(99.0), 0.01)
        self.assertAlmostEqual(short.unrealized_pnl(99.0), 2.0)

    def test_dict_roundtrip(self):
        pos = Position(size=1.5, entry_price=50.0, sl=49.0, tp=52.0,
                       entry_time=123, leverage=5.0, cluster=3)
        data = pos.to_dict()
        restored = Position.from_dict(data)
        self.assertEqual(restored.size, 1.5)
        self.assertEqual(restored.leverage, 5.0)
        self.assertEqual(restored.cluster, 3)

    def test_web_snapshot(self):
        pos = Position(size=1.0, entry_price=100.0, leverage=10.0)
        snap = pos.to_web_dict(price=102.0)
        self.assertEqual(snap["size"], 1.0)
        self.assertAlmostEqual(snap["unrealized_pnl"], 2.0)


if __name__ == "__main__":
    unittest.main()
