"""Tests for error tiering: OrderError must surface, not be swallowed."""

import unittest

from core.errors import (
    ConfigError,
    ConnectionError,
    DataError,
    OrderError,
    QuestError,
)


class ErrorHierarchyTest(unittest.TestCase):
    def test_all_derive_from_quest_error(self):
        for cls in (ConfigError, ConnectionError, DataError, OrderError):
            self.assertTrue(issubclass(cls, QuestError))
            self.assertTrue(issubclass(cls, Exception))

    def test_catch_base_class(self):
        with self.assertRaises(QuestError):
            raise OrderError("boom")

    def test_chained_context(self):
        cause = RuntimeError("network down")
        try:
            raise OrderError("order failed") from cause
        except OrderError as exc:
            self.assertIs(exc.__cause__, cause)


class LiveOrderErrorTest(unittest.TestCase):
    """实盘下单失败必须抛 OrderError；纸盘不受影响。"""

    def test_paper_returns_true(self):
        from core.config.exchange import ExchangeService
        svc = ExchangeService.__new__(ExchangeService)
        svc.is_live = False
        svc.symbol = "SOL/USDT"
        svc.paper_orders = []
        self.assertTrue(svc.execute_order("buy", 1.0))

    def test_insufficient_funds_raises(self):
        import ccxt
        from core.config.exchange import ExchangeService
        svc = ExchangeService.__new__(ExchangeService)
        svc.is_live = True
        svc.symbol = "SOL/USDT"

        class FakeLock:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class BadClient:
            def create_market_order(self, *args, **kwargs):
                raise ccxt.InsufficientFunds("no money")

        svc.api_lock = FakeLock()
        svc.client = BadClient()
        with self.assertRaises(OrderError):
            svc.execute_order("buy", 1.0)

    def test_bad_status_raises(self):
        from core.config.exchange import ExchangeService

        class FakeLock:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class WeirdClient:
            def create_market_order(self, *args, **kwargs):
                return {"status": "weird"}

        svc = ExchangeService.__new__(ExchangeService)
        svc.is_live = True
        svc.symbol = "SOL/USDT"
        svc.api_lock = FakeLock()
        svc.client = WeirdClient()
        with self.assertRaises(OrderError):
            svc.execute_order("buy", 1.0)


if __name__ == "__main__":
    unittest.main()
